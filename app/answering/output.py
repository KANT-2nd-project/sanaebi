# LLM 응답을 답변으로 쓸 수 없을 때 사용자에게 보여줄 안내입니다.
LLM_RESPONSE_ERROR = "답변을 생성하지 못했습니다. 잠시 후 다시 시도해주세요."


class LLMResponseError(Exception):
    """LLM 응답에서 답변 text를 꺼낼 수 없을 때 발생합니다."""
