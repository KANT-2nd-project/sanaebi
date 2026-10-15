"""Reconciliation and exact retrieval over one immutable document snapshot."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.retrieval.baseline import _connect_bundle
from app.retrieval.chunking import chunk_document, token_count
from app.retrieval.config import (
    DEFAULT_SPEC,
    KURE_SPEC,
    RetrievalSpec,
    canonical_retrieval_spec,
    retrieval_spec_id,
)
from app.retrieval.embedding import _validate_vectors
from app.retrieval.repository import IndexRepository, _validated_matrix
from app.retrieval.search import (
    KURE_MINIMUM_SIMILARITY_SCORE,
    KURE_TOP_K,
    MINIMUM_SIMILARITY_SCORE,
    search_config_id,
)
from app.retrieval.types import (
    Evidence,
    RetrievalInputTooLong,
    RetrievalNotReady,
    RetrievalUnavailable,
    RetrievedContext,
    SourceSpan,
)


class RetrievalService:
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
        self.baseline_path = Path(baseline_path) if baseline_path is not None else None
        self.spec = repository.spec if spec is None else spec
        if self.spec != repository.spec:
            raise ValueError("retrieval service and repository specs must match")
        embedder_spec = getattr(embedder, "spec", None)
        if embedder_spec is not None and embedder_spec != self.spec:
            raise ValueError("retrieval service and embedder specs must match")
        self.spec_id = retrieval_spec_id(self.spec)
        self.canonical_spec = canonical_retrieval_spec(self.spec)

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
            baseline_vectors = self._baseline_vectors(chunks)
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

    def retrieve(self, question: str, snapshot) -> RetrievedContext:
        if self.embedder is None:
            raise RetrievalUnavailable("검색 임베딩 모델을 사용할 수 없습니다.")
        if not isinstance(question, str):
            raise TypeError("검색 질문은 문자열이어야 합니다.")
        query_input = f"{self.spec.query_prefix}{question}"
        if (
            token_count(self.embedder.tokenizer, query_input, special_tokens=True)
            > self.spec.max_query_tokens
        ):
            raise RetrievalInputTooLong(
                "검색 질문이 임베딩 모델의 길이 제한을 넘습니다."
            )
        status = self.status(snapshot)
        if not status["ready"]:
            raise RetrievalNotReady("현재 게시 문서의 검색 색인이 준비되지 않았습니다.")
        if not snapshot.documents:
            return RetrievedContext(
                snapshot_fingerprint=snapshot.fingerprint,
                spec_id=self.spec_id,
                evidence=(),
                candidate_count=0,
                selected_count=0,
                observed_at=datetime.now(UTC),
                candidate_chunk_ids=(),
                search_config_id=search_config_id(self.spec),
            )

        query = _validated_matrix(
            self.embedder.encode_queries([question]),
            rows=1,
            dimension=self.spec.dimension,
        )[0]
        current = self.repository.current_chunks(snapshot)
        if not current:
            raise RetrievalUnavailable("준비된 게시 문서에 검색 청크가 없습니다.")
        matrix = _validated_matrix(
            np.stack([vector for _, vector in current]),
            rows=len(current),
            dimension=self.spec.dimension,
        )
        scores = matrix @ query
        hits = _ranked_hits(current, scores, spec=self.spec)
        candidate_chunk_ids = tuple(chunk.chunk_id for chunk, _ in hits)
        evidence_groups = _merge_hits(hits, snapshot)
        selected = _render_evidence(evidence_groups)
        return RetrievedContext(
            snapshot_fingerprint=snapshot.fingerprint,
            spec_id=self.spec_id,
            evidence=tuple(selected),
            candidate_count=len(hits),
            selected_count=len(selected),
            observed_at=datetime.now(UTC),
            candidate_chunk_ids=candidate_chunk_ids,
            search_config_id=search_config_id(self.spec),
        )

    def _baseline_vectors(self, chunks):
        if self.baseline_path is None or not chunks or not self.baseline_path.is_file():
            return {}
        try:
            connection = _connect_bundle(self.baseline_path)
            try:
                metadata = connection.execute(
                    "SELECT artifact_schema_version, spec_id, canonical_spec FROM bundle_metadata WHERE singleton=1"
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
                    f"SELECT input_key, vector_blob FROM baseline_chunks WHERE input_key IN ({placeholders}) ORDER BY source_document_id, ordinal",
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
            # The ordinary worker may still calculate missing vectors. The reset
            # path validates the bundle separately and must fail closed.
            return {}


def _ranked_hits(current, scores, *, spec=DEFAULT_SPEC):
    """Apply the active profile's fixed selection contract to ranked vectors."""
    ranked = sorted(
        range(len(current)),
        key=lambda index: (-float(scores[index]), current[index][0].chunk_id),
    )
    if spec == KURE_SPEC:
        if not ranked or float(scores[ranked[0]]) < KURE_MINIMUM_SIMILARITY_SCORE:
            return []
        ranked = ranked[:KURE_TOP_K]
        return [(current[index][0], float(scores[index])) for index in ranked]
    return [
        (current[index][0], float(scores[index]))
        for index in ranked
        if float(scores[index]) >= MINIMUM_SIMILARITY_SCORE
    ]


def _merge_hits(hits, snapshot):
    """Merge overlapping source spans from same-revision vector hits."""
    by_revision = {
        (document.document_id, document.revision_id): document
        for document in snapshot.documents
    }
    groups = []
    for chunk, score in hits:
        overlapping = [
            group
            for group in groups
            if group["document_id"] == chunk.document_id
            and group["revision_id"] == chunk.revision_id
            and _spans_overlap(group["spans"], chunk.spans)
        ]
        if not overlapping:
            groups.append(_hit_group(chunk, score))
            continue

        merged = overlapping[0]
        merged["spans"] = _union_spans(
            tuple(merged["spans"])
            + tuple(chunk.spans)
            + tuple(span for group in overlapping[1:] for span in group["spans"])
        )
        merged["chunks"].add(chunk.chunk_id)
        merged["score"] = max(merged["score"], score)
        for group in overlapping[1:]:
            merged["chunks"].update(group["chunks"])
            merged["score"] = max(merged["score"], group["score"])
            groups.remove(group)

    groups.sort(key=lambda item: (-item["score"], min(item["chunks"])))
    return [
        (
            by_revision[(group["document_id"], group["revision_id"])],
            _union_spans(group["spans"]),
            group,
        )
        for group in groups
    ]


def _render_evidence(groups):
    """Render every selected group in full without evidence or context caps."""
    results = []
    for document, spans, group in groups:
        text = _render_spans(document.body, spans)
        if not text.strip():
            continue
        results.append(
            Evidence(
                knowledge_id=document.knowledge_id,
                document_id=document.document_id,
                revision_id=document.revision_id,
                revision=document.revision,
                title=document.title,
                text=text,
                source_reference=document.source_reference,
                spans=spans,
                chunk_ids=tuple(sorted(group["chunks"])),
                score=group["score"],
                rank=len(results) + 1,
            )
        )
    return results


def _render_spans(body: str, spans: tuple[SourceSpan, ...]) -> str:
    return "\n".join(body[span.start : span.end] for span in spans)


def _spans_overlap(left, right):
    left_body = tuple(span for span in left if span.kind != "table_header")
    right_body = tuple(span for span in right if span.kind != "table_header")
    return any(
        a.start < b.end and b.start < a.end for a in left_body for b in right_body
    )


def _hit_group(chunk, score):
    return {
        "document_id": chunk.document_id,
        "revision_id": chunk.revision_id,
        "spans": tuple(chunk.spans),
        "chunks": {chunk.chunk_id},
        "score": score,
    }


def _union_spans(spans):
    ordered = sorted(spans, key=lambda span: (span.start, span.end, span.kind))
    merged = []
    for span in ordered:
        if merged and span.start < merged[-1].end:
            previous = merged[-1]
            merged[-1] = SourceSpan(
                previous.start,
                max(previous.end, span.end),
                previous.kind if previous.kind == span.kind else "body",
            )
        else:
            merged.append(span)
    return tuple(merged)
