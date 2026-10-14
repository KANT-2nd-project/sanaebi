from collections.abc import Callable

from httpx import TimeoutException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from openai import APITimeoutError

from generation.config import GenerationConfig
from generation.types import GenerationPrompt


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
) -> str:
    messages = to_messages(prompt)
    try:
        response = invoke(messages)
    except (TimeoutException, APITimeoutError) as exc:
        raise TimeoutError("모델 응답 대기 시간이 초과되었습니다.") from exc
    return extract_text(response.content)


def make_model_call(
    invoke: Callable[[list[BaseMessage]], AIMessage],
) -> Callable[[GenerationPrompt], str]:
    def model_call(prompt: GenerationPrompt) -> str:
        return invoke_model(prompt=prompt, invoke=invoke)

    return model_call


def build_ollama_model(config: GenerationConfig) -> ChatOllama:
    if config.provider != "ollama":
        raise ValueError("provider가 ollama가 아닙니다.")

    return ChatOllama(
        model=config.model_name, client_kwargs={"timeout": config.timeout_seconds}
    )


def build_ollama_call(config: GenerationConfig) -> Callable[[GenerationPrompt], str]:
    ollama_model = build_ollama_model(config)
    return make_model_call(ollama_model.invoke)


def build_openai_model(config: GenerationConfig) -> ChatOpenAI:
    if config.provider != "openai":
        raise ValueError("provider가 openai가 아닙니다.")

    return ChatOpenAI(
        model=config.model_name, timeout=config.timeout_seconds, max_retries=0
    )


def build_openai_call(config: GenerationConfig) -> Callable[[GenerationPrompt], str]:
    openai_model = build_openai_model(config)
    return make_model_call(openai_model.invoke)


def build_model_call(config: GenerationConfig) -> Callable[[GenerationPrompt], str]:
    if config.provider == "ollama":
        return build_ollama_call(config)
    elif config.provider == "openai":
        return build_openai_call(config)

    raise ValueError("provider는 (ollama, openai) 중 하나입니다.")
