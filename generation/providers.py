from collections.abc import Callable

from httpx import TimeoutException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from openai import APITimeoutError

from generation.config import GenerationConfig, GenerationOutputMode
from generation.output_schema import OPENAI_ANSWER_RESPONSE_FORMAT
from generation.types import GenerationPrompt, ModelResponse


def to_messages(prompt: GenerationPrompt) -> list[BaseMessage]:
    system_message = SystemMessage(content=prompt.system)
    human_message = HumanMessage(content=prompt.user)

    return [system_message, human_message]


def extract_text(content: object) -> str:
    if not isinstance(content, str):
        raise TypeError("모델 응답 내용은 문자열이여야 합니다.")

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

    raw_refusal = response.additional_kwargs.get("refusal")
    if raw_refusal is not None and not isinstance(raw_refusal, str):
        raise TypeError("모델 거절 정보는 문자열이어야 합니다.")
    refusal = raw_refusal if raw_refusal else None

    usage = response.usage_metadata or {}
    metadata = response.response_metadata
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


def build_ollama_model(config: GenerationConfig) -> ChatOllama:
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

    return ChatOllama(**options)


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
