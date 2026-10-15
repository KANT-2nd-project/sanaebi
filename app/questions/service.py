"""HTTP·모델 구현과 독립적인 라벨별 질문 처리 정책."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Literal, Protocol

from app.classification.errors import (
    ClassificationInferenceError,
    ClassificationUnavailable,
)
from app.diagnostics.trace import (
    record_classification,
    record_retrieval,
    record_routing,
)
from app.documents.context import DocumentContextSnapshot
from contracts.classification import ClassificationLabel
from generation.advisory import ClassificationContext

if TYPE_CHECKING:
    from app.retrieval.types import RetrievedContext

Retriever = Callable[[str, DocumentContextSnapshot], "RetrievedContext"]

Classifier = Callable[[str], ClassificationLabel]
DocumentReader = Callable[[], DocumentContextSnapshot]


class Answerer(Protocol):
    def __call__(
        self,
        question: str,
        context: DocumentContextSnapshot | RetrievedContext,
        *,
        classification_context: ClassificationContext | None = None,
    ) -> str: ...


RoutingMode = Literal["gate", "shadow", "advisory"]
_VALID_LABELS = frozenset({"SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"})


@dataclass(frozen=True)
class QuestionResult:
    text: str


def handle_question(
    question: str,
    *,
    classify: Classifier,
    read_documents: DocumentReader,
    answer: Answerer,
    retrieve: Retriever | None = None,
    routing_mode: RoutingMode = "gate",
) -> QuestionResult:
    _validate_routing_mode(routing_mode)
    record_routing(
        {
            "routing_mode": routing_mode,
            "label_source": "model",
            "classification_status": "running",
            "classification_elapsed_seconds": None,
            "processing_path": "classification",
            "generation_attempted": False,
        }
    )
    started = perf_counter()
    try:
        label = classify(question)
    except (ClassificationUnavailable, ClassificationInferenceError) as error:
        seconds = perf_counter() - started
        status = (
            "unavailable"
            if isinstance(error, ClassificationUnavailable)
            else "inference_error"
        )
        record_routing(
            {
                "classification_status": status,
                "classification_elapsed_seconds": seconds,
                "processing_path": (
                    f"classification_error_{routing_mode}"
                    if routing_mode in {"shadow", "advisory"}
                    else "classification_failed"
                ),
            }
        )
        if routing_mode == "gate":
            raise
        return answer_question_with_documents(
            question,
            read_documents=read_documents,
            answer=answer,
            retrieve=retrieve,
            routing_mode=routing_mode,
            label_source="model",
            classification_status=status,
            classification_elapsed_seconds=seconds,
        )
    except Exception:
        record_routing(
            {
                "classification_status": "unexpected_error",
                "classification_elapsed_seconds": perf_counter() - started,
                "processing_path": "classification_failed",
            }
        )
        raise

    seconds = perf_counter() - started
    if not isinstance(label, str) or label not in _VALID_LABELS:
        record_routing(
            {
                "classification_status": "invalid_label",
                "classification_elapsed_seconds": seconds,
                "processing_path": "invalid_label",
            }
        )
        raise ValueError("분류기가 허용되지 않은 라벨을 반환했습니다.")

    return _handle_validated_label(
        question,
        label,
        read_documents=read_documents,
        answer=answer,
        retrieve=retrieve,
        routing_mode=routing_mode,
        label_source="model",
        classification_status="ok",
        classification_elapsed_seconds=seconds,
    )


def handle_classified_question(
    question: str,
    label: ClassificationLabel,
    *,
    read_documents: DocumentReader,
    answer: Answerer,
    retrieve: Retriever | None = None,
    routing_mode: RoutingMode = "gate",
) -> QuestionResult:
    _validate_routing_mode(routing_mode)
    if not isinstance(label, str) or label not in _VALID_LABELS:
        record_routing(
            {
                "routing_mode": routing_mode,
                "label_source": "client",
                "classification_status": "invalid_label",
                "classification_elapsed_seconds": None,
                "processing_path": "invalid_label",
                "generation_attempted": False,
            }
        )
        raise ValueError("분류기가 허용되지 않은 라벨을 반환했습니다.")

    return _handle_validated_label(
        question,
        label,
        read_documents=read_documents,
        answer=answer,
        retrieve=retrieve,
        routing_mode=routing_mode,
        label_source="client",
        classification_status="provided",
        classification_elapsed_seconds=None,
    )


def _handle_validated_label(
    question: str,
    label: ClassificationLabel,
    *,
    read_documents: DocumentReader,
    answer: Answerer,
    retrieve: Retriever | None = None,
    routing_mode: RoutingMode,
    label_source: Literal["model", "client"],
    classification_status: str,
    classification_elapsed_seconds: float | None,
) -> QuestionResult:
    record_classification(label)
    record_routing(
        {
            "routing_mode": routing_mode,
            "label_source": label_source,
            "classification_status": classification_status,
            "classification_elapsed_seconds": classification_elapsed_seconds,
            "generation_attempted": False,
        }
    )

    if routing_mode == "gate" and label == "CLARIFY":
        record_routing({"processing_path": "clarify"})
        return QuestionResult(
            text="어떤 대상에 대해 어떤 도움이 필요한지 조금 더 알려주세요."
        )
    if routing_mode == "gate" and label == "UNSUPPORTED":
        record_routing({"processing_path": "unsupported"})
        return QuestionResult(text="지원 범위 밖의 요청 혹은 질문입니다.")

    return answer_question_with_documents(
        question,
        read_documents=read_documents,
        answer=answer,
        retrieve=retrieve,
        routing_mode=routing_mode,
        label_source=label_source,
        classification_status=classification_status,
        classification_elapsed_seconds=classification_elapsed_seconds,
        classification_context=(
            ClassificationContext(label)
            if routing_mode == "advisory" and label_source == "model"
            else None
        ),
    )


def answer_question_with_documents(
    question: str,
    *,
    read_documents: DocumentReader,
    answer: Answerer,
    retrieve: Retriever | None = None,
    routing_mode: RoutingMode = "gate",
    label_source: Literal["model", "client"] | None = None,
    classification_status: str | None = None,
    classification_elapsed_seconds: float | None = None,
    classification_context: ClassificationContext | None = None,
) -> QuestionResult:
    """한 번 스냅샷을 읽고, 문서가 있을 때만 답변기를 호출한다."""
    trace_fields = {
        "routing_mode": routing_mode,
        "label_source": label_source,
        "classification_status": classification_status,
        "classification_elapsed_seconds": classification_elapsed_seconds,
        "generation_attempted": False,
        "processing_path": "document_lookup",
    }
    record_routing(trace_fields)
    documents = read_documents()
    if not documents.documents:
        record_routing({"processing_path": "empty_documents"})
        return QuestionResult(
            text="현재 확인 가능한 회사 문서가 없어 답변하기 어렵습니다."
        )

    context = documents
    if retrieve is not None:
        record_routing({"processing_path": "retrieval", "generation_attempted": False})
        started = perf_counter()
        try:
            context = retrieve(question, documents)
        except Exception:
            record_retrieval(
                status="failed", seconds=perf_counter() - started, selected_count=0
            )
            raise
        else:
            record_retrieval(
                status="ok",
                seconds=perf_counter() - started,
                selected_count=len(getattr(context, "evidence", ())),
            )
        if not context.evidence:
            record_routing(
                {"processing_path": "empty_retrieval", "generation_attempted": False}
            )
            return QuestionResult(
                text="관련 문서에서 답변에 필요한 근거를 찾지 못했습니다."
            )
    record_routing({"processing_path": "generation", "generation_attempted": True})
    if classification_context is None:
        answer_text = answer(question, context)
    else:
        answer_text = answer(
            question, context, classification_context=classification_context
        )

    return QuestionResult(text=answer_text)


def _validate_routing_mode(routing_mode: str) -> None:
    if routing_mode not in {"gate", "shadow", "advisory"}:
        raise ValueError("routing_mode must be gate, shadow or advisory")
