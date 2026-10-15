"""Markdown-aware chunking that keeps exact offsets into the source body."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.retrieval.config import (
    MAX_INPUT_TOKENS,
    OVERLAP_TOKENS,
    PASSAGE_PREFIX,
    SPEC_ID,
    TARGET_BODY_TOKENS,
)
from app.retrieval.types import Chunk, RetrievalUnavailable, SourceSpan

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TOKEN_HEADER_BUDGET = 120


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    heading: str


def _as_list(value):
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value and isinstance(value[0], list):
        value = value[0]
    return value


def token_offsets(tokenizer, text: str) -> tuple[tuple[int, int], ...]:
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )
    offsets = _as_list(encoded["offset_mapping"])
    return tuple((int(start), int(end)) for start, end in offsets if end > start)


def token_count(tokenizer, text: str, *, special_tokens=True) -> int:
    encoded = tokenizer(
        text,
        add_special_tokens=special_tokens,
        truncation=False,
    )
    return len(_as_list(encoded["input_ids"]))


def embedding_input(title: str, heading: str, text: str) -> str:
    context = "\n".join(part for part in (title, heading) if part.strip())
    return (
        f"{PASSAGE_PREFIX}{context}\n{text}" if context else f"{PASSAGE_PREFIX}{text}"
    )


def embedding_input_key(value: str) -> str:
    return hashlib.sha256(f"{SPEC_ID}\0{value}".encode()).hexdigest()


def chunk_identifier(document_id: str, revision_id: str, ordinal: int, input_key: str):
    value = f"{SPEC_ID}\0{document_id}\0{revision_id}\0{ordinal}\0{input_key}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lines(body: str):
    cursor = 0
    for line in body.splitlines(keepends=True):
        end = cursor + len(line)
        yield cursor, end, line.rstrip("\r\n")
        cursor = end
    if cursor < len(body):
        yield cursor, len(body), body[cursor:].rstrip("\r\n")


def _blocks(body: str):
    lines = list(_lines(body))
    sections: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        start, end, content = lines[index]
        if not content.strip():
            index += 1
            continue

        heading_match = _HEADING.match(content)
        if heading_match:
            level = len(heading_match.group(1))
            sections = [(depth, title) for depth, title in sections if depth < level]
            sections.append((level, heading_match.group(2).strip()))
            yield _Block(
                start, end, "heading", " > ".join(title for _, title in sections)
            )
            index += 1
            continue

        heading = " > ".join(title for _, title in sections)
        if _FENCE.match(content):
            delimiter = _FENCE.match(content).group(1)
            block_start, block_end = start, end
            index += 1
            while index < len(lines):
                _, block_end, next_content = lines[index]
                index += 1
                if next_content.lstrip().startswith(delimiter):
                    break
            yield _Block(block_start, block_end, "code", heading)
            continue

        if _TABLE_LINE.match(content):
            block_start, block_end = start, end
            index += 1
            while index < len(lines) and _TABLE_LINE.match(lines[index][2]):
                block_end = lines[index][1]
                index += 1
            yield _Block(block_start, block_end, "table", heading)
            continue

        block_start, block_end = start, end
        index += 1
        while index < len(lines):
            _, next_end, next_content = lines[index]
            if not next_content.strip() or _HEADING.match(next_content):
                break
            if _TABLE_LINE.match(next_content) or _FENCE.match(next_content):
                break
            block_end = next_end
            index += 1
        yield _Block(block_start, block_end, "paragraph", heading)


def _clip_header(title: str, heading: str, tokenizer) -> str:
    header = "\n".join(part for part in (title, heading) if part.strip())
    offsets = token_offsets(tokenizer, header)
    if len(offsets) <= _TOKEN_HEADER_BUDGET:
        return header
    clipped = header[: offsets[_TOKEN_HEADER_BUDGET - 1][1]].rstrip()
    return f"{clipped}…"


def _render(body: str, spans: tuple[SourceSpan, ...]) -> str:
    return "\n".join(body[span.start : span.end] for span in spans)


def chunk_document(document, tokenizer) -> tuple[Chunk, ...]:
    """Split one published document; every span points to source-body characters."""
    body = document.body
    if not isinstance(body, str) or not body.strip():
        return ()

    raw_chunks: list[tuple[tuple[SourceSpan, ...], str]] = []
    pending_start: int | None = None
    pending_end: int | None = None
    pending_heading = ""
    pending_tokens = 0

    def flush_pending():
        nonlocal pending_start, pending_end, pending_heading, pending_tokens
        if pending_start is not None and pending_end is not None:
            raw_chunks.append(
                ((SourceSpan(pending_start, pending_end),), pending_heading)
            )
        pending_start = pending_end = None
        pending_heading = ""
        pending_tokens = 0

    def split_span(start: int, end: int, heading: str, kind="body"):
        value = body[start:end]
        offsets = token_offsets(tokenizer, value)
        if not offsets:
            return
        step = max(1, TARGET_BODY_TOKENS - OVERLAP_TOKENS)
        token_start = 0
        while token_start < len(offsets):
            token_end = min(len(offsets), token_start + TARGET_BODY_TOKENS)
            span_start = start + offsets[token_start][0]
            span_end = start + offsets[token_end - 1][1]
            raw_chunks.append(((SourceSpan(span_start, span_end, kind),), heading))
            if token_end == len(offsets):
                break
            token_start += step

    for block in _blocks(body):
        block_text = body[block.start : block.end]
        count = token_count(tokenizer, block_text, special_tokens=False)
        if block.kind == "table" and count > TARGET_BODY_TOKENS:
            flush_pending()
            _split_table(body, block, tokenizer, raw_chunks)
            continue
        if count > TARGET_BODY_TOKENS:
            flush_pending()
            split_span(block.start, block.end, block.heading, block.kind)
            continue
        if pending_start is not None and (
            pending_heading != block.heading
            or pending_tokens + count > TARGET_BODY_TOKENS
        ):
            flush_pending()
        if pending_start is None:
            pending_start = block.start
            pending_heading = block.heading
        pending_end = block.end
        pending_tokens += count
    flush_pending()

    chunks = []
    for ordinal, (spans, heading) in enumerate(raw_chunks):
        text = _render(body, spans)
        header = _clip_header(document.title, heading, tokenizer)
        encoded_text = embedding_input(header, "", text)
        # The header budget reserves room for a 360-token body and model specials.
        # Keep this as a checked invariant so tokenizer behavior changes fail closed.
        while (
            token_count(tokenizer, encoded_text, special_tokens=True) > MAX_INPUT_TOKENS
        ):
            header_offsets = token_offsets(tokenizer, header)
            if len(header_offsets) > 1:
                header = header[: header_offsets[-2][1]].rstrip() + "…"
                encoded_text = embedding_input(header, "", text)
                continue
            raise RetrievalUnavailable("청크가 임베딩 입력 한도를 넘습니다.")
        input_key = embedding_input_key(encoded_text)
        chunks.append(
            Chunk(
                document_id=document.document_id,
                revision_id=document.revision_id,
                ordinal=ordinal,
                spans=spans,
                heading=heading,
                embedding_header=header,
                text=text,
                embedding_text=encoded_text,
                input_key=input_key,
                chunk_id=chunk_identifier(
                    document.document_id, document.revision_id, ordinal, input_key
                ),
            )
        )

    _verify_coverage(body, chunks)
    return tuple(chunks)


def _split_table(body: str, block: _Block, tokenizer, raw_chunks):
    table_lines = [line for line in _lines(body[block.start : block.end])]
    if len(table_lines) < 2:
        _split_table_fallback(body, block, tokenizer, raw_chunks)
        return
    absolute = [
        (block.start + start, block.start + end, text)
        for start, end, text in table_lines
    ]
    header_end_index = (
        2 if len(absolute) > 2 and re.match(r"^\s*\|?\s*:?-{3,}", absolute[1][2]) else 1
    )
    header_start, header_end = absolute[0][0], absolute[header_end_index - 1][1]
    header_tokens = token_count(
        tokenizer, body[header_start:header_end], special_tokens=False
    )
    if header_tokens >= TARGET_BODY_TOKENS - OVERLAP_TOKENS:
        _split_table_fallback(body, block, tokenizer, raw_chunks)
        return
    header_span = SourceSpan(header_start, header_end, "table_header")
    row_capacity = TARGET_BODY_TOKENS - header_tokens
    rows = absolute[header_end_index:]
    current: list[tuple[int, int, str]] = []
    current_tokens = 0
    for row in rows:
        row_tokens = token_count(tokenizer, row[2], special_tokens=False)
        if row_tokens > row_capacity:
            if current:
                raw_chunks.append(
                    (
                        (header_span, SourceSpan(current[0][0], current[-1][1])),
                        block.heading,
                    )
                )
                current, current_tokens = [], 0
            local_chunks: list[tuple[tuple[SourceSpan, ...], str]] = []
            _split_span_with_header(
                body,
                row[0],
                row[1],
                block.heading,
                header_span,
                tokenizer,
                local_chunks,
            )
            raw_chunks.extend(local_chunks)
            continue
        if current and current_tokens + row_tokens > row_capacity:
            raw_chunks.append(
                (
                    (header_span, SourceSpan(current[0][0], current[-1][1])),
                    block.heading,
                )
            )
            current, current_tokens = [], 0
        current.append(row)
        current_tokens += row_tokens
    if current:
        raw_chunks.append(
            ((header_span, SourceSpan(current[0][0], current[-1][1])), block.heading)
        )
    if not rows:
        raw_chunks.append(
            ((SourceSpan(block.start, block.end, "table"),), block.heading)
        )


def _split_span_with_header(
    body, start, end, heading, header_span, tokenizer, raw_chunks
):
    value = body[start:end]
    offsets = token_offsets(tokenizer, value)
    capacity = max(
        1,
        TARGET_BODY_TOKENS
        - token_count(
            tokenizer, body[header_span.start : header_span.end], special_tokens=False
        ),
    )
    step = max(1, capacity - OVERLAP_TOKENS)
    token_start = 0
    while token_start < len(offsets):
        token_end = min(len(offsets), token_start + capacity)
        raw_chunks.append(
            (
                (
                    header_span,
                    SourceSpan(
                        start + offsets[token_start][0],
                        start + offsets[token_end - 1][1],
                    ),
                ),
                heading,
            )
        )
        if token_end == len(offsets):
            break
        token_start += step


def _split_table_fallback(body, block, tokenizer, raw_chunks):
    value = body[block.start : block.end]
    offsets = token_offsets(tokenizer, value)
    step = max(1, TARGET_BODY_TOKENS - OVERLAP_TOKENS)
    token_start = 0
    while token_start < len(offsets):
        token_end = min(len(offsets), token_start + TARGET_BODY_TOKENS)
        raw_chunks.append(
            (
                (
                    SourceSpan(
                        block.start + offsets[token_start][0],
                        block.start + offsets[token_end - 1][1],
                        "table",
                    ),
                ),
                block.heading,
            )
        )
        if token_end == len(offsets):
            break
        token_start += step


def _verify_coverage(body: str, chunks: list[Chunk]):
    covered = bytearray(len(body))
    for chunk in chunks:
        for span in chunk.spans:
            if span.start < 0 or span.end <= span.start or span.end > len(body):
                raise RetrievalUnavailable("문서 청크 원문 위치가 올바르지 않습니다.")
            for index in range(span.start, span.end):
                covered[index] = 1
    for index, char in enumerate(body):
        if not char.isspace() and not covered[index]:
            raise RetrievalUnavailable("문서 청크가 원문 일부를 포함하지 않습니다.")
