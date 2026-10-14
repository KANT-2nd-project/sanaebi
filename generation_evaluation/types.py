from dataclasses import dataclass
from math import isfinite

from generation.config import GenerationConfig
from generation.types import GenerationResult


@dataclass(frozen=True)
class GenerationRun:
    case_id: str
    config: GenerationConfig
    result: GenerationResult | None
    elapsed_seconds: float
    error_type: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("걸린 시간은 유한한 0 이상의 값이어야 합니다.")

        if self.result is None and self.error_type is None:
            raise ValueError("result와 error_type이 둘 다 없습니다.")

        if self.result is not None and self.error_type is not None:
            raise ValueError("result와 error_type이 둘 다 있습니다.")

        if self.error_type is not None and not self.error_type.strip():
            raise ValueError("error_type은 빈 문자열이나 공백일 수 없습니다.")


@dataclass(frozen=True)
class GenerationSummary:
    config: GenerationConfig
    counts: dict[str, int]
    completion_rate: float | None
    mean_attempt_seconds: float | None
    mean_completed_seconds: float | None
