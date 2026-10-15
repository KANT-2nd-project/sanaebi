"""HTTP 경계에서 앱별 모델과 요청별 문서·답변 의존성을 조립한다."""

from collections.abc import Callable
from functools import partial
from typing import Annotated

from fastapi import Depends, Request

from app.classification.predictor import TransformerClassifier
from app.questions.service import (
    QuestionResult,
    handle_classified_question,
    handle_question,
)
from contracts.classification import ClassificationLabel

QuestionHandler = Callable[[str], QuestionResult]
AssistantHandler = Callable[[str, ClassificationLabel], QuestionResult]


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
        answer=(
            request.app.state.answerer.answer_retrieved
            if request.app.state.retriever is not None
            else request.app.state.answerer.answer
        ),
        retrieve=(
            request.app.state.retriever.retrieve
            if request.app.state.retriever is not None
            else None
        ),
        routing_mode=request.app.state.routing_mode,
    )


def get_assistant_handler(request: Request) -> AssistantHandler:
    return partial(
        handle_classified_question,
        read_documents=request.app.state.document_provider.snapshot,
        answer=(
            request.app.state.answerer.answer_retrieved
            if request.app.state.retriever is not None
            else request.app.state.answerer.answer
        ),
        retrieve=(
            request.app.state.retriever.retrieve
            if request.app.state.retriever is not None
            else None
        ),
        routing_mode=request.app.state.routing_mode,
    )
