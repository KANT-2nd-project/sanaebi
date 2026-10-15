from collections.abc import Callable
from inspect import isawaitable

from httpx import TimeoutException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import APITimeoutError

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
    system_message = SystemMessage(content=prompt.system)
    human_message = HumanMessage(content=prompt.user)

    return [system_message, human_message]


def extract_text(content: object) -> str:
    if not isinstance(content, str):
        raise GenerationProviderResponseError("모델 응답 내용은 문자열이어야 합니다.")

    return content


def invoke_model(
    prompt: GenerationPrompt,
    invoke: Callable[[list[BaseMessage]], AIMessage],
) -> ModelResponse:
    messages = to_messages(prompt)
    try:
        response = invoke(messages)
    except (TimeoutException, APITimeoutError) as exc:
        raise TimeoutError("모델 응답 대기 시간이 초과되었습니다.") from exc

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


def make_model_call(
    invoke: Callable[[list[BaseMessage]], AIMessage],
) -> Callable[[GenerationPrompt], ModelResponse]:
    def model_call(prompt: GenerationPrompt) -> ModelResponse:
        return invoke_model(prompt=prompt, invoke=invoke)

    return model_call


def build_ollama_model(config: GenerationConfig):
    if config.provider != "ollama":
        raise ValueError("provider가 ollama가 아닙니다.")

    options = {
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
    ollama_model = build_ollama_model(config)
    return make_model_call(ollama_model.invoke)


def build_openai_model(config: GenerationConfig) -> ChatOpenAI:
    if config.provider != "openai":
        raise ValueError("provider가 openai가 아닙니다.")

    if config.context_window is not None:
        raise ValueError("OpenAI의 context_window 설정은 아직 연결하지 않았습니다.")

    options = {
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
    if config.output_mode is GenerationOutputMode.STRICT_JSON_SCHEMA:
        options["model_kwargs"] = {
            "response_format": OPENAI_ANSWER_RESPONSE_FORMAT,
        }
        options["use_responses_api"] = False

    return ChatOpenAI(**options)


def build_openai_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    openai_model = build_openai_model(config)
    invoke = lambda messages: invoke_openai_message(config, openai_model, messages)
    return make_model_call(invoke)


def invoke_openai_message(
    config: GenerationConfig,
    model: ChatOpenAI,
    messages: list[BaseMessage],
) -> AIMessage:
    if config.output_mode is GenerationOutputMode.STRICT_JSON_SCHEMA:
        return _invoke_strict_chat_completions(model, messages)
    return model.invoke(messages)


def _invoke_strict_chat_completions(
    model: ChatOpenAI, messages: list[BaseMessage]
) -> AIMessage:
    """Call Chat Completions without SDK parse() masking length-truncated output."""
    payload = model._get_request_payload(messages)
    raw_response = model.root_client.chat.completions.with_raw_response.create(
        **payload
    )
    completion = raw_response.parse()
    chat_result = model._create_chat_result(completion)
    generation = chat_result.generations[0]
    message = generation.message
    if not isinstance(message, AIMessage):
        raise TypeError("OpenAI 응답은 AIMessage여야 합니다.")
    message.response_metadata = {
        **(chat_result.llm_output or {}),
        **(generation.generation_info or {}),
        **message.response_metadata,
    }
    return message


def build_model_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    if config.provider == "ollama":
        return build_ollama_call(config)
    elif config.provider == "openai":
        return build_openai_call(config)

    raise ValueError("provider는 (ollama, openai) 중 하나입니다.")


class ManagedGenerationClient:
    """Callable OpenAI generation client with an explicit async close path."""

    def __init__(self, config: GenerationConfig) -> None:
        if config.provider is not GenerationProvider.OPENAI:
            raise ValueError("서버 생성 클라이언트는 OpenAI provider만 지원합니다.")

        self._model = build_openai_model(config)
        self._invoke = lambda messages: invoke_openai_message(
            config, self._model, messages
        )
        self._closed = False

    def __call__(self, prompt: GenerationPrompt) -> ModelResponse:
        if self._closed:
            raise RuntimeError("이미 종료된 생성 클라이언트입니다.")
        return invoke_model(prompt, self._invoke)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True

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
