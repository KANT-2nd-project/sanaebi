"""Stable internal values and safe retrieval failure categories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class RetrievalError(Exception):
    """Base class for expected retrieval-boundary failures."""


class RetrievalUnavailable(RetrievalError):
    """Model or index storage is missing, corrupt, or unusable."""


class RetrievalNotReady(RetrievalError):
    """At least one currently published revision has not been indexed."""


class RetrievalInputTooLong(RetrievalError):
    """The prefixed query exceeds the model's non-truncating token limit."""


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    kind: str = "body"


@dataclass(frozen=True)
class Chunk:
    document_id: str
    revision_id: str
    ordinal: int
    spans: tuple[SourceSpan, ...]
    heading: str
    embedding_header: str
    text: str
    embedding_text: str
    input_key: str
    chunk_id: str


@dataclass(frozen=True)
class Evidence:
    knowledge_id: str
    document_id: str
    revision_id: str
    revision: int
    title: str
    text: str
    source_reference: str
    spans: tuple[SourceSpan, ...]
    chunk_ids: tuple[str, ...]
    score: float
    rank: int
    expanded_chunk_ids: tuple[str, ...] = ()
    original_spans: tuple[SourceSpan, ...] = ()
    expanded_spans: tuple[SourceSpan, ...] = ()


@dataclass(frozen=True)
class RetrievedContext:
    snapshot_fingerprint: str
    spec_id: str
    evidence: tuple[Evidence, ...]
    candidate_count: int
    selected_count: int
    observed_at: datetime
    candidate_chunk_ids: tuple[str, ...] = ()
    search_config_id: str = ""
    source_document_count: int | None = None
