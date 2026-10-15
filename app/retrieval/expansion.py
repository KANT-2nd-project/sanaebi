"""Add bounded source context to ranked retrieval evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from app.documents.context import DocumentContextSnapshot
from app.retrieval.types import Chunk, Evidence, SourceSpan

MAX_EXPANDED_DOCUMENTS = 3
WHOLE_DOCUMENT_MAX_CHARS = 4_000
MAX_ADDED_SOURCE_CHARS = 6_000


@dataclass
class _EvidenceGroup:
    items: list[Evidence]
    spans: tuple[SourceSpan, ...]
    original_chunk_ids: set[str] = field(default_factory=set)
    expanded_chunk_ids: set[str] = field(default_factory=set)
    expanded: bool = False

    @property
    def rank(self) -> int:
        return min(item.rank for item in self.items)

    @property
    def score(self) -> float:
        return max(item.score for item in self.items)


def expand_evidence(
    evidence: Iterable[Evidence],
    current_chunks: Iterable[tuple[Chunk, object]],
    snapshot: DocumentContextSnapshot,
) -> tuple[Evidence, ...]:
    """Expand up to three ranked document revisions with bounded source text.

    Documents of at most 4,000 characters contribute their complete published
    body. Longer documents contribute only immediate neighbors of originally
    selected chunks. Supplemental text is capped at 6,000 unique source
    characters across the request; original evidence is always preserved.
    """
    ranked = tuple(evidence)
    if not ranked:
        return ()

    documents = {
        (document.document_id, document.revision_id): document
        for document in snapshot.documents
    }
    chunks_by_revision, chunks_by_id = _index_chunks(current_chunks)
    eligible = _first_document_revisions(ranked, documents)
    selected_keys = {key for key, _ in eligible}
    groups_by_key = _group_evidence(ranked, selected_keys, documents)
    added_source_chars = 0

    for key, document in eligible:
        groups = groups_by_key[key]
        if not groups:
            continue
        chunks = tuple(
            chunk
            for chunk in chunks_by_revision.get(key, ())
            if _valid_chunk(chunk, len(document.body))
        )
        original_ids = {
            chunk_id for group in groups for chunk_id in group.original_chunk_ids
        }
        known_spans = _union_spans(span for group in groups for span in group.spans)

        if len(document.body) <= WHOLE_DOCUMENT_MAX_CHARS:
            unit_spans = (SourceSpan(0, len(document.body)),)
            novel = _novel_spans(unit_spans, known_spans)
            cost = _span_length(novel)
            if added_source_chars + cost <= MAX_ADDED_SOURCE_CHARS:
                supplemental_ids = {
                    chunk.chunk_id
                    for chunk in chunks
                    if chunk.chunk_id not in original_ids
                    and _spans_overlap(novel, chunk.spans)
                }
                for group in groups:
                    group.spans = _union_spans(group.spans + unit_spans)
                    group.expanded_chunk_ids.update(supplemental_ids)
                    group.expanded = group.expanded or cost > 0
                added_source_chars += cost
                groups_by_key[key] = _merge_groups(groups)
            continue

        anchors = _original_anchors(groups, chunks_by_id, key, len(document.body))
        for chunk, parent_ids in _neighbor_units(anchors, chunks):
            novel = _novel_spans(chunk.spans, known_spans)
            cost = _span_length(novel)
            if not novel or added_source_chars + cost > MAX_ADDED_SOURCE_CHARS:
                continue

            target_groups = [
                group
                for group in groups
                if group.original_chunk_ids.intersection(parent_ids)
            ]
            if not target_groups:
                continue

            for group in target_groups:
                group.spans = _union_spans(group.spans + chunk.spans)
                group.expanded_chunk_ids.add(chunk.chunk_id)
                group.expanded = True
            known_spans = _union_spans(known_spans + chunk.spans)
            added_source_chars += cost
        groups_by_key[key] = _merge_groups(groups)

    expanded = []
    handled = set()
    for item in ranked:
        key = (item.document_id, item.revision_id)
        if key not in selected_keys or key not in documents:
            expanded.append(item)
            continue
        groups = groups_by_key[key]
        for group_index, group in enumerate(groups):
            identity = (key, group_index)
            if identity in handled or item not in group.items:
                continue
            handled.add(identity)
            expanded.append(_render_group(group, documents[key]))
    expanded.sort(key=lambda item: item.rank)
    return tuple(expanded)


def _first_document_revisions(evidence, documents):
    selected = []
    seen = set()
    for item in sorted(enumerate(evidence), key=lambda pair: (pair[1].rank, pair[0])):
        current = item[1]
        key = (current.document_id, current.revision_id)
        document = documents.get(key)
        if (
            key in seen
            or document is None
            or current.knowledge_id != document.knowledge_id
            or current.revision != document.revision
        ):
            continue
        seen.add(key)
        selected.append((key, document))
        if len(selected) == MAX_EXPANDED_DOCUMENTS:
            break
    return selected


def _index_chunks(current_chunks):
    by_revision = {}
    by_id = {}
    for chunk, _vector in current_chunks:
        key = (chunk.document_id, chunk.revision_id)
        by_revision.setdefault(key, []).append(chunk)
        by_id.setdefault(chunk.chunk_id, chunk)
    for chunks in by_revision.values():
        chunks.sort(key=lambda chunk: (chunk.ordinal, chunk.chunk_id))
    return by_revision, by_id


def _group_evidence(evidence, selected_keys, documents):
    result = {key: [] for key in selected_keys}
    for key in result:
        items = [
            item for item in evidence if (item.document_id, item.revision_id) == key
        ]
        document = documents[key]
        groups = []
        for item in items:
            if not _valid_spans(item.spans, len(document.body)):
                groups.append(
                    _EvidenceGroup(
                        items=[item],
                        spans=(),
                        original_chunk_ids=set(item.chunk_ids),
                        expanded_chunk_ids=set(item.expanded_chunk_ids),
                    )
                )
                continue
            overlapping = [
                group for group in groups if _spans_overlap(group.spans, item.spans)
            ]
            if not overlapping:
                groups.append(
                    _EvidenceGroup(
                        items=[item],
                        spans=_union_spans(item.spans),
                        original_chunk_ids=set(item.chunk_ids),
                        expanded_chunk_ids=set(item.expanded_chunk_ids),
                    )
                )
                continue
            group = overlapping[0]
            group.items.append(item)
            group.spans = _union_spans(group.spans + item.spans)
            group.original_chunk_ids.update(item.chunk_ids)
            group.expanded_chunk_ids.update(item.expanded_chunk_ids)
            for other in overlapping[1:]:
                group.items.extend(other.items)
                group.spans = _union_spans(group.spans + other.spans)
                group.original_chunk_ids.update(other.original_chunk_ids)
                group.expanded_chunk_ids.update(other.expanded_chunk_ids)
                group.expanded = group.expanded or other.expanded
                groups.remove(other)
        groups.sort(
            key=lambda group: (group.rank, min(group.original_chunk_ids, default=""))
        )
        result[key] = groups
    return result


def _original_anchors(groups, chunks_by_id, key, body_length):
    anchors = []
    for group in groups:
        for chunk_id in sorted(group.original_chunk_ids):
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None or (chunk.document_id, chunk.revision_id) != key:
                continue
            if not _valid_chunk(chunk, body_length):
                continue
            anchors.append((chunk, group, chunk_id))
    return anchors


def _neighbor_units(anchors, chunks):
    by_ordinal = {chunk.ordinal: chunk for chunk in chunks if _valid_chunk(chunk)}
    units = {}
    for anchor, group, anchor_id in anchors:
        for offset in (-1, 1):
            neighbor = by_ordinal.get(anchor.ordinal + offset)
            if neighbor is None or neighbor.chunk_id == anchor.chunk_id:
                continue
            unit = units.setdefault(neighbor.chunk_id, [neighbor, set()])
            unit[1].add(anchor_id)
    return tuple(units[key] for key in units)


def _merge_groups(groups):
    merged = []
    for group in groups:
        if not group.spans:
            merged.append(group)
            continue
        overlapping = [
            other for other in merged if _spans_overlap(other.spans, group.spans)
        ]
        if not overlapping:
            merged.append(group)
            continue
        primary = overlapping[0]
        primary.items.extend(group.items)
        primary.spans = _union_spans(primary.spans + group.spans)
        primary.original_chunk_ids.update(group.original_chunk_ids)
        primary.expanded_chunk_ids.update(group.expanded_chunk_ids)
        primary.expanded = primary.expanded or group.expanded
        for other in overlapping[1:]:
            primary.items.extend(other.items)
            primary.spans = _union_spans(primary.spans + other.spans)
            primary.original_chunk_ids.update(other.original_chunk_ids)
            primary.expanded_chunk_ids.update(other.expanded_chunk_ids)
            primary.expanded = primary.expanded or other.expanded
            merged.remove(other)
    merged.sort(
        key=lambda group: (group.rank, min(group.original_chunk_ids, default=""))
    )
    return merged


def _render_group(group, document):
    if len(group.items) == 1 and not group.expanded:
        return group.items[0]

    original_spans = _union_spans(span for item in group.items for span in item.spans)
    if not group.spans:
        base = min(group.items, key=lambda item: item.rank)
        return replace(
            base,
            score=group.score,
            rank=group.rank,
            chunk_ids=tuple(sorted(group.original_chunk_ids)),
            expanded_chunk_ids=tuple(
                sorted(group.expanded_chunk_ids - group.original_chunk_ids)
            ),
            original_spans=original_spans,
        )
    spans = _union_spans(group.spans)
    text = "\n".join(document.body[span.start : span.end] for span in spans)
    expanded_spans = _novel_spans(spans, original_spans)
    base = min(group.items, key=lambda item: item.rank)
    return replace(
        base,
        text=text,
        spans=spans,
        chunk_ids=tuple(sorted(group.original_chunk_ids)),
        score=group.score,
        rank=group.rank,
        expanded_chunk_ids=tuple(
            sorted(group.expanded_chunk_ids - group.original_chunk_ids)
        ),
        original_spans=original_spans,
        expanded_spans=expanded_spans,
    )


def _valid_chunk(chunk: Chunk, body_length=None) -> bool:
    return bool(chunk.spans) and all(
        span.start >= 0
        and span.end >= span.start
        and (body_length is None or span.end <= body_length)
        for span in chunk.spans
    )


def _valid_spans(spans, body_length):
    return bool(spans) and all(
        span.start >= 0 and span.end <= body_length and span.end >= span.start
        for span in spans
    )


def _spans_overlap(left, right):
    return any(
        first.start < second.end and second.start < first.end
        for first in left
        for second in right
    )


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


def _novel_spans(candidate, known):
    known_ranges = _union_offsets(known)
    novel = []
    for span in candidate:
        cursor = span.start
        for start, end in known_ranges:
            if end <= cursor:
                continue
            if start >= span.end:
                break
            if start > cursor:
                novel.append(SourceSpan(cursor, min(start, span.end), span.kind))
            cursor = max(cursor, end)
            if cursor >= span.end:
                break
        if cursor < span.end:
            novel.append(SourceSpan(cursor, span.end, span.kind))
    return _union_spans(novel)


def _union_offsets(spans):
    ranges = []
    for span in sorted(spans, key=lambda item: (item.start, item.end)):
        if ranges and span.start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], span.end))
        else:
            ranges.append((span.start, span.end))
    return tuple(ranges)


def _span_length(spans):
    return sum(end - start for start, end in _union_offsets(spans))
