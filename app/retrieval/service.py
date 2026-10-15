"""Reconciliation and exact retrieval over one immutable document snapshot."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.retrieval.baseline import _connect_bundle
from app.retrieval.chunking import chunk_document, token_count
from app.retrieval.config import CANONICAL_SPEC, SPEC_ID
from app.retrieval.embedding import _validate_vectors
from app.retrieval.repository import IndexRepository, _validated_matrix
from app.retrieval.types import (
    Evidence,
    RetrievalInputTooLong,
    RetrievalNotReady,
    RetrievalUnavailable,
    RetrievedContext,
    SourceSpan,
)

CANDIDATE_COUNT = 10
MAX_EVIDENCE_COUNT = 5
MAX_EVIDENCE_CHARS = 2_000
MAX_TOTAL_EVIDENCE_CHARS = 8_000


class RetrievalService:
    def __init__(
        self,
        repository: IndexRepository,
        embedder,
        baseline_path: str | Path | None = None,
    ):
        self.repository = repository
        self.embedder = embedder
        self.baseline_path = Path(baseline_path) if baseline_path is not None else None

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
            chunks = chunk_document(document, self.embedder.tokenizer)
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
                )
                for chunk, vector in zip(batch, encoded, strict=True):
                    newly_encoded[chunk.input_key] = vector
            vectors = np.asarray(
                [
                    reusable.get(chunk.input_key, newly_encoded.get(chunk.input_key))
                    for chunk in chunks
                ],
                dtype=np.float32,
            ).reshape((-1, 384))
            self.repository.store_documents(((document, chunks, vectors),))

        return self.status(snapshot)

    def retrieve(self, question: str, snapshot) -> RetrievedContext:
        if self.embedder is None:
            raise RetrievalUnavailable("검색 임베딩 모델을 사용할 수 없습니다.")
        if not isinstance(question, str):
            raise TypeError("검색 질문은 문자열이어야 합니다.")
        query_input = f"query: {question}"
        if token_count(self.embedder.tokenizer, query_input, special_tokens=True) > 512:
            raise RetrievalInputTooLong(
                "검색 질문이 임베딩 모델의 길이 제한을 넘습니다."
            )
        status = self.status(snapshot)
        if not status["ready"]:
            raise RetrievalNotReady("현재 게시 문서의 검색 색인이 준비되지 않았습니다.")
        if not snapshot.documents:
            return RetrievedContext(
                snapshot_fingerprint=snapshot.fingerprint,
                spec_id=SPEC_ID,
                evidence=(),
                candidate_count=0,
                selected_count=0,
                observed_at=datetime.now(UTC),
            )

        query = _validated_matrix(self.embedder.encode_queries([question]), rows=1)[0]
        current = self.repository.current_chunks(snapshot)
        if not current:
            raise RetrievalUnavailable("준비된 게시 문서에 검색 청크가 없습니다.")
        matrix = _validated_matrix(
            np.stack([vector for _, vector in current]), rows=len(current)
        )
        scores = matrix @ query
        order = sorted(
            range(len(current)),
            key=lambda index: (-float(scores[index]), current[index][0].chunk_id),
        )[:CANDIDATE_COUNT]
        hits = [(current[index][0], float(scores[index])) for index in order]
        evidence_groups = _merge_hits(hits, snapshot)
        selected = _apply_budgets(evidence_groups, snapshot)
        return RetrievedContext(
            snapshot_fingerprint=snapshot.fingerprint,
            spec_id=SPEC_ID,
            evidence=tuple(selected),
            candidate_count=len(hits),
            selected_count=len(selected),
            observed_at=datetime.now(UTC),
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
                    or metadata["spec_id"] != SPEC_ID
                    or metadata["canonical_spec"] != CANONICAL_SPEC
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
                    _validate_vectors(vector.reshape((1, -1)), expected_rows=1)
                    result.setdefault(row["input_key"], vector)
                return result
            finally:
                connection.close()
        except (RetrievalUnavailable, sqlite3.Error, OSError, TypeError, ValueError):
            # The ordinary worker may still calculate missing vectors. The reset
            # path validates the bundle separately and must fail closed.
            return {}


def _merge_hits(hits, snapshot):
    by_revision = {
        (document.document_id, document.revision_id): document
        for document in snapshot.documents
    }
    groups = []
    for chunk, score in hits:
        overlapping = []
        for group in groups:
            if (
                group["document_id"] == chunk.document_id
                and group["revision_id"] == chunk.revision_id
                and _spans_overlap(group["spans"], chunk.spans)
            ):
                overlapping.append(group)
        if not overlapping:
            groups.append(_hit_group(chunk, score))
            continue

        merged_spans = _union_spans(
            tuple(chunk.spans)
            + tuple(span for group in overlapping for span in group["spans"])
        )
        document = by_revision[(chunk.document_id, chunk.revision_id)]
        # Merge overlap only while it remains a useful single evidence item.
        # Otherwise keep the ranked chunks separate so an early source span
        # cannot consume the budget and hide a later, higher-scoring match.
        if len(_render_spans(document.body, merged_spans)) > MAX_EVIDENCE_CHARS:
            groups.append(_hit_group(chunk, score))
            continue

        merged = overlapping[0]
        merged["spans"] = merged_spans
        merged["chunks"].add(chunk.chunk_id)
        merged["hit_spans"][chunk.chunk_id] = tuple(chunk.spans)
        merged["hit_scores"][chunk.chunk_id] = score
        merged["score"] = max(merged["score"], score)
        for group in overlapping[1:]:
            merged["spans"] = _union_spans(merged["spans"] + tuple(group["spans"]))
            merged["chunks"].update(group["chunks"])
            merged["hit_spans"].update(group["hit_spans"])
            merged["hit_scores"].update(group["hit_scores"])
            merged["score"] = max(merged["score"], group["score"])
            groups.remove(group)

    groups.sort(key=lambda item: (-item["score"], min(item["chunks"])))
    results = []
    for group in groups:
        document = by_revision[(group["document_id"], group["revision_id"])]
        results.append((document, _union_spans(group["spans"]), group))
    return results


def _apply_budgets(groups, snapshot):
    remaining = MAX_TOTAL_EVIDENCE_CHARS
    selected = []
    for rank, (document, spans, group) in enumerate(groups, 1):
        if len(selected) >= MAX_EVIDENCE_COUNT or remaining <= 0:
            break
        limit = min(MAX_EVIDENCE_CHARS, remaining)
        if len(_render_spans(document.body, spans)) <= limit:
            selected_spans = spans
        else:
            selected_spans = _priority_bounded_spans(document.body, group, limit)
        text = _render_spans(document.body, selected_spans)
        if not text.strip():
            continue
        contributing_chunks = tuple(
            sorted(
                chunk_id
                for chunk_id, hit_spans in group["hit_spans"].items()
                if _spans_overlap(
                    tuple(span for span in hit_spans if span.kind != "table_header"),
                    tuple(
                        span for span in selected_spans if span.kind != "table_header"
                    ),
                )
            )
        )
        if not contributing_chunks:
            continue
        selected.append(
            Evidence(
                knowledge_id=document.knowledge_id,
                document_id=document.document_id,
                revision_id=document.revision_id,
                revision=document.revision,
                title=document.title,
                text=text,
                source_reference=document.source_reference,
                spans=selected_spans,
                chunk_ids=contributing_chunks,
                score=max(
                    group["hit_scores"][chunk_id] for chunk_id in contributing_chunks
                ),
                rank=rank,
            )
        )
        remaining -= len(text)
    return selected


def _priority_bounded_spans(body: str, group, budget: int):
    """Keep higher-scoring body spans when a group must be clipped to budget."""
    selected = ()
    ordered_hits = sorted(
        group["hit_spans"].items(),
        key=lambda item: (-group["hit_scores"][item[0]], item[0]),
    )
    table_headers = []
    for _, hit_spans in ordered_hits:
        for span in hit_spans:
            if span.kind == "table_header":
                table_headers.append(span)
                continue
            selected = _add_bounded_span(body, selected, span, budget)

    # Table headers add context, but never displace a higher-ranked body span.
    for span in _union_spans(tuple(table_headers)):
        selected = _add_bounded_span(body, selected, span, budget)
    return _union_spans(selected)


def _add_bounded_span(body: str, selected, span: SourceSpan, budget: int):
    candidate = _union_spans(tuple(selected) + (span,))
    if len(_render_spans(body, candidate)) <= budget:
        return candidate

    # The full span does not fit. Add the largest prefix that leaves already
    # selected, higher-scoring text intact, accounting for separators and
    # overlaps through the same renderer used for the final evidence.
    low, high = span.start + 1, span.end
    best = selected
    while low <= high:
        end = (low + high) // 2
        clipped = SourceSpan(span.start, end, span.kind)
        candidate = _union_spans(tuple(selected) + (clipped,))
        if len(_render_spans(body, candidate)) <= budget:
            best = candidate
            low = end + 1
        else:
            high = end - 1
    return best


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
        "hit_spans": {chunk.chunk_id: tuple(chunk.spans)},
        "hit_scores": {chunk.chunk_id: score},
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
