"""Load optional provider integrations only when selected."""


def load_ollama_chat_model():
    """Return ChatOllama without hiding broken transitive dependencies."""
    try:
        from langchain_ollama import ChatOllama
    except ModuleNotFoundError as exc:
        if exc.name != "langchain_ollama":
            raise
        raise ImportError(
            "Ollama 사용에는 선택 의존성이 필요합니다: uv sync --locked --extra ollama"
        ) from exc
    return ChatOllama
