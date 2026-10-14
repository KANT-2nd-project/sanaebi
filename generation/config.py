from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class GenerationProvider(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"


@dataclass(frozen=True)
class GenerationConfig:
    provider: GenerationProvider
    model_name: str
    timeout_seconds: float
    context_window: int | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("모델 이름은 비어 있을 수 없습니다.")

        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("모델 timeout 시간은 유한한 양수여야 합니다.")

        if not isinstance(self.provider, GenerationProvider):
            raise TypeError("provider는 GenerationProvider 값이어야 합니다.")

        for name, value in (
            ("context_window", self.context_window),
            ("max_output_tokens", self.max_output_tokens),
        ):
            if value is None:
                continue

            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name}는 정수여야 합니다.")

            if value <= 0:
                raise ValueError(f"{name}는 양수여야 합니다.")

        if (
            self.context_window is not None
            and self.max_output_tokens is not None
            and self.max_output_tokens >= self.context_window
        ):
            raise ValueError("출력 토큰 한도는 문맥 크기보다 작아야 합니다.")
