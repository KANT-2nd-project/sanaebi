"""Versioned model and chunking contract shared by indexes and baseline bundles."""

from __future__ import annotations

import hashlib
import json

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

SPEC = {
    "chunker_version": CHUNKER_VERSION,
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
CANONICAL_SPEC = json.dumps(SPEC, sort_keys=True, separators=(",", ":"))
SPEC_ID = hashlib.sha256(CANONICAL_SPEC.encode("utf-8")).hexdigest()
