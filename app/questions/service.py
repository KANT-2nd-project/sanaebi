"""Classification policy around explicitly assembled document answer flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Literal, Protocol

from langchain_core.runnables import RunnableLambda

from app.classification.errors import (
    ClassificationInferenceError,
    ClassificationUnavailable,
)
from app.diagnostics.trace import (
    named_trace_config,
    record_classification,
    record_routing,
)
from app.documents.context import DocumentContextSnapshot
from app.questions.pipeline import build_legacy_flow
from contracts.classification import LABELS, ClassificationLabel
from generation.advisory import ClassificationContext

if TYPE_CHECKING:
    from app.retrieval.types import RetrievedContext

Retriever = Callable[[str, DocumentContextSnapshot], "RetrievedContext"]
Classifier = Callable[[str], ClassificationLabel]
DocumentReader = Callable[[], DocumentContextSnapshot]
RoutingMode = Literal["gate", "shadow", "advisory"]


class Answerer(Protocol):
    def __call__(
        self,
        question: str,
        context: DocumentContextSnapshot | RetrievedContext,
        *,
        classification_context: ClassificationContext | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class QuestionResult:
    text: str


@dataclass(frozen=True)
class ClassificationOutcome:
    label: ClassificationLabel | None
    status: str
    source: Literal["model", "client"]
    elapsed_seconds: float | None

    def record(self, routing_mode, processing_path=None):
        fields = {
            "routing_mode": routing_mode,
            "label_source": self.source,
            "classification_status": self.status,
            "classification_elapsed_seconds": self.elapsed_seconds,
            "generation_attempted": False,
        }
        if processing_path is not None:
            fields["processing_path"] = processing_path
        record_routing(fields)
        if self.label is not None:
            record_classification(self.label)


def handle_question(
    question: str,
    *,
    classify: Classifier,
    read_documents: DocumentReader | None = None,
    answer: Answerer | None = None,
    retrieve: Retriever | None = None,
    routing_mode: RoutingMode = "gate",
    document_flow=None,
    allow_empty_retrieval=False,
) -> QuestionResult:
    _validate_routing_mode(routing_mode)
    ClassificationOutcome(None, "running", "model", None).record(
        routing_mode, "classification"
    )
    started = perf_counter()
    classifier = RunnableLambda(classify).with_config(
        **named_trace_config(run_name="classify", stage="classification", role="chain")
    )
    try:
        label = classifier.invoke(question)
    except (ClassificationUnavailable, ClassificationInferenceError) as error:
        status = (
            "unavailable"
            if isinstance(error, ClassificationUnavailable)
            else "inference_error"
        )
        outcome = ClassificationOutcome(None, status, "model", perf_counter() - started)
        outcome.record(
            routing_mode,
            "classification_failed"
            if routing_mode == "gate"
            else f"classification_error_{routing_mode}",
        )
        if routing_mode == "gate":
            raise
    except Exception:
        ClassificationOutcome(
            None, "unexpected_error", "model", perf_counter() - started
        ).record(routing_mode, "classification_failed")
        raise
    else:
        if not isinstance(label, str) or label not in LABELS:
            ClassificationOutcome(
                None, "invalid_label", "model", perf_counter() - started
            ).record(routing_mode, "invalid_label")
            raise ValueError("분류기가 허용되지 않은 라벨을 반환했습니다.")
        outcome = ClassificationOutcome(label, "ok", "model", perf_counter() - started)
    return _handle_outcome(
        question,
        outcome,
        read_documents=read_documents,
        answer=answer,
        retrieve=retrieve,
        routing_mode=routing_mode,
        document_flow=document_flow,
        allow_empty_retrieval=allow_empty_retrieval,
    )


def handle_classified_question(
    question: str,
    label: ClassificationLabel,
    *,
    read_documents: DocumentReader | None = None,
    answer: Answerer | None = None,
    retrieve: Retriever | None = None,
    routing_mode: RoutingMode = "gate",
    document_flow=None,
    allow_empty_retrieval=False,
) -> QuestionResult:
    _validate_routing_mode(routing_mode)
    if not isinstance(label, str) or label not in LABELS:
        ClassificationOutcome(None, "invalid_label", "client", None).record(
            routing_mode, "invalid_label"
        )
        raise ValueError("분류기가 허용되지 않은 라벨을 반환했습니다.")
    return _handle_outcome(
        question,
        ClassificationOutcome(label, "provided", "client", None),
        read_documents=read_documents,
        answer=answer,
        retrieve=retrieve,
        routing_mode=routing_mode,
        document_flow=document_flow,
        allow_empty_retrieval=allow_empty_retrieval,
    )


def _handle_outcome(
    question,
    outcome,
    *,
    read_documents,
    answer,
    retrieve,
    routing_mode,
    document_flow,
    allow_empty_retrieval,
):
    outcome.record(routing_mode)
    if routing_mode == "gate" and outcome.label == "CLARIFY":
        record_routing({"processing_path": "clarify"})
        return QuestionResult(
            "어떤 대상에 대해 어떤 도움이 필요한지 조금 더 알려주세요."
        )
    if routing_mode == "gate" and outcome.label == "UNSUPPORTED":
        record_routing({"processing_path": "unsupported"})
        return QuestionResult("지원 범위 밖의 요청 혹은 질문입니다.")
    advisory = (
        ClassificationContext(outcome.label)
        if routing_mode == "advisory"
        and outcome.source == "model"
        and outcome.status == "ok"
        else None
    )
    return answer_question_with_documents(
        question,
        read_documents=read_documents,
        answer=answer,
        retrieve=retrieve,
        routing_mode=routing_mode,
        label_source=outcome.source,
        classification_status=outcome.status,
        classification_elapsed_seconds=outcome.elapsed_seconds,
        classification_context=advisory,
        document_flow=document_flow,
        allow_empty_retrieval=allow_empty_retrieval,
    )


def answer_question_with_documents(
    question: str,
    *,
    read_documents: DocumentReader | None = None,
    answer: Answerer | None = None,
    retrieve: Retriever | None = None,
    routing_mode: RoutingMode = "gate",
    label_source=None,
    classification_status=None,
    classification_elapsed_seconds=None,
    classification_context: ClassificationContext | None = None,
    document_flow=None,
    allow_empty_retrieval=False,
) -> QuestionResult:
    """Direct-call compatibility; HTTP injects a complete full or RAG flow."""
    record_routing(
        {
            "routing_mode": routing_mode,
            "label_source": label_source,
            "classification_status": classification_status,
            "classification_elapsed_seconds": classification_elapsed_seconds,
            "generation_attempted": False,
        }
    )
    if document_flow is None:
        if read_documents is None or answer is None:
            raise TypeError(
                "A document flow or document reader and answerer is required"
            )
        document_flow = build_legacy_flow(
            read_documents,
            answer,
            retrieve,
            allow_empty_retrieval=allow_empty_retrieval,
        )
    return QuestionResult(
        document_flow.invoke(
            {"question": question, "classification_context": classification_context}
        )
    )


def _validate_routing_mode(routing_mode: str) -> None:
    if routing_mode not in {"gate", "shadow", "advisory"}:
        raise ValueError("routing_mode must be gate, shadow or advisory")
