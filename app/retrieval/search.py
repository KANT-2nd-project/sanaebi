"""Immutable online-search policies and their stable identifiers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.retrieval.config import DEFAULT_SPEC, KURE_MODEL_ID, MODEL_ID, RetrievalSpec

MINIMUM_SIMILARITY_SCORE = 0.35
KURE_MINIMUM_SIMILARITY_SCORE = 0.42882221937179565
KURE_TOP_K = 20


@dataclass(frozen=True, slots=True)
class SearchPolicy:
    """Immutable score-selection behavior, independent from vector specs."""

    selection: str
    minimum_similarity_score: float | None = None
    minimum_question_similarity_score: float | None = None
    top_k_chunks: int | None = None
    context_token_budget: int | None = None
    max_candidates: int | None = None
    max_evidence_count: int | None = None
    max_evidence_chars: int | None = None
    max_total_evidence_chars: int | None = None

    def __post_init__(self):
        if self.selection not in {"vector_score_threshold", "question_gate_top_k"}:
            raise ValueError("search policy selection is not supported")
        for value in (
            self.minimum_similarity_score,
            self.minimum_question_similarity_score,
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError("search policy similarity score must be in [0, 1]")
        if self.top_k_chunks is not None and self.top_k_chunks <= 0:
            raise ValueError("search policy top_k_chunks must be positive")
        unsupported_caps = (
            self.context_token_budget,
            self.max_candidates,
            self.max_evidence_count,
            self.max_evidence_chars,
            self.max_total_evidence_chars,
        )
        if any(value is not None for value in unsupported_caps):
            raise ValueError("search policy caps are not supported by this selector")
        if self.selection == "question_gate_top_k" and (
            self.minimum_question_similarity_score is None or self.top_k_chunks is None
        ):
            raise ValueError("question gate policy requires a threshold and top_k")
        if self.selection == "question_gate_top_k" and (
            self.minimum_similarity_score is not None
        ):
            raise ValueError("question gate policy cannot use a chunk threshold")
        if self.selection == "vector_score_threshold" and (
            self.minimum_similarity_score is None
        ):
            raise ValueError("score threshold policy requires a threshold")
        if self.selection == "vector_score_threshold" and (
            self.minimum_question_similarity_score is not None
            or self.top_k_chunks is not None
        ):
            raise ValueError(
                "score threshold policy cannot use a question gate or top_k"
            )

    def to_dict(self) -> dict:
        if self.selection == "vector_score_threshold":
            return {
                "context_token_budget": self.context_token_budget,
                "max_candidates": self.max_candidates,
                "max_evidence_chars": self.max_evidence_chars,
                "max_evidence_count": self.max_evidence_count,
                "max_total_evidence_chars": self.max_total_evidence_chars,
                "minimum_similarity_score": self.minimum_similarity_score,
                "selection": self.selection,
            }
        return {
            key: value
            for key, value in {
                "minimum_question_similarity_score": (
                    self.minimum_question_similarity_score
                ),
                "selection": self.selection,
                "top_k_chunks": self.top_k_chunks,
            }.items()
            if value is not None
        }


C_SEARCH_POLICY = SearchPolicy(
    context_token_budget=None,
    max_candidates=None,
    max_evidence_chars=None,
    max_evidence_count=None,
    max_total_evidence_chars=None,
    minimum_similarity_score=MINIMUM_SIMILARITY_SCORE,
    selection="vector_score_threshold",
)

KURE_SEARCH_POLICY = SearchPolicy(
    minimum_question_similarity_score=KURE_MINIMUM_SIMILARITY_SCORE,
    selection="question_gate_top_k",
    top_k_chunks=KURE_TOP_K,
)


def policy_for_spec(spec: RetrievalSpec) -> SearchPolicy:
    """Choose by the pinned model profile, never by full spec equality."""
    if spec.model_id == KURE_MODEL_ID:
        return KURE_SEARCH_POLICY
    if spec.model_id == MODEL_ID:
        return C_SEARCH_POLICY
    raise ValueError("retrieval model has no search policy")


def search_config_id(
    spec_or_policy: RetrievalSpec | SearchPolicy = DEFAULT_SPEC,
    *,
    policy: SearchPolicy | None = None,
) -> str:
    """Return the policy hash while preserving previously published IDs."""
    selected = (
        spec_or_policy
        if isinstance(spec_or_policy, SearchPolicy)
        else policy
        if policy is not None
        else policy_for_spec(spec_or_policy)
    )
    canonical = json.dumps(selected.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
