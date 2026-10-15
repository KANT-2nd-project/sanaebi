"""Versioned model and chunking contract shared by indexes and baseline bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

SCHEMA_VERSION = 1
MODEL_ID = "exp-models/dragonkue-KoEn-E5-Tiny"
MODEL_REVISION = "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9"
VECTOR_DIMENSION = 384
VECTOR_DTYPE = "float32"
POOLING = "attention-mask-mean"
NORMALIZATION = "l2"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
CHUNKER_VERSION = "markdown-source-spans-v1"
MAX_INPUT_TOKENS = 512
TARGET_BODY_TOKENS = 360
OVERLAP_TOKENS = 60


@dataclass(frozen=True)
class RetrievalSpec:
    """Immutable inputs that affect document chunking or passage vectors."""

    chunker_version: str = CHUNKER_VERSION

    def to_dict(self) -> dict:
        return {
            "chunker_version": self.chunker_version,
            "dimension": VECTOR_DIMENSION,
            "dtype": VECTOR_DTYPE,
            "max_input_tokens": MAX_INPUT_TOKENS,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "normalization": NORMALIZATION,
            "passage_prefix": PASSAGE_PREFIX,
            "pooling": POOLING,
            "query_prefix": QUERY_PREFIX,
            "target_body_tokens": TARGET_BODY_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
        }


DEFAULT_SPEC = RetrievalSpec()


def canonical_retrieval_spec(spec: RetrievalSpec = DEFAULT_SPEC) -> str:
    return json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))


def retrieval_spec_id(spec: RetrievalSpec = DEFAULT_SPEC) -> str:
    return hashlib.sha256(canonical_retrieval_spec(spec).encode("utf-8")).hexdigest()


# Existing module constants remain the default vector contract for callers.
SPEC = DEFAULT_SPEC.to_dict()
CANONICAL_SPEC = canonical_retrieval_spec(DEFAULT_SPEC)
SPEC_ID = retrieval_spec_id(DEFAULT_SPEC)
