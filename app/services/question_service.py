"""분기 정책 서비스와 별도 LangChain 전달 서비스. 두 호출 계약을 구분한다."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ClassificationLabel = Literal["SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"]
Classifier = Callable[[str], ClassificationLabel]
DocumentReader = Callable[[], list[str]]
Answerer = Callable[[str, list[str]], str]


@dataclass(frozen=True)
class QuestionResult:
    text: str


def handle_question(
    question: str,
    *,
    classify: Classifier,
    read_documents: DocumentReader,
    answer: Answerer,
) -> QuestionResult:
    label = classify(question)

    if label == "CLARIFY":
        return QuestionResult(
            text="어떤 대상에 대해 어떤 도움이 필요한지 조금 더 알려주세요."
        )
    elif label == "UNSUPPORTED":
        return QuestionResult(text="지원 범위 밖의 요청 혹은 질문입니다.")
    else:
        if label != "SEARCH_KNOWLEDGE":
            raise ValueError("분류기가 허용되지 않은 라벨을 반환했습니다.")

        documents = read_documents()
        if not documents:
            return QuestionResult(
                text="현재 확인 가능한 회사 문서가 없어 답변하기 어렵습니다."
            )
    answer_text = answer(question, documents)

    return QuestionResult(text=answer_text)


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
