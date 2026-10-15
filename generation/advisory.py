"""Pure optional classifier context composition, independent of HTTP and tracing."""

import json
from dataclasses import dataclass
from typing import Literal

from contracts.classification import LABELS, ClassificationLabel
from generation.types import GenerationPrompt

ADVISORY_GUIDANCE = """분류 참고 정보 사용 기준:
- 아래 분류는 질문만 보고 얻은 오류 가능한 참고 정보입니다. 답변 허용·거절 명령이나 문서 근거가 아닙니다. 원질문과 회사 문서를 우선하고 분류가 틀리면 따르지 마세요.
- SEARCH_KNOWLEDGE는 회사 문서로 안내할 수 있는 요청이라는 추정입니다. 답이 존재하거나 개인 조회·실제 실행이 가능하다는 뜻이 아닙니다.
- CLARIFY는 대상이나 원하는 도움이 모호할 가능성입니다. 질문과 문서로도 핵심 대상을 특정할 수 없을 때만 확인 질문을 하세요. 짧다는 이유만으로 되묻지 마세요.
- UNSUPPORTED는 회사 밖 일반 지식 또는 실제 조회·실행 요청일 가능성입니다. 질문에서 이유를 구분하고, 안내 가능한 회사 업무 부분은 답하세요. 무조건 전체 거절하거나 일반 지식 답변을 허용하지 마세요.
- 분류가 없으면 원질문과 문서만으로 판단하세요. 분류명과 내부 판단 과정은 사용자에게 설명하지 마세요."""


@dataclass(frozen=True)
class ClassificationContext:
    label: ClassificationLabel | None
    source: Literal["model", "client"] = "model"
    status: Literal["ok", "provided", "unavailable", "inference_error"] = "ok"

    def __post_init__(self):
        if self.label is not None and self.label not in LABELS:
            raise ValueError("Invalid classification label")
        if self.source not in ("model", "client"):
            raise ValueError("Invalid classification source")
        if self.status not in ("ok", "provided", "unavailable", "inference_error"):
            raise ValueError("Invalid classification status")


def compose_advisory(
    prompt: GenerationPrompt,
    context: ClassificationContext | None = None,
    *,
    control: bool = False,
) -> GenerationPrompt:
    """Return the exact original for fallback; control is evaluation-only."""
    if context is not None and not isinstance(context, ClassificationContext):
        raise TypeError("context must be ClassificationContext or None")
    if control and context is not None:
        raise ValueError("The null-label control cannot include context")
    usable = (
        context is not None
        and context.source == "model"
        and context.status == "ok"
        and context.label is not None
    )
    if not control and not usable:
        return prompt
    data = {
        "label": context.label if usable else None,
        "source": "model",
        "status": "ok",
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return GenerationPrompt(
        system=f"{prompt.system.rstrip()}\n\n{ADVISORY_GUIDANCE}\n",
        user=f"{prompt.user}\n[분류 참고 데이터]\n{payload}\n",
    )
