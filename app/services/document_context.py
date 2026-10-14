"""요청 시점의 baseline과 게시된 문서 snapshot을 합친다."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from app.company_knowledge import get_documents_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCUMENT_DB_PATH = PROJECT_ROOT / "var" / "documents.sqlite3"


@dataclass(frozen=True)
class DocumentContext:
    """답변 계층에 전달할 한 문서의 식별 정보와 본문."""

    source_kind: Literal["baseline", "registered"]
    document_id: str
    revision: str
    title: str
    body: str
    source_reference: str


@dataclass(frozen=True)
class DocumentContextSnapshot:
    """하나의 질문이 사용할 고정 문서 목록."""

    documents: tuple[DocumentContext, ...]
    duplicate_count: int = 0


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _baseline_contexts(path: Path) -> tuple[list[DocumentContext], int]:
    contexts: list[DocumentContext] = []
    seen_rows: set[str] = set()
    seen_ids: set[str] = set()
    duplicate_count = 0

    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue

            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{line_number}번째 줄은 JSON 객체여야 합니다.")

            title = row.get("title")
            body = row.get("document")
            if not isinstance(title, str) or not isinstance(body, str):
                raise TypeError(
                    f"{line_number}번째 줄의 title과 document는 문자열이어야 합니다."
                )
            if not title.strip() or not body.strip():
                raise ValueError(
                    f"{line_number}번째 줄의 제목과 본문은 비어 있을 수 없습니다."
                )

            canonical_row = json.dumps(
                row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if canonical_row in seen_rows:
                duplicate_count += 1
                continue
            seen_rows.add(canonical_row)

            if "document_id" not in row:
                document_id = _sha256(title + body)
            else:
                raw_id = row["document_id"]
                if not isinstance(raw_id, str) or not raw_id.strip():
                    raise TypeError(
                        f"{line_number}번째 줄의 document_id는 비어 있지 않은 문자열이어야 합니다."
                    )
                document_id = raw_id

            if document_id in seen_ids:
                raise ValueError(
                    f"{line_number}번째 줄에서 baseline 문서 ID 중복: {document_id}"
                )
            seen_ids.add(document_id)

            if "version" in row:
                version = row["version"]
                if not isinstance(version, str):
                    raise TypeError(
                        f"{line_number}번째 줄의 version은 문자열이어야 합니다."
                    )
                if not version.strip():
                    raise ValueError(
                        f"{line_number}번째 줄의 version은 비어 있을 수 없습니다."
                    )
            else:
                version = None

            content_hash = _sha256(body)
            revision = (
                f"{version}:{content_hash}" if version is not None else content_hash
            )
            source_url = row.get("source_url")
            if source_url is not None and not isinstance(source_url, str):
                raise TypeError(
                    f"{line_number}번째 줄의 source_url은 문자열이어야 합니다."
                )

            contexts.append(
                DocumentContext(
                    source_kind="baseline",
                    document_id=document_id,
                    revision=revision,
                    title=title,
                    body=body,
                    source_reference=(
                        source_url.strip()
                        if isinstance(source_url, str) and source_url.strip()
                        else f"baseline:{document_id}"
                    ),
                )
            )

    return contexts, duplicate_count


def _registered_context(detail: Any) -> DocumentContext:
    document_id = _field(detail, "id")
    published = _field(detail, "published")
    if not isinstance(document_id, str) or not document_id:
        raise TypeError("게시 문서 snapshot의 id가 문자열이 아닙니다.")
    if published is None:
        raise TypeError(f"게시 문서 {document_id}에 published revision이 없습니다.")

    title = _field(published, "title")
    body = _field(published, "body")
    revision_number = _field(published, "revision_number")
    if not isinstance(title, str) or not isinstance(body, str):
        raise TypeError(f"게시 문서 {document_id}의 title과 body가 문자열이 아닙니다.")
    if revision_number is None:
        raise TypeError(f"게시 문서 {document_id}의 revision_number가 없습니다.")

    source_url = _field(published, "source_url")
    if source_url is not None and not isinstance(source_url, str):
        raise TypeError(f"게시 문서 {document_id}의 source_url이 문자열이 아닙니다.")

    return DocumentContext(
        source_kind="registered",
        document_id=document_id,
        revision=str(revision_number),
        title=title,
        body=body,
        source_reference=(
            source_url.strip()
            if isinstance(source_url, str) and source_url.strip()
            else f"registered:{document_id}"
        ),
    )


class DocumentContextProvider:
    """매 호출마다 baseline과 현재 게시 snapshot을 읽는 provider."""

    def __init__(
        self,
        baseline_path: Path | None = None,
        repository: Any | None = None,
        database_path: Path | None = None,
    ) -> None:
        self.baseline_path = Path(baseline_path or get_documents_path())
        self.repository = repository
        configured_db = os.getenv("SANAEBI_DOCUMENT_DB")
        self.database_path = Path(
            database_path or configured_db or DEFAULT_DOCUMENT_DB_PATH
        )

    def _get_repository(self) -> Any | None:
        if self.repository is not None:
            return self.repository
        if not self.database_path.exists():
            return None

        from app.document_repository import DocumentRepository

        return DocumentRepository(self.database_path)

    def snapshot(self, today: date | None = None) -> DocumentContextSnapshot:
        baseline, duplicate_count = _baseline_contexts(self.baseline_path)
        repository = self._get_repository()
        registered = (
            repository.published_snapshot(today=today) if repository is not None else []
        )
        return DocumentContextSnapshot(
            documents=(*baseline, *(_registered_context(item) for item in registered)),
            duplicate_count=duplicate_count,
        )
