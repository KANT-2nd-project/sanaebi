"""SQLite-only published snapshots shared by every runtime answer entrypoint."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType

from app.documents.repository import DocumentRepository
from app.settings import get_document_database_path

NO_DOCUMENTS_MESSAGE = "현재 확인 가능한 회사 문서가 없어 답변하기 어렵습니다."


class DocumentStorageError(Exception):
    """A missing/unavailable store must not be treated as an empty collection."""


@dataclass(frozen=True)
class DocumentContext:
    document_id: str
    knowledge_id: str
    revision_id: str
    revision: int
    title: str
    body: str
    source_reference: str
    content_hash: str
    metadata: Mapping


@dataclass(frozen=True)
class DocumentContextSnapshot:
    documents: tuple[DocumentContext, ...]

    @property
    def fingerprint(self):
        entries = [
            (d.knowledge_id, d.revision_id, d.title, d.content_hash)
            for d in self.documents
        ]
        return hashlib.sha256(
            json.dumps(entries, ensure_ascii=False).encode()
        ).hexdigest()


def _context(detail):
    revision = detail["published"]
    origin = detail.get("provenance")
    knowledge_id = origin["source_document_id"] if origin else detail["id"]
    metadata = dict(revision["metadata"])
    for field in ("source_ids", "policy_decision_ids"):
        metadata[field] = tuple(metadata[field])
    return DocumentContext(
        document_id=detail["id"],
        knowledge_id=knowledge_id,
        revision_id=revision["id"],
        revision=revision["revision_number"],
        title=revision["title"],
        body=revision["body"],
        source_reference=revision["source_url"] or f"document:{knowledge_id}",
        content_hash=hashlib.sha256(revision["body"].encode()).hexdigest(),
        metadata=MappingProxyType(metadata),
    )


class DocumentContextProvider:
    def __init__(self, *, repository=None, database_path: Path | None = None):
        self.repository = repository or DocumentRepository(
            database_path or get_document_database_path()
        )
        if os.getenv("IEUM_WORKS_PATH"):
            warnings.warn(
                "IEUM_WORKS_PATH is ignored by runtime; use SANAEBI_DOCUMENT_DB or explicit evaluation documents_path.",
                stacklevel=2,
            )

    def snapshot(self, today: date | None = None) -> DocumentContextSnapshot:
        try:
            # Read-only open: no file creation and no implicit schema migration.
            documents = self.repository.published_snapshot(today=today)
            return DocumentContextSnapshot(tuple(_context(d) for d in documents))
        except (sqlite3.Error, OSError) as exc:
            raise DocumentStorageError("문서 저장소를 사용할 수 없습니다.") from exc
