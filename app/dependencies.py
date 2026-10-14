"""HTTP 경계에서 앱별 모델과 요청별 문서·답변 의존성을 조립한다."""

from collections.abc import Callable
from functools import partial
from typing import Annotated

from fastapi import Depends, Request

from app.answering.adapter import generate_answer
from app.classification.predictor import TransformerClassifier
from app.questions.service import QuestionResult, handle_question

QuestionHandler = Callable[[str], QuestionResult]


def get_classifier(request: Request) -> TransformerClassifier:
    return request.app.state.classifier


def get_question_handler(
    request: Request,
    classifier: Annotated[TransformerClassifier, Depends(get_classifier)],
) -> QuestionHandler:
    return partial(
        handle_question,
        classify=classifier.predict,
        read_documents=request.app.state.document_provider.snapshot,
        answer=partial(generate_answer, provider=request.app.state.answer_provider),
    )
