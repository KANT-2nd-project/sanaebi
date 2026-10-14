"""SQLite persistence for draft and published document revisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.documents.metadata import (
    SCHEMA,
    execute_schema,
    insert_metadata,
    read_metadata,
)

SCHEMA_VERSION = 2
IDEMPOTENCY_TTL = timedelta(hours=24)


class DuplicateDocumentError(Exception):
    def __init__(self, existing_id: str):
        super().__init__("A document with the same normalized title and body exists.")
        self.existing_id = existing_id


class IdempotencyConflictError(Exception):
    pass


class RevisionConflictError(Exception):
    def __init__(self, current_version: int | None):
        super().__init__("The document changed since it was loaded.")
        self.current_version = current_version


class DocumentRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if not readonly and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            f"{self.path.resolve().as_uri()}?mode=ro" if readonly else str(self.path),
            uri=readonly,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        connection = self.connect(readonly=not immediate)
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, connection=None) -> None:
        if connection is None:
            with self.transaction() as owned:
                self.initialize(owned)
            return
        self._initialize(connection)

    def _initialize(self, connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported document database schema version: {version}"
            )
        if version == SCHEMA_VERSION:
            return

        schema = """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                draft_revision_id TEXT NOT NULL,
                published_revision_id TEXT,
                withdrawn INTEGER NOT NULL DEFAULT 0 CHECK (withdrawn IN (0, 1)),
                record_version INTEGER NOT NULL CHECK (record_version >= 1),
                dedupe_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (draft_revision_id)
                    REFERENCES document_revisions(id)
                    DEFERRABLE INITIALLY DEFERRED,
                FOREIGN KEY (published_revision_id)
                    REFERENCES document_revisions(id)
                    DEFERRABLE INITIALLY DEFERRED
            );

            CREATE TABLE document_revisions (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id),
                revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                source_label TEXT NOT NULL,
                source_url TEXT,
                owner_department TEXT,
                effective_from TEXT,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (document_id, revision_number)
            );

            CREATE INDEX document_revisions_document_id
                ON document_revisions(document_id, revision_number);
            CREATE INDEX documents_updated_at
                ON documents(updated_at DESC, id ASC);
            CREATE INDEX documents_dedupe_hash ON documents(dedupe_hash);

            CREATE TABLE document_events (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id),
                revision_id TEXT REFERENCES document_revisions(id),
                action TEXT NOT NULL CHECK (action IN ('create', 'edit', 'publish', 'withdraw')),
                actor TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );

            CREATE TABLE idempotency_keys (
                key TEXT PRIMARY KEY,
                method_path TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_status INTEGER NOT NULL,
                response_body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TRIGGER document_revisions_are_immutable_update
            BEFORE UPDATE ON document_revisions
            BEGIN
                SELECT RAISE(ABORT, 'document revisions are immutable');
            END;

            CREATE TRIGGER document_revisions_are_immutable_delete
            BEFORE DELETE ON document_revisions
            BEGIN
                SELECT RAISE(ABORT, 'document revisions are immutable');
            END;
            """
        if version == 0:
            execute_schema(connection, schema)
        execute_schema(connection, SCHEMA)
        for row in connection.execute("SELECT id FROM document_revisions").fetchall():
            insert_metadata(connection, row["id"])
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def create_in_transaction(
        self,
        connection: sqlite3.Connection,
        fields: dict[str, Any],
        *,
        document_id: str | None = None,
        metadata=None,
        actor="local-demo",
    ) -> dict[str, Any]:
        normalized = _normalize_fields(fields)
        now = _utc_now()
        document_id = document_id or str(uuid.uuid4())
        revision_id = str(uuid.uuid4())
        dedupe_hash = _duplicate_hash(normalized["title"], normalized["body"])
        duplicate = connection.execute(
            "SELECT id FROM documents WHERE dedupe_hash = ? LIMIT 1",
            (dedupe_hash,),
        ).fetchone()
        if duplicate is not None:
            raise DuplicateDocumentError(duplicate["id"])

        content_hash = _content_hash(normalized)
        connection.execute(
            """INSERT INTO documents
               (id, draft_revision_id, published_revision_id, withdrawn,
                record_version, dedupe_hash, created_at, updated_at)
               VALUES (?, ?, NULL, 0, 1, ?, ?, ?)""",
            (document_id, revision_id, dedupe_hash, now, now),
        )
        connection.execute(
            """INSERT INTO document_revisions
               (id, document_id, revision_number, title, body, source_label,
                source_url, owner_department, effective_from, content_hash, created_at)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                revision_id,
                document_id,
                normalized["title"],
                normalized["body"],
                normalized["source_label"],
                normalized["source_url"],
                normalized["owner_department"],
                normalized["effective_from"],
                content_hash,
                now,
            ),
        )
        insert_metadata(connection, revision_id, metadata)
        self._record_event(
            connection, document_id, revision_id, "create", now, actor=actor
        )
        return _get_detail(connection, document_id, _seoul_today())

    def get_in_transaction(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        today: date | None = None,
    ) -> dict[str, Any] | None:
        return _get_detail(connection, document_id, today or _seoul_today())

    def update_draft_in_transaction(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        expected_version: int,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = _normalize_fields(fields)
        current = connection.execute(
            "SELECT record_version FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if current is None or current["record_version"] != expected_version:
            raise RevisionConflictError(
                current["record_version"] if current is not None else None
            )

        revision_number = connection.execute(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM document_revisions WHERE document_id = ?",
            (document_id,),
        ).fetchone()[0]
        revision_id = str(uuid.uuid4())
        now = _utc_now()
        self._insert_revision(
            connection, document_id, revision_id, revision_number, normalized, now
        )
        previous = connection.execute(
            "SELECT draft_revision_id FROM documents WHERE id = ?", (document_id,)
        ).fetchone()[0]
        metadata = read_metadata(connection, previous)
        metadata["review_status"] = "unreviewed"
        insert_metadata(connection, revision_id, metadata)
        cursor = connection.execute(
            """UPDATE documents
               SET draft_revision_id = ?, dedupe_hash = ?, record_version = record_version + 1,
                   updated_at = ?
               WHERE id = ? AND record_version = ?""",
            (
                revision_id,
                _duplicate_hash(normalized["title"], normalized["body"]),
                now,
                document_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise RevisionConflictError(self._current_version(connection, document_id))
        self._record_event(connection, document_id, revision_id, "edit", now)
        return _get_detail(connection, document_id, _seoul_today())

    def publish_in_transaction(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        expected_version: int,
        revision_id: str,
        *,
        actor="local-demo",
    ) -> dict[str, Any]:
        current_version = self._current_version(connection, document_id)
        if current_version != expected_version:
            raise RevisionConflictError(current_version)
        now = _utc_now()
        cursor = connection.execute(
            """UPDATE documents
               SET published_revision_id = ?, withdrawn = 0,
                   record_version = record_version + 1, updated_at = ?
               WHERE id = ? AND record_version = ?""",
            (revision_id, now, document_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise RevisionConflictError(self._current_version(connection, document_id))
        self._record_event(
            connection, document_id, revision_id, "publish", now, actor=actor
        )
        return _get_detail(connection, document_id, _seoul_today())

    def withdraw_in_transaction(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        expected_version: int,
    ) -> dict[str, Any]:
        current_version = self._current_version(connection, document_id)
        if current_version != expected_version:
            raise RevisionConflictError(current_version)
        now = _utc_now()
        cursor = connection.execute(
            """UPDATE documents
               SET withdrawn = 1, record_version = record_version + 1, updated_at = ?
               WHERE id = ? AND record_version = ?""",
            (now, document_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise RevisionConflictError(self._current_version(connection, document_id))
        detail = _get_detail(connection, document_id, _seoul_today())
        self._record_event(connection, document_id, None, "withdraw", now)
        return detail

    def get(self, document_id: str) -> dict[str, Any] | None:
        with self.transaction(immediate=False) as connection:
            return _get_detail(connection, document_id, _seoul_today())

    def list(
        self,
        q: str = "",
        status: str = "all",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if status == "draft":
            conditions.append("d.withdrawn = 0 AND d.published_revision_id IS NULL")
        elif status == "published":
            conditions.append("d.withdrawn = 0 AND d.published_revision_id IS NOT NULL")
        elif status == "withdrawn":
            conditions.append("d.withdrawn = 1")
        if q:
            escaped_query = (
                q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            conditions.append("dr.title LIKE ? ESCAPE '\\'")
            parameters.append(f"%{escaped_query}%")
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        with self.transaction(immediate=False) as connection:
            total = connection.execute(
                """SELECT COUNT(*) FROM documents d
                   JOIN document_revisions dr ON dr.id = d.draft_revision_id"""
                + where_clause,
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT d.id FROM documents d
                   JOIN document_revisions dr ON dr.id = d.draft_revision_id"""
                + where_clause
                + " ORDER BY d.updated_at DESC, d.id ASC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            today = _seoul_today()
            items = [
                _summary(_get_detail(connection, row["id"], today)) for row in rows
            ]
            return {"items": items, "total": total}

    def published_snapshot(self, today: date | None = None) -> list[dict[str, Any]]:
        effective_today = today or _seoul_today()
        with self.transaction(immediate=False) as connection:
            if (
                connection.execute("PRAGMA user_version").fetchone()[0]
                != SCHEMA_VERSION
            ):
                raise sqlite3.DatabaseError("Unsupported document schema")
            rows = connection.execute(
                """SELECT d.id
                   FROM documents d
                   JOIN document_revisions p ON p.id = d.published_revision_id
                   LEFT JOIN document_imports i ON i.document_id = d.id
                   WHERE d.withdrawn = 0
                     AND (p.effective_from IS NULL OR p.effective_from <= ?)
                   ORDER BY CASE WHEN i.document_id IS NULL THEN 1 ELSE 0 END,
                            i.source_ordinal, d.created_at, d.id ASC""",
                (effective_today.isoformat(),),
            ).fetchall()
            return [_get_detail(connection, row["id"], effective_today) for row in rows]

    def lookup_idempotency(
        self,
        connection: sqlite3.Connection,
        key: str,
        method_path: str,
        request_hash: str,
    ) -> tuple[int, dict[str, Any]] | None:
        row = connection.execute(
            """SELECT method_path, request_hash, response_status,
                      response_body, created_at
               FROM idempotency_keys WHERE key = ?""",
            (key,),
        ).fetchone()
        if row is None:
            return None
        created_at = datetime.fromisoformat(row["created_at"])
        if _utc_datetime() - created_at >= IDEMPOTENCY_TTL:
            connection.execute("DELETE FROM idempotency_keys WHERE key = ?", (key,))
            return None
        if row["method_path"] != method_path or row["request_hash"] != request_hash:
            raise IdempotencyConflictError
        return row["response_status"], json.loads(row["response_body"])

    def store_idempotency(
        self,
        connection: sqlite3.Connection,
        key: str,
        method_path: str,
        request_hash: str,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO idempotency_keys
               (key, method_path, request_hash, response_status, response_body, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                key,
                method_path,
                request_hash,
                response_status,
                json.dumps(response_body, ensure_ascii=False, separators=(",", ":")),
                _utc_now(),
            ),
        )

    def _record_event(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        revision_id: str | None,
        action: str,
        occurred_at: str,
        *,
        actor="local-demo",
    ) -> None:
        connection.execute(
            """INSERT INTO document_events
               (id, document_id, revision_id, action, actor, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), document_id, revision_id, action, actor, occurred_at),
        )

    def _insert_revision(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        revision_id: str,
        revision_number: int,
        fields: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """INSERT INTO document_revisions
               (id, document_id, revision_number, title, body, source_label,
                source_url, owner_department, effective_from, content_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                revision_id,
                document_id,
                revision_number,
                fields["title"],
                fields["body"],
                fields["source_label"],
                fields["source_url"],
                fields["owner_department"],
                fields["effective_from"],
                _content_hash(fields),
                created_at,
            ),
        )

    def _current_version(
        self, connection: sqlite3.Connection, document_id: str
    ) -> int | None:
        row = connection.execute(
            "SELECT record_version FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return row["record_version"] if row is not None else None


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    title = fields.get("title")
    body = fields.get("body")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must contain non-whitespace text")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body must contain non-whitespace text")
    effective_from = fields.get("effective_from")
    if isinstance(effective_from, date):
        effective_from = effective_from.isoformat()
    elif effective_from is not None:
        effective_from = date.fromisoformat(str(effective_from)).isoformat()
    return {
        "title": title,
        "body": body,
        "source_label": fields.get("source_label") or "",
        "source_url": fields.get("source_url") or None,
        "owner_department": fields.get("owner_department") or None,
        "effective_from": effective_from,
    }


def _content_hash(fields: dict[str, Any]) -> str:
    content = json.dumps(
        fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _duplicate_hash(title: str, body: str) -> str:
    normalize = lambda value: " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )
    value = f"{normalize(title)}\0{normalize(body)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _get_detail(
    connection: sqlite3.Connection, document_id: str, today: date
) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT d.id, d.record_version, d.withdrawn, d.created_at, d.updated_at,
                  dr.id AS draft_id, dr.revision_number AS draft_revision_number,
                  dr.title AS draft_title, dr.body AS draft_body,
                  dr.source_label AS draft_source_label, dr.source_url AS draft_source_url,
                  dr.owner_department AS draft_owner_department,
                  dr.effective_from AS draft_effective_from,
                  dr.content_hash AS draft_content_hash,
                  dr.created_at AS draft_created_at,
                  pr.id AS published_id,
                  pr.revision_number AS published_revision_number,
                  pr.title AS published_title, pr.body AS published_body,
                  pr.source_label AS published_source_label,
                  pr.source_url AS published_source_url,
                  pr.owner_department AS published_owner_department,
                  pr.effective_from AS published_effective_from,
                  pr.content_hash AS published_content_hash,
                  pr.created_at AS published_created_at
           FROM documents d
           JOIN document_revisions dr ON dr.id = d.draft_revision_id
           LEFT JOIN document_revisions pr ON pr.id = d.published_revision_id
           WHERE d.id = ?""",
        (document_id,),
    ).fetchone()
    if row is None:
        return None

    draft = _revision_from_row(row, "draft")
    published = _revision_from_row(row, "published") if row["published_id"] else None
    draft["metadata"] = read_metadata(connection, draft["id"])
    if published:
        published["metadata"] = read_metadata(connection, published["id"])
    origin = connection.execute(
        "SELECT source_namespace, source_document_id, source_file_sha256, row_sha256, imported_at FROM document_imports WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    withdrawn = bool(row["withdrawn"])
    if withdrawn:
        status = "withdrawn"
        eligibility = "withdrawn"
    elif published is None:
        status = "draft"
        eligibility = "draft"
    else:
        status = "published"
        effective_from = published["effective_from"]
        eligibility = (
            "scheduled"
            if effective_from is not None and date.fromisoformat(effective_from) > today
            else "eligible"
        )
    return {
        "id": row["id"],
        "record_version": row["record_version"],
        "withdrawn": withdrawn,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": status,
        "eligibility": eligibility,
        "provenance": dict(origin) if origin else None,
        "draft": draft,
        "published": published,
    }


def _revision_from_row(row: sqlite3.Row, prefix: str) -> dict[str, Any]:
    return {
        "id": row[f"{prefix}_id"],
        "revision_number": row[f"{prefix}_revision_number"],
        "title": row[f"{prefix}_title"],
        "body": row[f"{prefix}_body"],
        "source_label": row[f"{prefix}_source_label"],
        "source_url": row[f"{prefix}_source_url"],
        "owner_department": row[f"{prefix}_owner_department"],
        "effective_from": row[f"{prefix}_effective_from"],
        "content_hash": row[f"{prefix}_content_hash"],
        "created_at": row[f"{prefix}_created_at"],
    }


def _summary(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        **{
            key: value
            for key, value in detail.items()
            if key not in {"draft", "published"}
        },
        "draft": _revision_summary(detail["draft"]),
        "published": (
            _revision_summary(detail["published"])
            if detail["published"] is not None
            else None
        ),
    }


def _revision_summary(revision: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in revision.items() if key != "body"}


def _utc_datetime() -> datetime:
    return datetime.now(UTC)


def _utc_now() -> str:
    return _utc_datetime().isoformat(timespec="microseconds")


def _seoul_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()
