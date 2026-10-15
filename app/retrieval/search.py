"""The fixed C retrieval policy used by the server runtime."""

from __future__ import annotations

import hashlib
import json

MINIMUM_SIMILARITY_SCORE = 0.35

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


def search_config_id() -> str:
    canonical = json.dumps(C_SEARCH_POLICY, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
