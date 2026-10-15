"""Document chunking and write-side reconciliation for the vector index."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.retrieval.baseline_store import BaselineVectorStore
from app.retrieval.chunking import chunk_document
from app.retrieval.config import (
    RetrievalSpec,
    validate_runtime_spec,
)
from app.retrieval.repository import IndexRepository, _validated_matrix
from app.retrieval.types import RetrievalUnavailable


class RetrievalIndexer:
    """Build and reconcile index records; online retrieval stays read-only."""

    def __init__(
        self,
        repository: IndexRepository,
        embedder,
        baseline_path: str | Path | None = None,
        *,
        spec: RetrievalSpec | None = None,
    ):
        self.repository = repository
        self.embedder = embedder
        self.spec = repository.spec if spec is None else spec
        try:
            validate_runtime_spec(self.spec)
        except ValueError as exc:
            raise RetrievalUnavailable(str(exc)) from exc
        if self.spec != repository.spec:
            raise ValueError("retrieval indexer and repository specs must match")
        embedder_spec = getattr(embedder, "spec", None)
        if embedder_spec is not None and embedder_spec != self.spec:
            raise ValueError("retrieval indexer and embedder specs must match")
        self.baseline_vectors = BaselineVectorStore(baseline_path, spec=self.spec)

    def status(self, snapshot):
        return self.repository.status(snapshot)

    def reconcile(self, snapshot):
        before = self.status(snapshot)
        if before["ready"]:
            return before
        if self.embedder is None:
            raise RetrievalUnavailable("색인 작업에 로컬 임베딩 모델이 필요합니다.")
        self.repository.initialize_if_missing()

        for document in snapshot.documents:
            single_snapshot = type(snapshot)((document,))
            if self.repository.status(single_snapshot)["ready"]:
                continue
            splitter_tokenizer = getattr(self.embedder, "splitter_tokenizer", None)
            chunks = chunk_document(
                document,
                splitter_tokenizer
                if splitter_tokenizer is not None
                else self.embedder.tokenizer,
                spec=self.spec,
            )
            baseline_vectors = self.baseline_vectors.vectors_for(chunks)
            keys = [chunk.input_key for chunk in chunks]
            reusable = self.repository.reusable_vectors(keys)
            reusable.update(baseline_vectors)
            missing = [chunk for chunk in chunks if chunk.input_key not in reusable]
            newly_encoded = {}
            for start in range(0, len(missing), 8):
                batch = missing[start : start + 8]
                encoded = _validated_matrix(
                    self.embedder.encode_documents(
                        [chunk.embedding_text for chunk in batch]
                    ),
                    rows=len(batch),
                    dimension=self.spec.dimension,
                )
                for chunk, vector in zip(batch, encoded, strict=True):
                    newly_encoded[chunk.input_key] = vector
            vectors = np.asarray(
                [
                    reusable.get(chunk.input_key, newly_encoded.get(chunk.input_key))
                    for chunk in chunks
                ],
                dtype=np.float32,
            ).reshape((-1, self.spec.dimension))
            self.repository.store_documents(((document, chunks, vectors),))

        return self.status(snapshot)
