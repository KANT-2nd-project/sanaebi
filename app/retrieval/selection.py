"""Pure score selection and source-span evidence assembly."""

from __future__ import annotations

from app.retrieval.search import SearchPolicy
from app.retrieval.types import Evidence, SourceSpan


def rank_hits(current, scores, *, policy: SearchPolicy):
    ranked = sorted(
        range(len(current)),
        key=lambda index: (-float(scores[index]), current[index][0].chunk_id),
    )
    if policy.minimum_question_similarity_score is not None and (
        not ranked
        or float(scores[ranked[0]]) < policy.minimum_question_similarity_score
    ):
        return []
    if policy.top_k_chunks is not None:
        ranked = ranked[: policy.top_k_chunks]
    if policy.minimum_similarity_score is not None:
        ranked = [
            index
            for index in ranked
            if float(scores[index]) >= policy.minimum_similarity_score
        ]
    return [(current[index][0], float(scores[index])) for index in ranked]


def merge_hits(hits, snapshot):
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
            and spans_overlap(group["spans"], chunk.spans)
        ]
        if not overlapping:
            groups.append(_hit_group(chunk, score))
            continue

        merged = overlapping[0]
        merged["spans"] = union_spans(
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
            union_spans(group["spans"]),
            group,
        )
        for group in groups
    ]


def render_evidence(groups):
    """Render every selected group in full without evidence or context caps."""
    results = []
    for document, spans, group in groups:
        text = render_spans(document.body, spans)
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


def render_spans(body: str, spans: tuple[SourceSpan, ...]) -> str:
    return "\n".join(body[span.start : span.end] for span in spans)


def spans_overlap(left, right):
    left_body = tuple(span for span in left if span.kind != "table_header")
    right_body = tuple(span for span in right if span.kind != "table_header")
    return any(
        left_span.start < right_span.end and right_span.start < left_span.end
        for left_span in left_body
        for right_span in right_body
    )


def _hit_group(chunk, score):
    return {
        "document_id": chunk.document_id,
        "revision_id": chunk.revision_id,
        "spans": tuple(chunk.spans),
        "chunks": {chunk.chunk_id},
        "score": score,
    }


def union_spans(spans):
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
