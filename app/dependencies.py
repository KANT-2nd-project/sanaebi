from collections.abc import Callable
from functools import partial

from app.services.question_service import QuestionResult

QuestionHandler = Callable[[str], QuestionResult]


def get_question_handler() -> QuestionHandler:
    raise NotImplementedError("분류기·문서 reader·답변기를 아직 연결하지 않았습니다.")

    return partial(
        handle_question,
        classify=classifier,
        read_documents=document_reader,
        answer=answerer,
    )
