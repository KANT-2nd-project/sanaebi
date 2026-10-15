"""HTTP 경계에서 앱별 모델과 요청별 문서·답변 의존성을 조립한다."""

from collections.abc import Callable
from functools import partial
from typing import Annotated

from fastapi import Depends, Request

from app.classification.predictor import TransformerClassifier
from app.questions.pipeline import build_full_flow, build_rag_flow
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
        **_document_answer_dependencies(request),
    )


def get_assistant_handler(request: Request) -> AssistantHandler:
    return partial(
        handle_classified_question,
        **_document_answer_dependencies(request),
    )


def _document_answer_dependencies(request: Request) -> dict:
    state = request.app.state
    retriever = state.retriever
    flow = (
        build_full_flow(state.document_provider.snapshot, state.answerer.answer_input)
        if retriever is None
        else build_rag_flow(
            state.document_provider.snapshot,
            retriever.retrieve,
            state.answerer.answer_input,
            allow_empty_retrieval=state.answerer.supports_empty_retrieval,
        )
    )
    return {"document_flow": flow, "routing_mode": state.routing_mode}
