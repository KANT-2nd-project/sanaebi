import json
from collections.abc import Mapping

# LLM 응답을 답변으로 쓸 수 없을 때 사용자에게 보여줄 안내입니다.
LLM_RESPONSE_ERROR = "답변을 생성하지 못했습니다. 잠시 후 다시 시도해주세요."


class LLMResponseError(Exception):
    """LLM 응답에서 답변 text를 꺼낼 수 없을 때 발생합니다."""


# 작성일: 2026-10-14
# 작성자: yu
# 기능: LLM 응답(JSON 객체·문자열)에서 답변 text만 검증해 꺼냄
def extract_answer_text(result: Mapping | str) -> str:
    # 문자열로 받은 결과는 JSON 객체로 해석합니다.
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as error:
            raise LLMResponseError("LLM 응답이 올바른 JSON이 아닙니다.") from error
    if not isinstance(result, Mapping):
        raise LLMResponseError("LLM 응답이 JSON 객체가 아닙니다.")
    # 모델 호출 실패나 길이 제한으로 잘린 응답은 본문이 있어도 답변으로 쓰지 않습니다.
    if result.get("error"):
        raise LLMResponseError(f"LLM 호출 오류: {result['error']}")
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        raise LLMResponseError("LLM 응답에 text가 없습니다.")
    return text.strip()
