"""Read-only score retrieval over one immutable document snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import numpy as np

from app.retrieval.chunking import token_count
from app.retrieval.config import (
    DEFAULT_SPEC,
    RetrievalSpec,
    retrieval_spec_id,
    validate_runtime_spec,
)
from app.retrieval.expansion import expand_evidence
from app.retrieval.indexer import RetrievalIndexer
from app.retrieval.repository import IndexRepository, _validated_matrix
from app.retrieval.search import SearchPolicy, policy_for_spec, search_config_id
from app.retrieval.selection import merge_hits, rank_hits, render_evidence
from app.retrieval.types import (
    RetrievalInputTooLong,
    RetrievalUnavailable,
    RetrievedContext,
)


class RetrievalService:
    """Online vector search; reconciliation is owned by RetrievalIndexer."""

    def __init__(
        self,
        repository: IndexRepository,
        embedder,
        baseline_path=None,
        *,
        spec: RetrievalSpec | None = None,
        search_policy: SearchPolicy | None = None,
        indexer: RetrievalIndexer | None = None,
        expand_context: bool = False,
    ):
        if type(expand_context) is not bool:
            raise TypeError("expand_context must be bool")
        self.expand_context = expand_context
        self.repository = repository
        self.embedder = embedder
        self.spec = repository.spec if spec is None else spec
        try:
            validate_runtime_spec(self.spec)
        except ValueError as exc:
            raise RetrievalUnavailable(str(exc)) from exc
        if self.spec != repository.spec:
            raise ValueError("retrieval service and repository specs must match")
        embedder_spec = getattr(embedder, "spec", None)
        if embedder_spec is not None and embedder_spec != self.spec:
            raise ValueError("retrieval service and embedder specs must match")
        if search_policy is not None and not isinstance(search_policy, SearchPolicy):
            raise TypeError("search_policy must be a SearchPolicy")
        self.search_policy = search_policy or policy_for_spec(self.spec)
        # Compatibility adapter for existing maintenance callers. New app wiring
        # injects the indexer into DocumentIndexSynchronizer directly.
        self._compat_indexer = indexer or RetrievalIndexer(
            repository, embedder, baseline_path, spec=self.spec
        )
        self.spec_id = getattr(repository, "spec_id", retrieval_spec_id(self.spec))

    @property
    def search_config_id(self):
        original = search_config_id(self.search_policy)
        if not self.expand_context:
            return original
        policy = {
            "base_policy": original,
            "context_expansion": "source-context-v1",
            "max_documents": 3,
            "whole_document_max_chars": 4000,
            "max_added_source_chars": 6000,
            "neighbor_radius": 1,
        }
        return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()

    def status(self, snapshot):
        """Readiness inspection remains separate from online retrieval."""
        return self.repository.status(snapshot)

    def reconcile(self, snapshot):
        """Compatibility adapter; write-side ownership lives in RetrievalIndexer."""
        return self._compat_indexer.reconcile(snapshot)

    def retrieve(self, question: str, snapshot) -> RetrievedContext:
        if self.embedder is None:
            raise RetrievalUnavailable("검색 임베딩 모델을 사용할 수 없습니다.")
        if not isinstance(question, str):
            raise TypeError("검색 질문은 문자열이어야 합니다.")
        query_input = f"{self.spec.query_prefix}{question}"
        if (
            token_count(self.embedder.tokenizer, query_input, special_tokens=True)
            > self.spec.max_query_tokens
        ):
            raise RetrievalInputTooLong(
                "검색 질문이 임베딩 모델의 길이 제한을 넘습니다."
            )
        if not snapshot.documents:
            return self._empty_context(snapshot)

        # One transaction loads and validates the current snapshot's chunks and
        # vectors. Missing or corrupt indexes fail before query encoding.
        current = self.repository.current_chunks(snapshot)
        if not current:
            raise RetrievalUnavailable("준비된 게시 문서에 검색 청크가 없습니다.")

        query = _validated_matrix(
            self.embedder.encode_queries([question]),
            rows=1,
            dimension=self.spec.dimension,
        )[0]
        matrix = _validated_matrix(
            np.stack([vector for _, vector in current]),
            rows=len(current),
            dimension=self.spec.dimension,
        )
        scores = matrix @ query
        hits = rank_hits(current, scores, policy=self.search_policy)
        candidate_chunk_ids = tuple(chunk.chunk_id for chunk, _ in hits)
        evidence_groups = merge_hits(hits, snapshot)
        selected = render_evidence(evidence_groups)
        if self.expand_context:
            selected = expand_evidence(selected, current, snapshot)
        return RetrievedContext(
            snapshot_fingerprint=snapshot.fingerprint,
            spec_id=self.spec_id,
            evidence=tuple(selected),
            candidate_count=len(hits),
            selected_count=len(selected),
            observed_at=datetime.now(UTC),
            candidate_chunk_ids=candidate_chunk_ids,
            search_config_id=self.search_config_id,
            source_document_count=len(snapshot.documents),
        )

    def _empty_context(self, snapshot):
        return RetrievedContext(
            snapshot_fingerprint=snapshot.fingerprint,
            spec_id=self.spec_id,
            evidence=(),
            candidate_count=0,
            selected_count=0,
            observed_at=datetime.now(UTC),
            candidate_chunk_ids=(),
            search_config_id=self.search_config_id,
            source_document_count=0,
        )


def _ranked_hits(
    current,
    scores,
    *,
    spec: RetrievalSpec = DEFAULT_SPEC,
    policy: SearchPolicy | None = None,
):
    """Compatibility wrapper for pure ranking and existing evaluation tests."""
    return rank_hits(current, scores, policy=policy or policy_for_spec(spec))


# Kept as private aliases for downstream tests and older internal imports.
_merge_hits = merge_hits
_render_evidence = render_evidence
