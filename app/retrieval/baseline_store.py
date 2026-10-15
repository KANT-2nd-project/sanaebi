"""Read immutable baseline vectors for reuse during index reconciliation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from app.retrieval.baseline import _connect_bundle
from app.retrieval.config import (
    RetrievalSpec,
    canonical_retrieval_spec,
    retrieval_spec_id,
)
from app.retrieval.embedding import _validate_vectors
from app.retrieval.types import RetrievalUnavailable


class BaselineVectorStore:
    """Read-only lookup of vectors matching a selected retrieval spec."""

    def __init__(self, path: str | Path | None, *, spec: RetrievalSpec):
        self.path = Path(path) if path is not None else None
        self.spec = spec
        self.spec_id = retrieval_spec_id(spec)
        self.canonical_spec = canonical_retrieval_spec(spec)

    def vectors_for(self, chunks):
        if self.path is None or not chunks or not self.path.is_file():
            return {}
        try:
            connection = _connect_bundle(self.path)
            try:
                metadata = connection.execute(
                    "SELECT artifact_schema_version, spec_id, canonical_spec "
                    "FROM bundle_metadata WHERE singleton=1"
                ).fetchone()
                if (
                    metadata is None
                    or metadata["artifact_schema_version"] != 1
                    or metadata["spec_id"] != self.spec_id
                    or metadata["canonical_spec"] != self.canonical_spec
                ):
                    raise RetrievalUnavailable(
                        "기본 벡터 묶음 spec이 일치하지 않습니다."
                    )
                keys = tuple(dict.fromkeys(chunk.input_key for chunk in chunks))
                placeholders = ",".join("?" for _ in keys)
                rows = connection.execute(
                    "SELECT input_key, vector_blob FROM baseline_chunks "
                    f"WHERE input_key IN ({placeholders}) "
                    "ORDER BY source_document_id, ordinal",
                    keys,
                ).fetchall()
                result = {}
                for row in rows:
                    vector = np.frombuffer(row["vector_blob"], dtype="<f4").astype(
                        np.float32, copy=True
                    )
                    _validate_vectors(
                        vector.reshape((1, -1)),
                        expected_rows=1,
                        dimension=self.spec.dimension,
                    )
                    result.setdefault(row["input_key"], vector)
                return result
            finally:
                connection.close()
        except (RetrievalUnavailable, sqlite3.Error, OSError, TypeError, ValueError):
            # An invalid optional bundle only disables vector reuse; ordinary
            # indexing still computes the missing vectors. Reset validates it
            # separately and fails closed.
            return {}
