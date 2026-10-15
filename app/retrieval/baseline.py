"""Immutable vectors for restoring the published company-document baseline."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.retrieval.chunking import (
    chunk_document,
    chunk_identifier,
    embedding_input,
    embedding_input_key,
)
from app.retrieval.config import CANONICAL_SPEC, SPEC_ID
from app.retrieval.repository import (
    IndexRepository,
    _validated_matrix,
    _vector_from_blob,
    document_digest,
)
from app.retrieval.types import Chunk, RetrievalUnavailable, SourceSpan

ARTIFACT_SCHEMA_VERSION = 1
_BUNDLE_SCHEMA = """
CREATE TABLE bundle_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    artifact_schema_version INTEGER NOT NULL,
    spec_id TEXT NOT NULL,
    canonical_spec TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_document_count INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE baseline_documents (
    source_document_id TEXT PRIMARY KEY,
    title_body_digest TEXT NOT NULL,
    expected_chunk_count INTEGER NOT NULL CHECK(expected_chunk_count >= 0)
);
CREATE TABLE baseline_chunks (
    source_document_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    spans_json TEXT NOT NULL,
    heading TEXT NOT NULL,
    embedding_header TEXT NOT NULL,
    input_key TEXT NOT NULL,
    vector_blob BLOB NOT NULL,
    PRIMARY KEY(source_document_id, ordinal),
    FOREIGN KEY(source_document_id)
        REFERENCES baseline_documents(source_document_id) ON DELETE CASCADE
);
CREATE INDEX baseline_chunks_input_key ON baseline_chunks(input_key);
"""


def prepare_baseline(
    source_path: str | Path, output_root: str | Path, embedder
) -> Path:
    """Build a source-bound immutable bundle and publish it without overwriting."""
    source_path = Path(source_path)
    source_raw, rows = _read_source(source_path)
    source_sha = hashlib.sha256(source_raw).hexdigest()
    target_dir = Path(output_root) / "schema-v1" / SPEC_ID / source_sha
    target = target_dir / "baseline.sqlite3"
    target_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        validate_baseline(target, source_path)
        return target
    if embedder is None:
        raise RetrievalUnavailable("기본 벡터를 만들 로컬 임베딩 모델이 없습니다.")

    staged = target_dir / f".baseline.{uuid.uuid4().hex}.tmp"
    try:
        prepared = []
        for row in rows:
            document = SimpleNamespace(
                document_id=row["document_id"],
                knowledge_id=row["document_id"],
                revision_id="baseline-artifact",
                revision=1,
                title=row["title"],
                body=row["document"],
                source_reference=f"document:{row['document_id']}",
            )
            chunks = chunk_document(document, embedder.tokenizer)
            if row["document"].strip() and not chunks:
                raise RetrievalUnavailable(
                    "기본 문서에서 검색 청크를 만들지 못했습니다."
                )
            prepared.append((row, document, chunks))

        all_chunks = [chunk for _, _, chunks in prepared for chunk in chunks]
        vectors = []
        for start in range(0, len(all_chunks), 8):
            batch = all_chunks[start : start + 8]
            vectors.extend(
                embedder.encode_documents([chunk.embedding_text for chunk in batch])
            )
        matrix = _validated_matrix(
            np.asarray(vectors, dtype=np.float32).reshape((-1, 384)),
            rows=len(all_chunks),
        )

        connection = sqlite3.connect(staged, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_BUNDLE_SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO bundle_metadata VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ARTIFACT_SCHEMA_VERSION,
                    SPEC_ID,
                    CANONICAL_SPEC,
                    source_sha,
                    len(rows),
                    len(all_chunks),
                    datetime.now(UTC).isoformat(),
                ),
            )
            offset = 0
            for row, document, chunks in prepared:
                connection.execute(
                    "INSERT INTO baseline_documents VALUES (?, ?, ?)",
                    (
                        row["document_id"],
                        document_digest(document.title, document.body),
                        len(chunks),
                    ),
                )
                for chunk, vector in zip(
                    chunks, matrix[offset : offset + len(chunks)], strict=True
                ):
                    connection.execute(
                        """INSERT INTO baseline_chunks
                           (source_document_id, ordinal, spans_json, heading,
                            embedding_header, input_key, vector_blob)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["document_id"],
                            chunk.ordinal,
                            _spans_json(chunk.spans),
                            chunk.heading,
                            chunk.embedding_header,
                            chunk.input_key,
                            np.asarray(vector, dtype="<f4").tobytes(),
                        ),
                    )
                offset += len(chunks)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

        validate_baseline(staged, source_path)
        try:
            os.link(staged, target)
        except FileExistsError:
            validate_baseline(target, source_path)
        staged.unlink(missing_ok=True)
        return target
    except RetrievalUnavailable:
        staged.unlink(missing_ok=True)
        raise
    except Exception as exc:
        staged.unlink(missing_ok=True)
        raise RetrievalUnavailable("기본 벡터 묶음을 준비하지 못했습니다.") from exc


def validate_baseline(bundle_path: str | Path, source_path: str | Path) -> dict:
    """Verify source identity, spec, spans, complete chunk counts and vectors."""
    source_raw, source_rows = _read_source(Path(source_path))
    source_sha = hashlib.sha256(source_raw).hexdigest()
    connection = _connect_bundle(Path(bundle_path))
    try:
        metadata = connection.execute(
            "SELECT * FROM bundle_metadata WHERE singleton=1"
        ).fetchone()
        if metadata is None or (
            metadata["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION
            or metadata["spec_id"] != SPEC_ID
            or metadata["canonical_spec"] != CANONICAL_SPEC
            or metadata["source_sha256"] != source_sha
            or metadata["source_document_count"] != len(source_rows)
        ):
            raise RetrievalUnavailable(
                "기본 벡터 묶음의 source 또는 spec이 일치하지 않습니다."
            )
        document_rows = connection.execute(
            "SELECT * FROM baseline_documents"
        ).fetchall()
        by_id = {row["source_document_id"]: row for row in document_rows}
        if len(by_id) != len(source_rows) or set(by_id) != {
            row["document_id"] for row in source_rows
        }:
            raise RetrievalUnavailable(
                "기본 벡터 묶음의 문서 목록이 완전하지 않습니다."
            )

        total_chunks = 0
        for source_row in source_rows:
            document_id = source_row["document_id"]
            stored_doc = by_id[document_id]
            digest = document_digest(source_row["title"], source_row["document"])
            if stored_doc["title_body_digest"] != digest:
                raise RetrievalUnavailable(
                    "기본 벡터 묶음의 문서 내용이 source와 다릅니다."
                )
            chunks = connection.execute(
                "SELECT * FROM baseline_chunks WHERE source_document_id=? ORDER BY ordinal",
                (document_id,),
            ).fetchall()
            if len(chunks) != stored_doc["expected_chunk_count"]:
                raise RetrievalUnavailable(
                    "기본 벡터 묶음의 청크 수가 일치하지 않습니다."
                )
            if [row["ordinal"] for row in chunks] != list(range(len(chunks))):
                raise RetrievalUnavailable(
                    "기본 벡터 묶음의 청크 순서가 올바르지 않습니다."
                )
            _validate_bundle_chunks(source_row["title"], source_row["document"], chunks)
            total_chunks += len(chunks)
        if total_chunks != metadata["chunk_count"]:
            raise RetrievalUnavailable(
                "기본 벡터 묶음의 전체 청크 수가 일치하지 않습니다."
            )
        return {
            "valid": True,
            "source_sha256": source_sha,
            "spec_id": SPEC_ID,
            "source_document_count": len(source_rows),
            "chunk_count": total_chunks,
        }
    except RetrievalUnavailable:
        raise
    except (sqlite3.Error, OSError, TypeError, KeyError, ValueError) as exc:
        raise RetrievalUnavailable(
            "기본 벡터 묶음이 손상됐거나 읽을 수 없습니다."
        ) from exc
    finally:
        connection.close()


def restore_baseline(
    repository: IndexRepository,
    bundle_path: str | Path,
    source_path: str | Path,
    snapshot,
) -> dict:
    """Map precomputed vectors onto current revision IDs without loading a model."""
    validate_baseline(bundle_path, source_path)
    source_rows = {
        row["document_id"]: row for row in _read_source(Path(source_path))[1]
    }
    connection = _connect_bundle(Path(bundle_path))
    records = []
    try:
        for document in snapshot.documents:
            source = source_rows.get(document.knowledge_id)
            if source is None:
                continue
            if document_digest(document.title, document.body) != document_digest(
                source["title"], source["document"]
            ):
                continue
            rows = connection.execute(
                "SELECT * FROM baseline_chunks WHERE source_document_id=? ORDER BY ordinal",
                (document.knowledge_id,),
            ).fetchall()
            chunks = []
            vectors = []
            for row in rows:
                spans = _read_spans(row["spans_json"])
                text = "\n".join(document.body[span.start : span.end] for span in spans)
                embedding_text = embedding_input(row["embedding_header"], "", text)
                if embedding_input_key(embedding_text) != row["input_key"]:
                    raise RetrievalUnavailable(
                        "기본 벡터 입력이 source와 일치하지 않습니다."
                    )
                chunks.append(
                    Chunk(
                        document_id=document.document_id,
                        revision_id=document.revision_id,
                        ordinal=row["ordinal"],
                        spans=spans,
                        heading=row["heading"],
                        embedding_header=row["embedding_header"],
                        text=text,
                        embedding_text=embedding_text,
                        input_key=row["input_key"],
                        chunk_id=chunk_identifier(
                            document.document_id,
                            document.revision_id,
                            row["ordinal"],
                            row["input_key"],
                        ),
                    )
                )
                vectors.append(_vector_from_blob(row["vector_blob"]))
            records.append(
                (
                    document,
                    tuple(chunks),
                    np.asarray(vectors, dtype=np.float32).reshape((-1, 384)),
                )
            )
    except RetrievalUnavailable:
        raise
    except (sqlite3.Error, OSError, TypeError, KeyError, ValueError) as exc:
        raise RetrievalUnavailable("기본 벡터 연결 자료를 읽을 수 없습니다.") from exc
    finally:
        connection.close()

    if records:
        repository.store_documents(records)
    return repository.status(snapshot)


def _read_source(path: Path):
    try:
        raw = path.read_bytes()
        rows = []
        seen = set()
        for line_number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"invalid row {line_number}")
            for key in ("document_id", "title", "document"):
                if not isinstance(value.get(key), str) or not value[key].strip():
                    raise ValueError(f"invalid field {line_number}")
            if value["document_id"] in seen:
                raise ValueError("duplicate source document id")
            seen.add(value["document_id"])
            rows.append(value)
        if not rows:
            raise ValueError("empty source")
        return raw, rows
    except RetrievalUnavailable:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RetrievalUnavailable("회사 문서 기본 원본을 읽을 수 없습니다.") from exc


def _connect_bundle(path: Path):
    if not path.is_file():
        raise RetrievalUnavailable("기본 벡터 묶음이 없습니다.")
    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=1,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    except (sqlite3.Error, OSError) as exc:
        raise RetrievalUnavailable("기본 벡터 묶음을 열 수 없습니다.") from exc


def _validate_bundle_chunks(title, body, rows):
    covered = bytearray(len(body))
    for row in rows:
        spans = _read_spans(row["spans_json"])
        if not spans:
            raise RetrievalUnavailable("기본 벡터 청크에 원문 위치가 없습니다.")
        for span in spans:
            if span.start < 0 or span.end <= span.start or span.end > len(body):
                raise RetrievalUnavailable(
                    "기본 벡터 청크 위치가 원문 범위를 벗어납니다."
                )
            covered[span.start : span.end] = b"\x01" * (span.end - span.start)
        text = "\n".join(body[span.start : span.end] for span in spans)
        embedding_text = embedding_input(row["embedding_header"], "", text)
        if embedding_input_key(embedding_text) != row["input_key"]:
            raise RetrievalUnavailable("기본 벡터 입력 식별값이 일치하지 않습니다.")
        if not row["embedding_header"].strip():
            raise RetrievalUnavailable("기본 벡터 청크의 임베딩 헤더가 비었습니다.")
        _vector_from_blob(row["vector_blob"])
    if any(
        not char.isspace() and not covered[index] for index, char in enumerate(body)
    ):
        raise RetrievalUnavailable("기본 벡터 청크가 원문 일부를 누락했습니다.")


def _read_spans(encoded):
    try:
        rows = json.loads(encoded)
        return tuple(
            SourceSpan(int(item["start"]), int(item["end"]), str(item["kind"]))
            for item in rows
        )
    except (TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RetrievalUnavailable("기본 벡터 청크 위치 정보가 손상됐습니다.") from exc


def _spans_json(spans):
    return json.dumps(
        [{"start": span.start, "end": span.end, "kind": span.kind} for span in spans],
        separators=(",", ":"),
    )
