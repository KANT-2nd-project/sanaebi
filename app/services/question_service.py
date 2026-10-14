"""질문을 분류한 뒤 LangChain의 고정 입력 형식으로 전달한다."""

from collections.abc import Callable


class ClassificationModelUnavailable(Exception):
    """분류 모델 파일을 찾을 수 없음."""


def answer_question(
    question: str,
    classify: Callable[[str], str],
    generate: Callable[[dict, str], dict],
) -> dict:
    question = question.strip()

    # 1. 저장된 분류 모델로 카테고리 결정
    try:
        category = classify(question)
    except FileNotFoundError as error:
        raise ClassificationModelUnavailable from error

    # 2. 질문을 LangChain 고정 입력 형식에 담기
    response = {"ok": True, "text": question, "reason": ""}

    # 3. 질문과 카테고리를 전달하고 LangChain 결과를 그대로 반환
    return generate(response, category)
