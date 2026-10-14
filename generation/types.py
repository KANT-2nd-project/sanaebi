from dataclasses import dataclass
from enum import StrEnum


class GenerationStatus(StrEnum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    EMPTY_ANSWER = "empty_answer"


@dataclass(frozen=True)
class GenerationResult:
    status: GenerationStatus
    raw_text: str | None
    answer: str | None


@dataclass(frozen=True)
class GenerationPrompt:
    system: str
    user: str
