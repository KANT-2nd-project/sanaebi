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
KURE_MODEL_ID = "nlpai-lab/KURE-v1"
KURE_MODEL_REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"
KURE_VECTOR_DIMENSION = 1024
KURE_POOLING = "cls"
KURE_MAX_QUERY_TOKENS = 512
KURE_MAX_DOCUMENT_TOKENS = 8192


def _legacy_model_contract(
    model_id,
    model_revision,
    dimension,
    dtype,
    pooling,
    normalization,
    query_prefix,
    passage_prefix,
    max_query_tokens,
    max_document_tokens,
):
    return (
        model_id == MODEL_ID
        and model_revision == MODEL_REVISION
        and dimension == VECTOR_DIMENSION
        and dtype == VECTOR_DTYPE
        and pooling == POOLING
        and normalization == NORMALIZATION
        and query_prefix == QUERY_PREFIX
        and passage_prefix == PASSAGE_PREFIX
        and max_query_tokens == MAX_INPUT_TOKENS
        and max_document_tokens == MAX_INPUT_TOKENS
    )


@dataclass(frozen=True)
class RetrievalSpec:
    """Immutable model and chunking inputs that identify one vector index."""

    chunker_version: str = CHUNKER_VERSION
    model_id: str = MODEL_ID
    model_revision: str = MODEL_REVISION
    dimension: int = VECTOR_DIMENSION
    dtype: str = VECTOR_DTYPE
    pooling: str = POOLING
    normalization: str = NORMALIZATION
    query_prefix: str = QUERY_PREFIX
    passage_prefix: str = PASSAGE_PREFIX
    max_query_tokens: int = MAX_INPUT_TOKENS
    max_document_tokens: int = MAX_INPUT_TOKENS
    target_body_tokens: int = TARGET_BODY_TOKENS
    overlap_tokens: int = OVERLAP_TOKENS
    splitter_model_id: str = MODEL_ID
    splitter_model_revision: str = MODEL_REVISION
    splitter_directory: str = "splitter"

    def to_dict(self) -> dict:
        # Keep the previously published Tiny serialization and IDs stable. New
        # profiles use separate query/document limits and explicit model fields.
        if _legacy_model_contract(
            self.model_id,
            self.model_revision,
            self.dimension,
            self.dtype,
            self.pooling,
            self.normalization,
            self.query_prefix,
            self.passage_prefix,
            self.max_query_tokens,
            self.max_document_tokens,
        ):
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
        result = {
            "chunker_version": self.chunker_version,
            "dimension": self.dimension,
            "dtype": self.dtype,
            "max_document_tokens": self.max_document_tokens,
            "max_query_tokens": self.max_query_tokens,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "passage_prefix": self.passage_prefix,
            "pooling": self.pooling,
            "query_prefix": self.query_prefix,
            "target_body_tokens": self.target_body_tokens,
            "overlap_tokens": self.overlap_tokens,
        }
        if self.model_id == KURE_MODEL_ID:
            result["splitter"] = {
                "model_id": self.splitter_model_id,
                "revision": self.splitter_model_revision,
                "directory": self.splitter_directory,
            }
        return result


DEFAULT_SPEC = RetrievalSpec()
KURE_SPEC = RetrievalSpec(
    chunker_version=CHUNKER_VERSION,
    model_id=KURE_MODEL_ID,
    model_revision=KURE_MODEL_REVISION,
    dimension=KURE_VECTOR_DIMENSION,
    dtype=VECTOR_DTYPE,
    pooling=KURE_POOLING,
    normalization=NORMALIZATION,
    query_prefix="",
    passage_prefix="",
    max_query_tokens=KURE_MAX_QUERY_TOKENS,
    max_document_tokens=KURE_MAX_DOCUMENT_TOKENS,
    target_body_tokens=TARGET_BODY_TOKENS,
    overlap_tokens=OVERLAP_TOKENS,
    splitter_model_id=MODEL_ID,
    splitter_model_revision=MODEL_REVISION,
    splitter_directory="splitter",
)
SERVER_SPEC = KURE_SPEC


def canonical_retrieval_spec(spec: RetrievalSpec = DEFAULT_SPEC) -> str:
    return json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))


def retrieval_spec_id(spec: RetrievalSpec = DEFAULT_SPEC) -> str:
    return hashlib.sha256(canonical_retrieval_spec(spec).encode("utf-8")).hexdigest()


# Existing module constants remain the default vector contract for callers.
SPEC = DEFAULT_SPEC.to_dict()
CANONICAL_SPEC = canonical_retrieval_spec(DEFAULT_SPEC)
SPEC_ID = retrieval_spec_id(DEFAULT_SPEC)
