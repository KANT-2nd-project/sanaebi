"""Fixed KURE selection and the preserved legacy Tiny C policy identity."""

from __future__ import annotations

import hashlib
import json

from app.retrieval.config import DEFAULT_SPEC, KURE_SPEC, RetrievalSpec

MINIMUM_SIMILARITY_SCORE = 0.35
KURE_MINIMUM_SIMILARITY_SCORE = 0.42882221937179565
KURE_TOP_K = 20

# This is descriptive metadata for the fixed policy, not a runtime selector.
C_SEARCH_POLICY = {
    "context_token_budget": None,
    "max_candidates": None,
    "max_evidence_chars": None,
    "max_evidence_count": None,
    "max_total_evidence_chars": None,
    "minimum_similarity_score": MINIMUM_SIMILARITY_SCORE,
    "selection": "vector_score_threshold",
}

KURE_SEARCH_POLICY = {
    "minimum_question_similarity_score": KURE_MINIMUM_SIMILARITY_SCORE,
    "selection": "question_gate_top_k",
    "top_k_chunks": KURE_TOP_K,
}


def search_config_id(spec: RetrievalSpec = DEFAULT_SPEC) -> str:
    policy = KURE_SEARCH_POLICY if spec == KURE_SPEC else C_SEARCH_POLICY
    canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
