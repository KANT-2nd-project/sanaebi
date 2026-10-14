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
