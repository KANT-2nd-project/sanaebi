from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class GenerationProvider(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"


class GenerationOutputMode(StrEnum):
    PROMPT_JSON = "prompt_json"
    STRICT_JSON_SCHEMA = "strict_json_schema"


@dataclass(frozen=True)
class GenerationConfig:
    provider: GenerationProvider
    model_name: str
    timeout_seconds: float
    context_window: int | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    temperature: float | None = None
    output_mode: GenerationOutputMode = GenerationOutputMode.PROMPT_JSON

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("모델 이름은 비어 있을 수 없습니다.")

        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("모델 timeout 시간은 유한한 양수여야 합니다.")

        if not isinstance(self.provider, GenerationProvider):
            raise TypeError("provider는 GenerationProvider 값이어야 합니다.")

        if not isinstance(self.output_mode, GenerationOutputMode):
            raise TypeError("output_mode는 GenerationOutputMode 값이어야 합니다.")

        if (
            self.output_mode is GenerationOutputMode.STRICT_JSON_SCHEMA
            and self.provider is not GenerationProvider.OPENAI
        ):
            raise ValueError(
                "strict_json_schema는 OpenAI provider에서만 사용할 수 있습니다."
            )

        valid_reasoning_efforts = {"none", "low", "medium", "high", "xhigh", "max"}
        if self.reasoning_effort is not None:
            if not isinstance(self.reasoning_effort, str):
                raise TypeError("reasoning_effort는 문자열 또는 None이어야 합니다.")
            if self.reasoning_effort not in valid_reasoning_efforts:
                raise ValueError(
                    "reasoning_effort는 none, low, medium, high, xhigh, max 중 하나여야 합니다."
                )
            if self.provider is GenerationProvider.OLLAMA:
                raise ValueError(
                    "reasoning_effort는 OpenAI provider에서만 사용할 수 있습니다."
                )

        if self.temperature is not None:
            if isinstance(self.temperature, bool) or not isinstance(
                self.temperature, (int, float)
            ):
                raise TypeError("temperature는 유한한 숫자 또는 None이어야 합니다.")
            if not isfinite(self.temperature) or not 0 <= self.temperature <= 2:
                raise ValueError(
                    "temperature는 0 이상 2 이하의 유한한 숫자여야 합니다."
                )
            if self.reasoning_effort not in (None, "none"):
                raise ValueError(
                    "reasoning_effort를 명시한 경우 none이 아니면 temperature를 함께 지정할 수 없습니다."
                )

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


def config_from_dict(data: dict[str, object]) -> GenerationConfig:
    provider_value = data.get("provider")
    model_name = data.get("model_name")
    timeout_seconds = data.get("timeout_seconds")

    if not isinstance(provider_value, str):
        raise TypeError("provider는 문자열이어야 합니다.")

    if not isinstance(model_name, str):
        raise TypeError("model_name은 문자열이어야 합니다.")

    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise TypeError("timeout_seconds는 숫자여야 합니다.")

    return GenerationConfig(
        provider=GenerationProvider(provider_value),
        model_name=model_name,
        timeout_seconds=timeout_seconds,
        context_window=data.get("context_window"),
        max_output_tokens=data.get("max_output_tokens"),
        reasoning_effort=data.get("reasoning_effort"),
        temperature=data.get("temperature"),
        output_mode=GenerationOutputMode(data.get("output_mode", "prompt_json")),
    )
