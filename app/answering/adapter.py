"""이미 확보한 문서 snapshot으로 선택한 LangChain 제공자만 호출한다."""

from collections.abc import Mapping

from app.answering.output import LLMResponseError, extract_answer_text
from app.documents.context import DocumentContextSnapshot


def execute(*args, **kwargs):
    from sanaebi_assistant import process_response

    return process_response(*args, **kwargs)


def generate_answer(
    question: str, snapshot: DocumentContextSnapshot, *, provider: str
) -> str:
    results = execute(
        {"ok": True, "text": question, "reason": ""},
        "SEARCH_KNOWLEDGE",
        provider=provider,
        document_snapshot=snapshot,
    )
    result = results.get(provider) if isinstance(results, Mapping) else None
    if not isinstance(result, Mapping) or not result.get("success"):
        raise LLMResponseError("LangChain 모델 호출에 실패했습니다.")
    output = result.get("output", {"text": result.get("answer")})
    text = extract_answer_text(output)
    if text.startswith("{"):
        text = extract_answer_text(text)
    return text


def generate_assistant_response(
    response: dict,
    category: str,
    *,
    provider: str | None = None,
    document_provider=None,
) -> dict:
    from app.documents.context import DocumentContextProvider
    from sanaebi_assistant import process_response

    snapshot = None
    if response.get("ok") and category == "SEARCH_KNOWLEDGE":
        snapshot = (document_provider or DocumentContextProvider()).snapshot()
    return process_response(
        response,
        classification_label=category,
        provider=provider,
        document_snapshot=snapshot,
    )
