"""Named document flows; snapshots stay request-local and are read exactly once."""

from collections.abc import Callable
from time import perf_counter

from langchain_core.runnables import RunnableBranch, RunnableLambda, RunnablePassthrough

from app.diagnostics.trace import named_trace_config, record_retrieval, record_routing

EMPTY_DOCUMENTS = "현재 확인 가능한 회사 문서가 없어 답변하기 어렵습니다."
EMPTY_RETRIEVAL = "관련 문서에서 답변에 필요한 근거를 찾지 못했습니다."


def _stage(function, name):
    return RunnableLambda(function).with_config(
        **named_trace_config(run_name=name, stage=name, role="chain")
    )


def _notice(text, path):
    def respond(_):
        record_routing({"processing_path": path, "generation_attempted": False})
        return text

    return _stage(respond, path)


def _document_flow(
    read_documents, render, answer, retrieve=None, *, allow_empty_retrieval=False
):
    if allow_empty_retrieval and retrieve is None:
        raise ValueError("Empty retrieval generation requires a RAG flow")

    def snapshot(_):
        record_routing(
            {"processing_path": "document_lookup", "generation_attempted": False}
        )
        return read_documents()

    def retrieve_context(state):
        record_routing({"processing_path": "retrieval", "generation_attempted": False})
        started = perf_counter()
        try:
            context = retrieve(state["question"], state["snapshot"])
        except Exception:
            record_retrieval(
                status="failed", seconds=perf_counter() - started, selected_count=0
            )
            raise
        record_retrieval(
            status="ok",
            seconds=perf_counter() - started,
            selected_count=len(context.evidence),
            metadata={
                "snapshot_fingerprint": getattr(context, "snapshot_fingerprint", ""),
                "spec_id": getattr(context, "spec_id", ""),
                "search_config_id": getattr(context, "search_config_id", ""),
                "candidate_count": getattr(context, "candidate_count", 0),
                "selected_chunk_ids": [
                    chunk_id
                    for item in context.evidence
                    if isinstance(getattr(item, "chunk_ids", None), (tuple, list))
                    for chunk_id in item.chunk_ids
                ],
                "scores": [getattr(item, "score", None) for item in context.evidence],
                "ranks": [getattr(item, "rank", None) for item in context.evidence],
            },
        )
        return context

    def generate(answer_input):
        record_routing({"processing_path": "generation", "generation_attempted": True})
        return answer(answer_input)

    generation = _stage(render, "render_documents") | _stage(
        generate, "answer_documents"
    )
    if retrieve is None:
        populated = generation
    else:
        populated = RunnablePassthrough.assign(
            context=_stage(retrieve_context, "retrieve")
        ) | RunnableBranch(
            (
                lambda state: (
                    not state["context"].evidence and not allow_empty_retrieval
                ),
                _notice(EMPTY_RETRIEVAL, "empty_retrieval"),
            ),
            generation,
        )
    return (
        RunnablePassthrough.assign(snapshot=_stage(snapshot, "read_snapshot"))
        | RunnableBranch(
            (
                lambda state: (
                    not state["snapshot"].documents and not allow_empty_retrieval
                ),
                _notice(EMPTY_DOCUMENTS, "empty_documents"),
            ),
            populated,
        )
    ).with_config(
        **named_trace_config(run_name="answer_flow", stage="answer_flow", role="chain")
    )


def build_full_flow(read_documents, answer_input):
    from app.answering.input import AnswerInput

    return _document_flow(
        read_documents,
        lambda state: AnswerInput.from_snapshot(
            state["question"],
            state["snapshot"],
            classification_context=state.get("classification_context"),
        ),
        answer_input,
    )


def build_rag_flow(
    read_documents, retrieve, answer_input, *, allow_empty_retrieval=False
):
    from app.answering.input import AnswerInput

    return _document_flow(
        read_documents,
        lambda state: AnswerInput.from_retrieved(
            state["question"],
            state["context"],
            classification_context=state.get("classification_context"),
        ),
        answer_input,
        retrieve,
        allow_empty_retrieval=allow_empty_retrieval,
    )


def build_legacy_flow(
    read_documents: Callable,
    answer: Callable,
    retrieve=None,
    *,
    allow_empty_retrieval=False,
):
    """Compatibility for direct service callers injecting the old answer callable."""

    def invoke(state):
        context = state["context"] if retrieve is not None else state["snapshot"]
        advisory = state.get("classification_context")
        if advisory is None:
            return answer(state["question"], context)
        return answer(state["question"], context, classification_context=advisory)

    return _document_flow(
        read_documents,
        lambda state: state,
        invoke,
        retrieve,
        allow_empty_retrieval=allow_empty_retrieval,
    )
