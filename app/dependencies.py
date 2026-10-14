from collections.abc import Callable
from functools import partial

from app.koelectra_classifier import classify_question
from app.services.document_context import DocumentContextProvider
from app.services.question_service import QuestionResult, handle_question

QuestionHandler = Callable[[str], QuestionResult]


def read_runtime_documents():
    return [
        f"제목: {d.title.strip()}\n내용: {d.body.strip()}"
        for d in DocumentContextProvider().snapshot().documents
    ]


def answer_not_configured(question: str, documents: list[str]) -> str:
    raise NotImplementedError("답변 생성기를 아직 연결안함")


def get_question_handler() -> QuestionHandler:
    document_reader = read_runtime_documents

    return partial(
        handle_question,
        classify=classify_question,
        read_documents=document_reader,
        answer=answer_not_configured,
    )
