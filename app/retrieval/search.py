"""Search-only settings and lexical/vector rank combination."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchConfig:
    """Ranking behavior independent of the document-vector specification."""

    expand_adjacent: bool = False
    hybrid_search: bool = False
    candidate_count: int = 10
    vector_pool: int = 20
    keyword_pool: int = 20
    rrf_constant: int = 60
    bm25_k1: float = 1.2
    bm25_b: float = 0.75

    def to_dict(self) -> dict:
        return {
            "bm25_b": self.bm25_b,
            "bm25_k1": self.bm25_k1,
            "candidate_count": self.candidate_count,
            "expand_adjacent": self.expand_adjacent,
            "hybrid_search": self.hybrid_search,
            "keyword_pool": self.keyword_pool,
            "rrf_constant": self.rrf_constant,
            "vector_pool": self.vector_pool,
        }


DEFAULT_SEARCH_CONFIG = SearchConfig()


def search_config_id(config: SearchConfig = DEFAULT_SEARCH_CONFIG) -> str:
    canonical = json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def tokenize_terms(tokenizer, text: str) -> tuple[str, ...]:
    """Return deterministic Tiny-tokenizer terms, excluding all special tokens."""
    if hasattr(tokenizer, "tokenize"):
        tokens = tokenizer.tokenize(text)
        special_tokens = set(getattr(tokenizer, "all_special_tokens", ()))
    else:
        encoded = tokenizer(text, add_special_tokens=False, truncation=False)
        input_ids = encoded["input_ids"]
        if hasattr(input_ids, "tolist"):
            input_ids = input_ids.tolist()
        if input_ids and isinstance(input_ids[0], list):
            input_ids = input_ids[0]
        tokens = tokenizer.convert_ids_to_tokens(input_ids)
        special_tokens = set(getattr(tokenizer, "all_special_tokens", ()))
        special_ids = set(getattr(tokenizer, "all_special_ids", ()))
        tokens = [
            token
            for token_id, token in zip(input_ids, tokens, strict=True)
            if token_id not in special_ids
        ]
    return tuple(
        token.casefold()
        for token in tokens
        if isinstance(token, str) and token and token not in special_tokens
    )


def bm25_rank(
    query_tokens: Sequence[str],
    documents: Mapping[Hashable, Sequence[str]],
    *,
    top_k: int,
    k1: float = 1.2,
    b: float = 0.75,
) -> list[tuple[Hashable, float]]:
    """Rank documents with BM25 and stable key tie-breaking."""
    if top_k <= 0 or not query_tokens or not documents:
        return []
    lengths = {key: len(tokens) for key, tokens in documents.items()}
    average_length = sum(lengths.values()) / len(lengths)
    if average_length == 0:
        return []
    token_counts = {key: Counter(tokens) for key, tokens in documents.items()}
    document_frequency = Counter(
        term
        for term in set(query_tokens)
        for counts in token_counts.values()
        if counts.get(term, 0)
    )
    scores = {}
    total_documents = len(documents)
    for key, counts in token_counts.items():
        score = 0.0
        for term in query_tokens:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            frequency_in_documents = document_frequency[term]
            inverse_frequency = math.log(
                1.0
                + (total_documents - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            length_normalizer = 1.0 - b + b * lengths[key] / average_length
            score += (
                inverse_frequency
                * frequency
                * (k1 + 1.0)
                / (frequency + k1 * length_normalizer)
            )
        if score > 0:
            scores[key] = score
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))[:top_k]


def reciprocal_rank_fusion(
    vector_hits: Sequence[tuple[Hashable, float]],
    keyword_hits: Sequence[tuple[Hashable, float]],
    *,
    limit: int,
    rrf_constant: int = 60,
) -> list[tuple[Hashable, float]]:
    """Combine already-ranked lists with equal-weight reciprocal rank fusion."""
    scores: dict[Hashable, float] = {}
    for hits in (vector_hits, keyword_hits):
        for rank, (key, _) in enumerate(hits, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_constant + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))[:limit]
