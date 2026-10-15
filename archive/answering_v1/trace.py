"""Trace stage names for the archived ``sanaebi_assistant.create_chain`` flow."""

from app.diagnostics.trace import (
    MODEL_STAGE,
    ROOT_STAGE,
    StageResolver,
    TraceCallback,
    to_record,
)

_NAMED_STAGES = {
    "prepare_input": "입력 정리",
    "RunnableBranch": "경로 선택",
    "format_answer": "출력 정리",
    "format_failed_input": "입력 오류 응답",
}


def stage_of(name: str | None, tags, parent_stage: str | None) -> tuple[str, bool]:
    """Name the archived chain's nodes and branch wrappers for historical tests."""
    name = name or ""
    if parent_stage is None:
        return ROOT_STAGE, False
    if name in _NAMED_STAGES:
        return _NAMED_STAGES[name], False
    if name.endswith("PromptTemplate"):
        return "프롬프트 만들기", False
    if name.startswith("RunnableAssign"):
        return "구조화 답변", True
    if parent_stage == "경로 선택":
        if any(str(tag).startswith("condition:") for tag in tags or ()):
            return "경로 조건", True
        return "답변 체인", True
    if parent_stage == "답변 체인" and name == "RunnableLambda":
        return "문서 문맥 추가", False
    if name.startswith(("RunnableSequence", "RunnableParallel")):
        return parent_stage, True
    if parent_stage == "구조화 답변":
        return "출력 해석", False
    return name or "알 수 없음", False


class LegacyTraceCallback(TraceCallback):
    """Use historical stages and opt into its clipped raw chain outputs.

    This callback is explicit to the archived answerer; the active server's
    ``TraceCallback`` continues to retain only allowlisted chain metadata.
    """

    def __init__(self):
        super().__init__(stage_resolver=stage_of)

    def _chain_output_record(self, outputs):
        """Preserve historical answer stages without widening active tracing."""
        return to_record(outputs)


__all__ = [
    "MODEL_STAGE",
    "ROOT_STAGE",
    "LegacyTraceCallback",
    "StageResolver",
    "stage_of",
]
