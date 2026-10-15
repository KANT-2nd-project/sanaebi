from collections.abc import Callable
from functools import partial
from inspect import isawaitable
from typing import Any

from httpx import TimeoutException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from openai import APITimeoutError, OpenAI

from generation.config import (
    GenerationConfig,
    GenerationOutputMode,
    GenerationProvider,
)
from generation.optional_providers import load_ollama_chat_model
from generation.output_schema import OPENAI_ANSWER_RESPONSE_FORMAT
from generation.types import GenerationPrompt, ModelResponse


class GenerationProviderResponseError(TypeError):
    """A provider returned a response that violates the generation contract."""


def to_messages(prompt: GenerationPrompt) -> list[BaseMessage]:
    return [SystemMessage(content=prompt.system), HumanMessage(content=prompt.user)]


def extract_text(content: object) -> str:
    if not isinstance(content, str):
        raise GenerationProviderResponseError("모델 응답 내용은 문자열이어야 합니다.")
    return content


def model_response_from_ai_message(response: object) -> ModelResponse:
    """Normalize provider metadata without performing model I/O."""
    if not isinstance(response, AIMessage):
        raise GenerationProviderResponseError("모델 응답은 AIMessage여야 합니다.")

    additional_kwargs = response.additional_kwargs
    if not isinstance(additional_kwargs, dict):
        raise GenerationProviderResponseError(
            "모델 응답 메타데이터가 올바르지 않습니다."
        )

    raw_refusal = additional_kwargs.get("refusal")
    if raw_refusal is not None and not isinstance(raw_refusal, str):
        raise GenerationProviderResponseError("모델 거절 정보는 문자열이어야 합니다.")
    refusal = raw_refusal if raw_refusal else None

    usage = response.usage_metadata
    metadata = response.response_metadata
    if usage is None:
        usage = {}
    if not isinstance(usage, dict) or not isinstance(metadata, dict):
        raise GenerationProviderResponseError(
            "모델 응답 메타데이터가 올바르지 않습니다."
        )
    if isinstance(response.content, str):
        raw_text = response.content
    elif refusal is not None:
        raw_text = None
    else:
        raw_text = extract_text(response.content)

    return ModelResponse(
        raw_text=raw_text,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        finish_reason=(metadata.get("done_reason") or metadata.get("finish_reason")),
        refusal=refusal,
    )


def invoke_model(
    prompt: GenerationPrompt,
    invoke: Callable[[list[BaseMessage]], AIMessage],
) -> ModelResponse:
    try:
        response = invoke(to_messages(prompt))
    except (TimeoutException, APITimeoutError) as exc:
        raise TimeoutError("모델 응답 대기 시간이 초과되었습니다.") from exc
    return model_response_from_ai_message(response)


class ModelCall:
    """Callable compatibility adapter for the stable GenerationPrompt contract."""

    def __init__(self, invoke: Callable[[list[BaseMessage]], AIMessage]):
        self.invoke = invoke

    def __call__(self, prompt: GenerationPrompt) -> ModelResponse:
        return invoke_model(prompt=prompt, invoke=self.invoke)


def make_model_call(
    invoke: Callable[[list[BaseMessage]], AIMessage],
) -> ModelCall:
    return ModelCall(invoke)


def build_ollama_model(config: GenerationConfig):
    if config.provider != "ollama":
        raise ValueError("provider가 ollama가 아닙니다.")

    options: dict[str, Any] = {
        "model": config.model_name,
        "num_ctx": config.context_window,
        "num_predict": config.max_output_tokens,
        "client_kwargs": {"timeout": config.timeout_seconds},
    }
    if config.temperature is not None:
        options["temperature"] = config.temperature

    return load_ollama_chat_model()(**options)


def build_ollama_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    return make_model_call(build_ollama_model(config).invoke)


class StrictOpenAIChatModel:
    """Public OpenAI SDK adapter that preserves raw truncation responses."""

    def __init__(self, config: GenerationConfig, client: OpenAI | None = None):
        if config.provider is not GenerationProvider.OPENAI:
            raise ValueError("provider가 openai가 아닙니다.")
        if config.output_mode is not GenerationOutputMode.STRICT_JSON_SCHEMA:
            raise ValueError("strict JSON schema 설정이 필요합니다.")
        self.config = config
        self.client = client or OpenAI(
            timeout=config.timeout_seconds,
            max_retries=0,
        )

    def build_payload(self, messages: list[BaseMessage]) -> dict[str, object]:
        sdk_messages: list[dict[str, str]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                role = "system"
            elif isinstance(message, HumanMessage):
                role = "user"
            else:
                raise GenerationProviderResponseError(
                    "strict 생성 입력은 system/user 메시지만 허용합니다."
                )
            sdk_messages.append(
                {"role": role, "content": extract_text(message.content)}
            )

        payload: dict[str, object] = {
            "model": self.config.model_name,
            "messages": sdk_messages,
            "response_format": OPENAI_ANSWER_RESPONSE_FORMAT,
        }
        if self.config.max_output_tokens is not None:
            payload["max_completion_tokens"] = self.config.max_output_tokens
        if self.config.reasoning_effort is not None:
            payload["reasoning_effort"] = self.config.reasoning_effort
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        return payload

    def invoke(self, messages: list[BaseMessage] | PromptValue) -> AIMessage:
        if isinstance(messages, PromptValue):
            messages = messages.to_messages()
        completion = self.client.chat.completions.create(**self.build_payload(messages))
        if not completion.choices:
            raise GenerationProviderResponseError("OpenAI 응답에 선택지가 없습니다.")

        choice = completion.choices[0]
        message = choice.message
        refusal = message.refusal
        content = message.content
        if content is None and refusal:
            content = []
        usage_metadata = None
        if completion.usage is not None:
            usage_metadata = {
                "input_tokens": completion.usage.prompt_tokens,
                "output_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
        return AIMessage(
            content=content if content is not None else [],
            additional_kwargs={"refusal": refusal} if refusal else {},
            usage_metadata=usage_metadata,
            response_metadata={
                "finish_reason": choice.finish_reason,
                "model_name": completion.model,
                "id": completion.id,
            },
        )

    def close(self) -> None:
        self.client.close()


def build_openai_model(config: GenerationConfig) -> ChatOpenAI | StrictOpenAIChatModel:
    if config.provider != "openai":
        raise ValueError("provider가 openai가 아닙니다.")

    if config.context_window is not None:
        raise ValueError("OpenAI의 context_window 설정은 아직 연결하지 않았습니다.")

    if config.output_mode is GenerationOutputMode.STRICT_JSON_SCHEMA:
        return StrictOpenAIChatModel(config)

    options: dict[str, Any] = {
        "model": config.model_name,
        "timeout": config.timeout_seconds,
        "max_retries": 0,
    }
    if config.max_output_tokens is not None:
        options["max_completion_tokens"] = config.max_output_tokens
    if config.reasoning_effort is not None:
        options["reasoning_effort"] = config.reasoning_effort
    if config.temperature is not None:
        options["temperature"] = config.temperature

    return ChatOpenAI(**options)


def invoke_openai_message(
    config: GenerationConfig,
    model: ChatOpenAI | StrictOpenAIChatModel,
    messages: list[BaseMessage],
) -> AIMessage:
    if config.output_mode is GenerationOutputMode.STRICT_JSON_SCHEMA:
        if not isinstance(model, StrictOpenAIChatModel):
            raise TypeError("strict JSON schema는 공개 SDK adapter가 필요합니다.")
    elif isinstance(model, StrictOpenAIChatModel):
        raise TypeError("prompt_json은 ChatOpenAI 모델이 필요합니다.")
    return model.invoke(messages)


def build_openai_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    model = build_openai_model(config)
    invoke = partial(invoke_openai_message, config, model)
    return make_model_call(invoke)


def build_model_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    if config.provider == "ollama":
        return build_ollama_call(config)
    if config.provider == "openai":
        return build_openai_call(config)
    raise ValueError("provider는 (ollama, openai) 중 하나입니다.")


class ManagedGenerationClient:
    """App-owned provider with a direct Runnable and explicit close path."""

    def __init__(self, config: GenerationConfig) -> None:
        if config.provider is not GenerationProvider.OPENAI:
            raise ValueError("서버 생성 클라이언트는 OpenAI provider만 지원합니다.")

        self._config = config
        self._model = build_openai_model(config)
        self._invoke = partial(invoke_openai_message, config, self._model)
        if config.output_mode is GenerationOutputMode.STRICT_JSON_SCHEMA:
            self.runnable = RunnableLambda(self._model.invoke)
        else:
            self.runnable = self._model
        self._closed = False

    def __call__(self, prompt: GenerationPrompt) -> ModelResponse:
        if self._closed:
            raise RuntimeError("이미 종료된 생성 클라이언트입니다.")
        return invoke_model(prompt, self._invoke)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._config.output_mode is GenerationOutputMode.STRICT_JSON_SCHEMA:
            self._model.close()
            return

        sync_close = getattr(self._model.root_client, "close", None)
        async_close = getattr(self._model.root_async_client, "close", None)
        try:
            if callable(sync_close):
                result = sync_close()
                if isawaitable(result):
                    await result
        finally:
            if callable(async_close):
                result = async_close()
                if isawaitable(result):
                    await result


def build_managed_model_call(config: GenerationConfig) -> ManagedGenerationClient:
    """Build the server-owned OpenAI client; Ollama remains CLI-only."""
    return ManagedGenerationClient(config)
