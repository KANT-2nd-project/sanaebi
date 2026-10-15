"""Historical contextual embedding chunker used by retrieval experiments only."""

from __future__ import annotations

from dataclasses import replace

from app.retrieval.chunking import (
    _clip_header,
    chunk_document,
    chunk_identifier,
    embedding_input,
    embedding_input_key,
    token_count,
    token_offsets,
)
from app.retrieval.config import MAX_INPUT_TOKENS
from app.retrieval.types import RetrievalUnavailable
from retrieval.experiments.contextual_config import CONTEXTUAL_SPEC


def contextual_chunk_document(document, tokenizer, *, spec=CONTEXTUAL_SPEC):
    """Add adjacent source text to embedding inputs without changing source spans."""
    base_chunks = chunk_document(document, tokenizer, spec=spec)
    contextual_chunks = []

    for chunk in base_chunks:
        base_header = _clip_header(document.title, chunk.heading, tokenizer)
        before_window, after_window = _adjacent_context_windows(
            document.body,
            chunk.spans,
            tokenizer,
            spec.embedding_context_tokens,
        )
        header, encoded_text = _compose_contextual_input(
            base_header,
            chunk.text,
            tokenizer,
            spec,
            before_window,
            after_window,
            spec.embedding_context_tokens,
        )
        while (
            token_count(tokenizer, encoded_text, special_tokens=True) > MAX_INPUT_TOKENS
        ):
            low, high = 0, spec.embedding_context_tokens
            best = None
            while low <= high:
                middle = (low + high) // 2
                candidate_header, candidate_text = _compose_contextual_input(
                    base_header,
                    chunk.text,
                    tokenizer,
                    spec,
                    before_window,
                    after_window,
                    middle,
                )
                if (
                    token_count(tokenizer, candidate_text, special_tokens=True)
                    <= MAX_INPUT_TOKENS
                ):
                    best = (candidate_header, candidate_text)
                    low = middle + 1
                else:
                    high = middle - 1
            if best is not None:
                header, encoded_text = best
                break

            header_offsets = token_offsets(tokenizer, base_header)
            if len(header_offsets) > 1:
                base_header = base_header[: header_offsets[-2][1]].rstrip() + "…"
                header, encoded_text = _compose_contextual_input(
                    base_header,
                    chunk.text,
                    tokenizer,
                    spec,
                    before_window,
                    after_window,
                    0,
                )
                continue
            raise RetrievalUnavailable("청크가 임베딩 입력 한도를 넘습니다.")

        input_key = embedding_input_key(encoded_text, spec=spec)
        contextual_chunks.append(
            replace(
                chunk,
                embedding_header=header,
                embedding_text=encoded_text,
                input_key=input_key,
                chunk_id=chunk_identifier(
                    chunk.document_id,
                    chunk.revision_id,
                    chunk.ordinal,
                    input_key,
                    spec=spec,
                ),
            )
        )

    return tuple(contextual_chunks)


def _adjacent_context_windows(body, spans, tokenizer, max_side_tokens):
    if not max_side_tokens:
        return ("", ()), ("", ())
    start = min(span.start for span in spans)
    end = max(span.end for span in spans)
    before = _boundary_window(body, 0, start, tokenizer, max_side_tokens, from_end=True)
    after = _boundary_window(
        body, end, len(body), tokenizer, max_side_tokens, from_end=False
    )
    return before, after


def _compose_contextual_input(
    base_header, text, tokenizer, spec, before_window, after_window, context_limit
):
    before, after = _bounded_adjacent_context(
        before_window,
        after_window,
        tokenizer,
        spec,
        context_limit,
    )
    header = _contextual_header(base_header, before, after)
    return header, embedding_input(header, "", text)


def _boundary_window(body, start, end, tokenizer, max_tokens, *, from_end):
    """Tokenize only a growing edge window, avoiding repeated whole-body scans."""
    if start >= end:
        return "", ()
    window_size = min(end - start, max(256, max_tokens * 8))
    while True:
        window_start = end - window_size if from_end else start
        window_end = end if from_end else start + window_size
        value = body[window_start:window_end]
        offsets = token_offsets(tokenizer, value)
        if len(offsets) >= max_tokens or window_size >= end - start:
            if from_end:
                offsets = offsets[-max_tokens:]
                value = value[offsets[0][0] :] if offsets else ""
                offsets = tuple(
                    (
                        a - (offsets[0][0] if offsets else 0),
                        b - (offsets[0][0] if offsets else 0),
                    )
                    for a, b in offsets
                )
            else:
                offsets = offsets[:max_tokens]
                value = value[: offsets[-1][1]] if offsets else ""
            return value, tuple(offsets)
        window_size = min(end - start, window_size * 2)


def _bounded_adjacent_context(before_window, after_window, tokenizer, spec, limit):
    before_text, before_offsets = before_window
    after_text, after_offsets = after_window
    limit = max(0, limit)
    left_target = min(spec.context_before_tokens, (limit + 1) // 2)
    right_target = min(spec.context_after_tokens, limit // 2)
    left_count = min(left_target, len(before_offsets))
    right_count = min(right_target, len(after_offsets))
    remaining = limit - left_count - right_count
    if remaining:
        left_extra = min(remaining, len(before_offsets) - left_count)
        left_count += left_extra
        remaining -= left_extra
        right_count += min(remaining, len(after_offsets) - right_count)
    before = _slice_token_window(before_text, before_offsets, left_count, from_end=True)
    after = _slice_token_window(after_text, after_offsets, right_count, from_end=False)
    return before, after


def _slice_token_window(value, offsets, count, *, from_end):
    if not count:
        return ""
    selected = offsets[-count:] if from_end else offsets[:count]
    return value[selected[0][0] : selected[-1][1]].strip()


def _contextual_header(header, before, after):
    parts = [header]
    if before:
        parts.extend(("[인접 이전 문맥]", before))
    if after:
        parts.extend(("[인접 다음 문맥]", after))
    return "\n".join(part for part in parts if part)
