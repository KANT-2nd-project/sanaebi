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

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("모델 이름은 비어 있을 수 없습니다.")

        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("모델 timeout 시간은 유한한 양수여야 합니다.")

        if not isinstance(self.provider, GenerationProvider):
            raise TypeError("provider는 GenerationProvider 값이어야 합니다.")
