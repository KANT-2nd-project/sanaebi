"""Reconciliation and exact retrieval over one immutable document snapshot."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.retrieval.baseline import _connect_bundle
from app.retrieval.chunking import chunk_document, token_count
from app.retrieval.config import (
    RetrievalSpec,
    canonical_retrieval_spec,
    retrieval_spec_id,
)
from app.retrieval.embedding import _validate_vectors
from app.retrieval.repository import IndexRepository, _validated_matrix
from app.retrieval.search import (
    DEFAULT_SEARCH_CONFIG,
    SearchConfig,
    bm25_rank,
    reciprocal_rank_fusion,
    search_config_id,
    tokenize_terms,
)
from app.retrieval.types import (
    Evidence,
    RetrievalInputTooLong,
    RetrievalNotReady,
    RetrievalUnavailable,
    RetrievedContext,
    SourceSpan,
)

MAX_EVIDENCE_COUNT = 5
MAX_EVIDENCE_CHARS = 2_000
MAX_TOTAL_EVIDENCE_CHARS = 8_000


class RetrievalService:
    def __init__(
        self,
        repository: IndexRepository,
        embedder,
        baseline_path: str | Path | None = None,
        *,
        spec: RetrievalSpec | None = None,
        search_config: SearchConfig = DEFAULT_SEARCH_CONFIG,
    ):
        self.repository = repository
        self.embedder = embedder
        self.baseline_path = Path(baseline_path) if baseline_path is not None else None
        self.spec = repository.spec if spec is None else spec
        if self.spec != repository.spec:
            raise ValueError("retrieval service and repository specs must match")
        self.search_config = search_config
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
            chunks = chunk_document(document, self.embedder.tokenizer, spec=self.spec)
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
                spec_id=self.spec_id,
                evidence=(),
                candidate_count=0,
                selected_count=0,
                observed_at=datetime.now(UTC),
                candidate_chunk_ids=(),
                search_config_id=search_config_id(self.search_config),
            )

        query = _validated_matrix(self.embedder.encode_queries([question]), rows=1)[0]
        current = self.repository.current_chunks(snapshot)
        if not current:
            raise RetrievalUnavailable("준비된 게시 문서에 검색 청크가 없습니다.")
        matrix = _validated_matrix(
            np.stack([vector for _, vector in current]), rows=len(current)
        )
        scores = matrix @ query
        vector_order = sorted(
            range(len(current)),
            key=lambda index: (-float(scores[index]), current[index][0].chunk_id),
        )
        chunk_by_id = {chunk.chunk_id: chunk for chunk, _ in current}
        if self.search_config.hybrid_search:
            vector_limit = min(len(vector_order), self.search_config.vector_pool)
            vector_hits = [
                (current[index][0].chunk_id, float(scores[index]))
                for index in vector_order[:vector_limit]
            ]
            document_terms = _bm25_document_terms(
                current, snapshot, self.embedder.tokenizer
            )
            query_terms = tokenize_terms(self.embedder.tokenizer, question)
            keyword_hits = bm25_rank(
                query_terms,
                document_terms,
                top_k=self.search_config.keyword_pool,
                k1=self.search_config.bm25_k1,
                b=self.search_config.bm25_b,
            )
            fused = reciprocal_rank_fusion(
                vector_hits,
                keyword_hits,
                limit=self.search_config.candidate_count,
                rrf_constant=self.search_config.rrf_constant,
            )
            hits = [(chunk_by_id[chunk_id], score) for chunk_id, score in fused]
        else:
            candidate_count = min(len(vector_order), self.search_config.candidate_count)
            hits = [
                (current[index][0], float(scores[index]))
                for index in vector_order[:candidate_count]
            ]
        candidate_chunk_ids = tuple(chunk.chunk_id for chunk, _ in hits)
        expanded_hits = (
            _expand_adjacent_hits(
                hits,
                [chunk for chunk, _ in current],
                self.search_config,
            )
            if self.search_config.expand_adjacent
            else hits
        )
        evidence_groups = _merge_hits(expanded_hits, snapshot)
        selected = _apply_budgets(evidence_groups, snapshot)
        return RetrievedContext(
            snapshot_fingerprint=snapshot.fingerprint,
            spec_id=self.spec_id,
            evidence=tuple(selected),
            candidate_count=len(hits),
            selected_count=len(selected),
            observed_at=datetime.now(UTC),
            candidate_chunk_ids=candidate_chunk_ids,
            search_config_id=search_config_id(self.search_config),
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
    for hit in hits:
        chunk, score, role, context_anchor_id = _unpack_hit(hit)
        overlapping = []
        for group in groups:
            if (
                group["document_id"] == chunk.document_id
                and group["revision_id"] == chunk.revision_id
                and (
                    _spans_overlap(group["spans"], chunk.spans)
                    or (
                        role == "expanded"
                        and context_anchor_id in group["anchor_chunks"]
                    )
                )
            ):
                overlapping.append(group)
        if not overlapping:
            groups.append(_hit_group(chunk, score, role, context_anchor_id))
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
            groups.append(_hit_group(chunk, score, role, context_anchor_id))
            continue

        merged = overlapping[0]
        merged["spans"] = merged_spans
        merged["chunks"].add(chunk.chunk_id)
        merged["hit_spans"][chunk.chunk_id] = tuple(chunk.spans)
        merged["hit_scores"][chunk.chunk_id] = score
        merged["hit_roles"][chunk.chunk_id] = role
        merged["hit_ordinals"][chunk.chunk_id] = chunk.ordinal
        if context_anchor_id is not None:
            merged["hit_parent_anchor"][chunk.chunk_id] = context_anchor_id
        if role == "anchor":
            merged["anchor_chunks"].add(chunk.chunk_id)
            merged["anchor_score"] = max(merged["anchor_score"], score)
        merged["score"] = max(merged["score"], score)
        for group in overlapping[1:]:
            merged["spans"] = _union_spans(merged["spans"] + tuple(group["spans"]))
            merged["chunks"].update(group["chunks"])
            merged["hit_spans"].update(group["hit_spans"])
            merged["hit_scores"].update(group["hit_scores"])
            merged["hit_roles"].update(group["hit_roles"])
            merged["hit_ordinals"].update(group["hit_ordinals"])
            merged["hit_parent_anchor"].update(group["hit_parent_anchor"])
            merged["anchor_chunks"].update(group["anchor_chunks"])
            merged["anchor_score"] = max(merged["anchor_score"], group["anchor_score"])
            merged["score"] = max(merged["score"], group["score"])
            groups.remove(group)

    groups.sort(
        key=lambda item: (
            not bool(item["anchor_chunks"]),
            -item["anchor_score"] if item["anchor_chunks"] else -item["score"],
            min(item["chunks"]),
        )
    )
    results = []
    for group in groups:
        document = by_revision[(group["document_id"], group["revision_id"])]
        results.append((document, _union_spans(group["spans"]), group))
    return results


def _unpack_hit(hit):
    if len(hit) == 2:
        chunk, score = hit
        return chunk, score, "anchor", None
    if len(hit) == 3:
        chunk, score, role = hit
        context_anchor_id = None
    else:
        chunk, score, role, context_anchor_id = hit
    if role not in {"anchor", "expanded"}:
        raise ValueError("unknown retrieval hit role")
    return chunk, score, role, context_anchor_id


def _expand_adjacent_hits(hits, current_chunks, search_config):
    """Add one source-order neighbor on each side while keeping anchors first."""
    by_position = {
        (chunk.document_id, chunk.revision_id, chunk.ordinal): chunk
        for chunk in current_chunks
    }
    anchor_ids = {chunk.chunk_id for chunk, _ in hits}
    ranked_anchors = [(chunk, score, "anchor", None) for chunk, score in hits]
    expanded = {}
    expanded_order = []
    if not search_config.expand_adjacent:
        return ranked_anchors

    for anchor, anchor_score in hits:
        for offset in (-1, 1):
            neighbor = by_position.get(
                (
                    anchor.document_id,
                    anchor.revision_id,
                    anchor.ordinal + offset,
                )
            )
            if neighbor is None or neighbor.chunk_id in anchor_ids:
                continue
            if not _same_parent_or_immediate_section(anchor, neighbor):
                continue
            previous = expanded.get(neighbor.chunk_id)
            if previous is None:
                expanded[neighbor.chunk_id] = (
                    neighbor,
                    anchor_score,
                    "expanded",
                    anchor.chunk_id,
                )
                expanded_order.append(neighbor.chunk_id)
            elif anchor_score > previous[1]:
                expanded[neighbor.chunk_id] = (
                    neighbor,
                    anchor_score,
                    "expanded",
                    anchor.chunk_id,
                )
    return ranked_anchors + [expanded[chunk_id] for chunk_id in expanded_order]


def _bm25_document_terms(current, snapshot, tokenizer):
    """Tokenize only source title, heading and chunk body for lexical search."""
    titles = {
        (document.document_id, document.revision_id): document.title
        for document in snapshot.documents
    }
    return {
        chunk.chunk_id: tokenize_terms(
            tokenizer,
            f"{titles[(chunk.document_id, chunk.revision_id)]}\n"
            f"{chunk.heading}\n{chunk.text}",
        )
        for chunk, _ in current
    }


def _same_parent_or_immediate_section(left, right):
    left_path = tuple(part.strip() for part in left.heading.split(">") if part.strip())
    right_path = tuple(
        part.strip() for part in right.heading.split(">") if part.strip()
    )
    if left_path == right_path:
        return True
    if left_path[:-1] == right_path[:-1] and left_path[:-1]:
        return True
    # The caller resolves only ordinal +/- 1 in the same document revision.
    # With no common parent, this is the narrow adjacent-section fallback.
    return (
        left.document_id == right.document_id
        and left.revision_id == right.revision_id
        and abs(left.ordinal - right.ordinal) == 1
    )


def _apply_budgets(groups, snapshot):
    # Select and reserve all original anchors against the global budget before
    # considering any optional neighbor text. Otherwise an expansion attached
    # to an early-ranked anchor can truncate a later direct match.
    anchor_groups = []
    for document, spans, group in groups:
        anchor_ids = group["anchor_chunks"]
        if not anchor_ids:
            continue
        anchor_group = _anchor_only_group(group, anchor_ids)
        anchor_spans = _union_spans(
            span for chunk_id in anchor_ids for span in group["hit_spans"][chunk_id]
        )
        anchor_groups.append((document, anchor_spans, anchor_group))
    anchor_groups.sort(
        key=lambda item: (
            -item[2]["anchor_score"],
            min(item[2]["anchor_chunks"]),
        )
    )

    remaining = MAX_TOTAL_EVIDENCE_CHARS
    selected = []
    for document, spans, group in anchor_groups:
        if len(selected) >= MAX_EVIDENCE_COUNT or remaining <= 0:
            break
        limit = min(MAX_EVIDENCE_CHARS, remaining)
        selected_spans = (
            spans
            if len(_render_spans(document.body, spans)) <= limit
            else _priority_bounded_spans(document.body, group, limit)
        )
        text = _render_spans(document.body, selected_spans)
        if not text.strip():
            continue
        contributing_chunks = _contributing_chunks(group, selected_spans)
        if not contributing_chunks:
            continue
        item = {
            "document": document,
            "spans": selected_spans,
            "text": text,
            "chunk_ids": list(contributing_chunks),
            "anchor_chunk_ids": set(contributing_chunks),
            "anchor_scores": {
                chunk_id: group["hit_scores"][chunk_id]
                for chunk_id in contributing_chunks
            },
            "expanded_chunk_ids": [],
            "score": max(
                group["hit_scores"][chunk_id] for chunk_id in contributing_chunks
            ),
        }
        selected.append(item)
        remaining -= len(text)

    if remaining <= 0:
        return [_evidence(item, rank) for rank, item in enumerate(selected, 1)]

    # Expansion hits can have been merged into an anchor group or kept in a
    # separate group when their combined text would exceed the per-item limit.
    # The parent mapping lets both shapes attach only to the intended selected
    # anchor, while all direct-anchor text has already reserved its share.
    expansions_by_anchor = {}
    for document, _, group in groups:
        for chunk_id, role in group["hit_roles"].items():
            parent_anchor = group["hit_parent_anchor"].get(chunk_id)
            if role != "expanded" or parent_anchor is None:
                continue
            expansions_by_anchor.setdefault(parent_anchor, []).append(
                (
                    document,
                    chunk_id,
                    group["hit_spans"][chunk_id],
                    group["hit_ordinals"][chunk_id],
                )
            )

    seen_expansions = set()
    for item in selected:
        document = item["document"]
        candidates = []
        ordered_anchor_ids = sorted(
            item["anchor_chunk_ids"],
            key=lambda chunk_id: (-item["anchor_scores"][chunk_id], chunk_id),
        )
        for anchor_id in ordered_anchor_ids:
            candidates.extend(
                sorted(
                    expansions_by_anchor.get(anchor_id, ()),
                    key=lambda candidate: (candidate[3], candidate[1]),
                )
            )
        for expansion_document, chunk_id, hit_spans, _ in candidates:
            key = (document.document_id, document.revision_id, chunk_id)
            if key in seen_expansions:
                continue
            seen_expansions.add(key)
            if (
                expansion_document.document_id != document.document_id
                or expansion_document.revision_id != document.revision_id
            ):
                continue

            original_spans = item["spans"]
            original_body = tuple(
                span for span in original_spans if span.kind != "table_header"
            )
            updated_spans = original_spans
            evidence_limit = min(MAX_EVIDENCE_CHARS, len(item["text"]) + remaining)
            for span in hit_spans:
                if span.kind != "table_header":
                    updated_spans = _add_bounded_span(
                        document.body, updated_spans, span, evidence_limit
                    )
            updated_body = tuple(
                span for span in updated_spans if span.kind != "table_header"
            )
            body_added = len(_render_spans(document.body, updated_body)) - len(
                _render_spans(document.body, original_body)
            )
            if body_added <= 0:
                continue

            for span in hit_spans:
                if span.kind == "table_header":
                    updated_spans = _add_bounded_span(
                        document.body, updated_spans, span, evidence_limit
                    )
            updated_text = _render_spans(document.body, updated_spans)
            added_chars = len(updated_text) - len(item["text"])
            if added_chars <= 0:
                continue

            item["spans"] = updated_spans
            item["text"] = updated_text
            item["chunk_ids"].append(chunk_id)
            item["expanded_chunk_ids"].append(chunk_id)
            remaining -= added_chars
            if remaining <= 0:
                break

    return [_evidence(item, rank) for rank, item in enumerate(selected, 1)]


def _anchor_only_group(group, anchor_ids):
    hit_spans = {chunk_id: group["hit_spans"][chunk_id] for chunk_id in anchor_ids}
    hit_scores = {chunk_id: group["hit_scores"][chunk_id] for chunk_id in anchor_ids}
    return {
        "hit_spans": hit_spans,
        "hit_scores": hit_scores,
        "hit_roles": {chunk_id: "anchor" for chunk_id in anchor_ids},
        "anchor_chunks": set(anchor_ids),
        "anchor_score": max(hit_scores.values()),
    }


def _contributing_chunks(group, spans):
    selected_body = tuple(span for span in spans if span.kind != "table_header")
    return tuple(
        sorted(
            chunk_id
            for chunk_id, hit_spans in group["hit_spans"].items()
            if _spans_overlap(
                tuple(span for span in hit_spans if span.kind != "table_header"),
                selected_body,
            )
        )
    )


def _evidence(item, rank):
    document = item["document"]
    return Evidence(
        knowledge_id=document.knowledge_id,
        document_id=document.document_id,
        revision_id=document.revision_id,
        revision=document.revision,
        title=document.title,
        text=item["text"],
        source_reference=document.source_reference,
        spans=item["spans"],
        chunk_ids=tuple(item["chunk_ids"]),
        score=item["score"],
        rank=rank,
        expanded_chunk_ids=tuple(item["expanded_chunk_ids"]),
    )


def _priority_bounded_spans(body: str, group, budget: int):
    """Keep higher-scoring body spans when a group must be clipped to budget."""
    selected = ()
    ordered_hits = sorted(
        group["hit_spans"].items(),
        key=lambda item: (
            group["hit_roles"].get(item[0]) != "anchor",
            -group["hit_scores"][item[0]],
            item[0],
        ),
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


def _hit_group(chunk, score, role="anchor", context_anchor_id=None):
    return {
        "document_id": chunk.document_id,
        "revision_id": chunk.revision_id,
        "spans": tuple(chunk.spans),
        "chunks": {chunk.chunk_id},
        "hit_spans": {chunk.chunk_id: tuple(chunk.spans)},
        "hit_scores": {chunk.chunk_id: score},
        "hit_roles": {chunk.chunk_id: role},
        "hit_ordinals": {chunk.chunk_id: chunk.ordinal},
        "hit_parent_anchor": (
            {chunk.chunk_id: context_anchor_id} if context_anchor_id is not None else {}
        ),
        "anchor_chunks": {chunk.chunk_id} if role == "anchor" else set(),
        "anchor_score": score if role == "anchor" else float("-inf"),
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
