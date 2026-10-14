from dataclasses import dataclass
from enum import StrEnum


class GenerationStatus(StrEnum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    EMPTY_ANSWER = "empty_answer"
    TRUNCATED = "truncated"


@dataclass(frozen=True)
class GenerationResult:
    status: GenerationStatus
    raw_text: str | None
    answer: str | None

    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GenerationStatus):
            raise TypeError("status는 GenerationStatus여야 합니다.")

        if self.raw_text is not None and not isinstance(self.raw_text, str):
            raise TypeError("raw_text는 문자열 또는 None이어야 합니다.")

        if self.answer is not None and not isinstance(self.answer, str):
            raise TypeError("answer는 문자열 또는 None이어야 합니다.")

        if self.status is GenerationStatus.TIMEOUT:
            if self.raw_text is not None or self.answer is not None:
                raise ValueError(
                    "timeout 결과의 raw_text와 answer는 None이어야 합니다."
                )
            return

        if self.raw_text is None:
            raise ValueError("timeout 이외의 결과에는 raw_text가 필요합니다.")

        if self.status is GenerationStatus.COMPLETED:
            if self.answer is None or not self.answer.strip():
                raise ValueError(
                    "completed 결과에는 비어 있지 않은 answer가 필요합니다."
                )
        elif self.answer is not None:
            raise ValueError("실패 결과의 answer는 None이어야 합니다.")


@dataclass(frozen=True)
class GenerationPrompt:
    system: str
    user: str


@dataclass(frozen=True)
class ModelResponse:
    raw_text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
