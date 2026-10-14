from collections.abc import Callable
from functools import partial

from app.company_knowledge import get_documents_path
from app.document_store import read_documents
from app.koelectra_classifier import classify_question
from app.services.question_service import QuestionResult, handle_question

QuestionHandler = Callable[[str], QuestionResult]

DOCUMENTS_PATH = get_documents_path()


def answer_not_configured(question: str, documents: list[str]) -> str:
    raise NotImplementedError("답변 생성기를 아직 연결안함")


def get_question_handler() -> QuestionHandler:
    document_reader = partial(read_documents, DOCUMENTS_PATH)

    return partial(
        handle_question,
        classify=classify_question,
        read_documents=document_reader,
        answer=answer_not_configured,
    )
