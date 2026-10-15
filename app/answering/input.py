"""Immutable, common input contract for full and retrieved answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.documents.context import DocumentContextSnapshot
from generation.advisory import ClassificationContext
from generation.documents import render_document

if TYPE_CHECKING:
    from app.retrieval.types import RetrievedContext


@dataclass(frozen=True)
class AnswerInput:
    question: str
    documents: tuple[str, ...]
    snapshot_fingerprint: str
    classification_context: ClassificationContext | None = None
    evidence_state: str | None = None

    @classmethod
    def from_snapshot(
        cls,
        question: str,
        snapshot: DocumentContextSnapshot,
        *,
        classification_context: ClassificationContext | None = None,
    ) -> AnswerInput:
        documents = tuple(
            render_document(d.knowledge_id, d.title, d.body, d.revision)
            for d in snapshot.documents
        )
        return cls(
            question,
            documents,
            snapshot.fingerprint,
            classification_context,
        )

    @classmethod
    def from_retrieved(
        cls,
        question: str,
        context: RetrievedContext,
        *,
        classification_context: ClassificationContext | None = None,
    ) -> AnswerInput:
        documents = tuple(
            "[현재 게시 문서의 발췌 근거]\n"
            + render_document(e.knowledge_id, e.title, e.text, e.revision)
            for e in context.evidence
        )
        return cls(
            question,
            documents,
            context.snapshot_fingerprint,
            classification_context,
            (
                "available"
                if documents
                else "no_published_documents"
                if context.source_document_count == 0
                else "no_matches"
            ),
        )
