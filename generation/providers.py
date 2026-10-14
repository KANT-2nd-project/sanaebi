from collections.abc import Callable

from httpx import TimeoutException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from openai import APITimeoutError

from generation.config import GenerationConfig
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

    usage = response.usage_metadata or {}
    metadata = response.response_metadata

    return ModelResponse(
        raw_text=extract_text(response.content),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        finish_reason=(metadata.get("done_reason") or metadata.get("finish_reason")),
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

    return ChatOllama(
        model=config.model_name,
        num_ctx=config.context_window,
        num_predict=config.max_output_tokens,
        client_kwargs={"timeout": config.timeout_seconds},
    )


def build_ollama_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    ollama_model = build_ollama_model(config)
    return make_model_call(ollama_model.invoke)


def build_openai_model(config: GenerationConfig) -> ChatOpenAI:
    if config.provider != "openai":
        raise ValueError("provider가 openai가 아닙니다.")

    if config.context_window is not None or config.max_output_tokens is not None:
        raise ValueError("OpenAI의 문맥, 출력 한도 설정은 아직 연결하지 않았습니다.")

    return ChatOpenAI(
        model=config.model_name, timeout=config.timeout_seconds, max_retries=0
    )


def build_openai_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    openai_model = build_openai_model(config)
    return make_model_call(openai_model.invoke)


def build_model_call(
    config: GenerationConfig,
) -> Callable[[GenerationPrompt], ModelResponse]:
    if config.provider == "ollama":
        return build_ollama_call(config)
    elif config.provider == "openai":
        return build_openai_call(config)

    raise ValueError("provider는 (ollama, openai) 중 하나입니다.")
