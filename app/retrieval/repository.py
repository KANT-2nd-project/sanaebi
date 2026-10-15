"""Separate SQLite persistence for exact vector search and revision mappings."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.retrieval.chunking import (
    chunk_identifier,
    embedding_input,
    embedding_input_key,
)
from app.retrieval.config import (
    CANONICAL_SPEC,
    SCHEMA_VERSION,
    SPEC_ID,
    VECTOR_DIMENSION,
)
from app.retrieval.types import (
    Chunk,
    RetrievalNotReady,
    RetrievalUnavailable,
    SourceSpan,
)

BUSY_TIMEOUT_MS = 1_000


def document_digest(title: str, body: str) -> str:
    payload = json.dumps([title, body], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class IndexRepository:
    """Read-only on construction; writers initialize only when explicitly invoked."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.spec_root = self.root / "schema-v1" / SPEC_ID
        self.database_path = self.spec_root / "index.sqlite3"
        self.lock_path = self.spec_root / "writer.lock"

    def connect(self, *, readonly=False):
        try:
            if readonly:
                if not self.database_path.is_file():
                    return None
                connection = sqlite3.connect(
                    self.database_path.resolve().as_uri() + "?mode=ro",
                    uri=True,
                    timeout=BUSY_TIMEOUT_MS / 1000,
                    isolation_level=None,
                )
            else:
                self.spec_root.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(
                    self.database_path,
                    timeout=BUSY_TIMEOUT_MS / 1000,
                    isolation_level=None,
                )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            return connection
        except (sqlite3.Error, OSError) as exc:
            raise RetrievalUnavailable("검색 색인을 열 수 없습니다.") from exc

    def initialize(self):
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise RetrievalUnavailable("검색 색인 schema가 지원되지 않습니다.")
            connection.execute("BEGIN IMMEDIATE")
            for statement in (
                """CREATE TABLE IF NOT EXISTS index_spec (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version INTEGER NOT NULL,
                    spec_id TEXT NOT NULL,
                    canonical_spec TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS indexed_revisions (
                    document_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    title_body_digest TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
                    indexed_at TEXT NOT NULL,
                    PRIMARY KEY (document_id, revision_id)
                )""",
                """CREATE TABLE IF NOT EXISTS chunks (
                    document_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                    chunk_id TEXT NOT NULL UNIQUE,
                    spans_json TEXT NOT NULL,
                    heading TEXT NOT NULL,
                    embedding_header TEXT NOT NULL,
                    input_key TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    PRIMARY KEY (document_id, revision_id, ordinal),
                    FOREIGN KEY (document_id, revision_id)
                        REFERENCES indexed_revisions(document_id, revision_id)
                        ON DELETE CASCADE
                )""",
                "CREATE INDEX IF NOT EXISTS chunks_input_key ON chunks(input_key)",
            ):
                connection.execute(statement)
            row = connection.execute(
                "SELECT schema_version, spec_id, canonical_spec FROM index_spec WHERE singleton=1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO index_spec VALUES (1, ?, ?, ?)",
                    (SCHEMA_VERSION, SPEC_ID, CANONICAL_SPEC),
                )
            elif (
                row["schema_version"] != SCHEMA_VERSION
                or row["spec_id"] != SPEC_ID
                or row["canonical_spec"] != CANONICAL_SPEC
            ):
                raise RetrievalUnavailable(
                    "검색 색인 모델 spec이 현재 설정과 다릅니다."
                )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except RetrievalUnavailable:
            connection.rollback()
            raise
        except (sqlite3.Error, OSError) as exc:
            connection.rollback()
            raise RetrievalUnavailable("검색 색인을 초기화할 수 없습니다.") from exc
        finally:
            connection.close()

    def status(self, snapshot):
        documents = snapshot.documents
        expected = len(documents)
        if not expected:
            return {"ready": True, "expected": 0, "ready_count": 0, "missing": 0}
        connection = self.connect(readonly=True)
        if connection is None:
            return {
                "ready": False,
                "expected": expected,
                "ready_count": 0,
                "missing": expected,
            }
        try:
            self._assert_spec(connection)
            connection.execute("BEGIN")
            ready_count = sum(
                self._load_document(connection, document, load_vectors=False)
                is not None
                for document in documents
            )
            connection.commit()
        except RetrievalUnavailable:
            connection.rollback()
            raise
        except (sqlite3.Error, OSError) as exc:
            connection.rollback()
            raise RetrievalUnavailable("검색 색인 상태를 읽을 수 없습니다.") from exc
        finally:
            connection.close()
        missing = expected - ready_count
        return {
            "ready": missing == 0,
            "expected": expected,
            "ready_count": ready_count,
            "missing": missing,
        }

    def initialize_if_missing(self):
        if self.database_path.is_file():
            return
        self.initialize()

    def store_documents(self, records):
        """Atomically replace each supplied document/revision's complete chunk set."""
        self.initialize_if_missing()
        connection = self.connect()
        if connection is None:
            raise RetrievalUnavailable("검색 색인을 열 수 없습니다.")
        try:
            self._assert_spec(connection)
            connection.execute("BEGIN IMMEDIATE")
            for document, chunks, vectors in records:
                self._store_one(connection, document, chunks, vectors)
            connection.commit()
        except RetrievalUnavailable:
            connection.rollback()
            raise
        except (sqlite3.Error, OSError) as exc:
            connection.rollback()
            raise RetrievalUnavailable("검색 색인을 저장할 수 없습니다.") from exc
        finally:
            connection.close()

    def _store_one(self, connection, document, chunks, vectors):
        array = _validated_matrix(vectors, rows=len(chunks))
        if not chunks and document.body.strip():
            raise RetrievalUnavailable("내용이 있는 문서에서 청크를 만들지 못했습니다.")
        if any(
            chunk.document_id != document.document_id
            or chunk.revision_id != document.revision_id
            or chunk.ordinal != ordinal
            for ordinal, chunk in enumerate(chunks)
        ):
            raise RetrievalUnavailable("저장할 청크 식별 정보가 올바르지 않습니다.")
        connection.execute(
            "DELETE FROM indexed_revisions WHERE document_id=? AND revision_id=?",
            (document.document_id, document.revision_id),
        )
        connection.execute(
            "INSERT INTO indexed_revisions VALUES (?, ?, ?, ?, ?)",
            (
                document.document_id,
                document.revision_id,
                document_digest(document.title, document.body),
                len(chunks),
                datetime.now(UTC).isoformat(),
            ),
        )
        for chunk, vector in zip(chunks, array, strict=True):
            self._validate_chunk_against_source(document, chunk)
            spans_json = json.dumps(
                [
                    {"start": span.start, "end": span.end, "kind": span.kind}
                    for span in chunk.spans
                ],
                separators=(",", ":"),
            )
            connection.execute(
                """INSERT INTO chunks
                   (document_id, revision_id, ordinal, chunk_id, spans_json,
                    heading, embedding_header, input_key, vector_blob)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk.document_id,
                    chunk.revision_id,
                    chunk.ordinal,
                    chunk.chunk_id,
                    spans_json,
                    chunk.heading,
                    chunk.embedding_header,
                    chunk.input_key,
                    np.asarray(vector, dtype="<f4").tobytes(),
                ),
            )

    def reusable_vectors(self, input_keys):
        if not input_keys or not self.database_path.is_file():
            return {}
        connection = self.connect(readonly=True)
        if connection is None:
            return {}
        try:
            self._assert_spec(connection)
            unique = tuple(dict.fromkeys(input_keys))
            placeholders = ",".join("?" for _ in unique)
            rows = connection.execute(
                f"SELECT input_key, vector_blob FROM chunks WHERE input_key IN ({placeholders}) ORDER BY chunk_id",
                unique,
            ).fetchall()
            result = {}
            for row in rows:
                result.setdefault(
                    row["input_key"], _vector_from_blob(row["vector_blob"])
                )
            return result
        except RetrievalUnavailable:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise RetrievalUnavailable("기존 검색 벡터를 읽을 수 없습니다.") from exc
        finally:
            connection.close()

    def current_chunks(self, snapshot):
        documents = snapshot.documents
        if not documents:
            return []
        connection = self.connect(readonly=True)
        if connection is None:
            raise RetrievalNotReady("검색 색인이 준비되지 않았습니다.")
        try:
            self._assert_spec(connection)
            connection.execute("BEGIN")
            result = []
            for document in documents:
                loaded = self._load_document(connection, document, load_vectors=True)
                if loaded is None:
                    raise RetrievalNotReady(
                        "현재 게시 문서의 검색 색인이 준비되지 않았습니다."
                    )
                result.extend(loaded)
            connection.commit()
            return result
        except (RetrievalUnavailable, RetrievalNotReady):
            connection.rollback()
            raise
        except (sqlite3.Error, OSError) as exc:
            connection.rollback()
            raise RetrievalUnavailable("검색 색인을 읽을 수 없습니다.") from exc
        finally:
            connection.close()

    def _load_document(self, connection, document, *, load_vectors):
        row = connection.execute(
            """SELECT title_body_digest, chunk_count FROM indexed_revisions
               WHERE document_id=? AND revision_id=?""",
            (document.document_id, document.revision_id),
        ).fetchone()
        if row is None:
            return None
        if row["title_body_digest"] != document_digest(document.title, document.body):
            return None
        rows = connection.execute(
            """SELECT ordinal, chunk_id, spans_json, heading, embedding_header,
                      input_key, vector_blob FROM chunks
               WHERE document_id=? AND revision_id=? ORDER BY ordinal""",
            (document.document_id, document.revision_id),
        ).fetchall()
        if len(rows) != row["chunk_count"]:
            return None
        chunks = []
        vectors = []
        for ordinal, stored in enumerate(rows):
            if stored["ordinal"] != ordinal:
                raise RetrievalUnavailable("검색 청크 순번이 올바르지 않습니다.")
            if not isinstance(stored["heading"], str) or not isinstance(
                stored["embedding_header"], str
            ):
                raise RetrievalUnavailable("검색 청크 헤더 형식이 올바르지 않습니다.")
            try:
                raw_spans = json.loads(stored["spans_json"])
                spans = tuple(
                    SourceSpan(int(item["start"]), int(item["end"]), str(item["kind"]))
                    for item in raw_spans
                )
            except (TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
                raise RetrievalUnavailable(
                    "검색 청크 위치 정보가 손상됐습니다."
                ) from exc
            if not spans:
                raise RetrievalUnavailable("검색 청크에 원문 위치가 없습니다.")
            for span in spans:
                if (
                    span.start < 0
                    or span.end <= span.start
                    or span.end > len(document.body)
                ):
                    raise RetrievalUnavailable(
                        "검색 청크 위치가 문서 범위를 벗어납니다."
                    )
            text = "\n".join(document.body[span.start : span.end] for span in spans)
            embedding_text = embedding_input(stored["embedding_header"], "", text)
            if embedding_input_key(embedding_text) != stored["input_key"]:
                raise RetrievalUnavailable("검색 청크 입력이 현재 문서와 다릅니다.")
            expected_id = chunk_identifier(
                document.document_id,
                document.revision_id,
                ordinal,
                stored["input_key"],
            )
            if expected_id != stored["chunk_id"]:
                raise RetrievalUnavailable("검색 청크 식별 정보가 손상됐습니다.")
            chunk = Chunk(
                document_id=document.document_id,
                revision_id=document.revision_id,
                ordinal=ordinal,
                spans=spans,
                heading=stored["heading"],
                embedding_header=stored["embedding_header"],
                text=text,
                embedding_text=embedding_text,
                input_key=stored["input_key"],
                chunk_id=stored["chunk_id"],
            )
            self._validate_chunk_against_source(document, chunk)
            chunks.append(chunk)
            if load_vectors:
                vectors.append(_vector_from_blob(stored["vector_blob"]))
            else:
                _vector_from_blob(stored["vector_blob"])
        covered = bytearray(len(document.body))
        for chunk in chunks:
            for span in chunk.spans:
                covered[span.start : span.end] = b"\x01" * (span.end - span.start)
        if any(
            not char.isspace() and not covered[index]
            for index, char in enumerate(document.body)
        ):
            raise RetrievalUnavailable(
                "검색 청크가 현재 문서 일부를 포함하지 않습니다."
            )
        if load_vectors:
            return list(zip(chunks, vectors, strict=True))
        return chunks

    def _assert_spec(self, connection):
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            row = connection.execute(
                "SELECT schema_version, spec_id, canonical_spec FROM index_spec WHERE singleton=1"
            ).fetchone()
        except sqlite3.Error as exc:
            raise RetrievalUnavailable("검색 색인 형식이 올바르지 않습니다.") from exc
        if (
            version != SCHEMA_VERSION
            or row is None
            or row["schema_version"] != SCHEMA_VERSION
            or row["spec_id"] != SPEC_ID
            or row["canonical_spec"] != CANONICAL_SPEC
        ):
            raise RetrievalUnavailable(
                "검색 색인 schema 또는 spec이 일치하지 않습니다."
            )

    @staticmethod
    def _validate_chunk_against_source(document, chunk):
        if not chunk.text.strip() or not chunk.embedding_header.strip():
            raise RetrievalUnavailable("검색 청크가 비어 있습니다.")
        for span in chunk.spans:
            if (
                span.start < 0
                or span.end <= span.start
                or span.end > len(document.body)
            ):
                raise RetrievalUnavailable("검색 청크 원문 위치가 올바르지 않습니다.")
        source_text = "\n".join(
            document.body[span.start : span.end] for span in chunk.spans
        )
        expected_embedding = embedding_input(chunk.embedding_header, "", source_text)
        if (
            source_text != chunk.text
            or expected_embedding != chunk.embedding_text
            or embedding_input_key(expected_embedding) != chunk.input_key
            or chunk.chunk_id
            != chunk_identifier(
                document.document_id,
                document.revision_id,
                chunk.ordinal,
                chunk.input_key,
            )
        ):
            raise RetrievalUnavailable("검색 청크가 원문과 일치하지 않습니다.")


def _vector_from_blob(blob):
    if not isinstance(blob, bytes) or len(blob) != VECTOR_DIMENSION * 4:
        raise RetrievalUnavailable("검색 벡터 차원이 올바르지 않습니다.")
    vector = np.frombuffer(blob, dtype="<f4").astype(np.float32, copy=True)
    if vector.shape != (VECTOR_DIMENSION,) or not np.isfinite(vector).all():
        raise RetrievalUnavailable("검색 벡터가 유한한 숫자가 아닙니다.")
    norm = float(np.linalg.norm(vector))
    if not np.isclose(norm, 1.0, rtol=1e-4, atol=1e-4):
        raise RetrievalUnavailable("검색 벡터가 정규화되지 않았습니다.")
    return vector


def _validated_matrix(vectors, *, rows):
    array = np.asarray(vectors, dtype=np.float32)
    if array.shape != (rows, VECTOR_DIMENSION) or not np.isfinite(array).all():
        raise RetrievalUnavailable("저장할 검색 벡터 형식이 올바르지 않습니다.")
    if rows and not np.allclose(
        np.linalg.norm(array, axis=1), 1.0, rtol=1e-4, atol=1e-4
    ):
        raise RetrievalUnavailable("저장할 검색 벡터가 정규화되지 않았습니다.")
    return array
