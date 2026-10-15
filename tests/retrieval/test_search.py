from dataclasses import replace
from typing import ClassVar

import numpy as np

from app.retrieval.config import KURE_SPEC, retrieval_spec_id
from app.retrieval.search import (
    C_SEARCH_POLICY,
    KURE_MINIMUM_SIMILARITY_SCORE,
    KURE_SEARCH_POLICY,
    MINIMUM_SIMILARITY_SCORE,
    SearchPolicy,
    policy_for_spec,
)
from app.retrieval.search import (
    search_config_id as c_search_config_id,
)
from app.retrieval.service import _ranked_hits
from app.retrieval.types import Chunk, SourceSpan
from retrieval.experiments.legacy_search import (
    SearchConfig,
    bm25_rank,
    reciprocal_rank_fusion,
    search_config_id,
    tokenize_terms,
)
from tests.retrieval.helpers import RetrievalTestCase


class TinyLikeTokenizer:
    all_special_tokens: ClassVar[frozenset[str]] = frozenset(
        {"[CLS]", "[SEP]", "[PAD]"}
    )

    def tokenize(self, text):
        return text.split()


class SearchTests(RetrievalTestCase):
    def test_server_search_policy_is_fixed_to_unbounded_score_threshold_c(self):
        self.assertEqual(MINIMUM_SIMILARITY_SCORE, 0.35)
        self.assertEqual(C_SEARCH_POLICY.selection, "vector_score_threshold")
        self.assertIsNone(C_SEARCH_POLICY.max_candidates)
        self.assertIsNone(C_SEARCH_POLICY.max_evidence_count)
        self.assertIsNone(C_SEARCH_POLICY.max_evidence_chars)
        self.assertIsNone(C_SEARCH_POLICY.max_total_evidence_chars)
        self.assertIsNone(C_SEARCH_POLICY.context_token_budget)
        self.assertEqual(
            c_search_config_id(),
            "8c7a90ed5b75721daa0ca100d55cfc40d908cb22a44d4f472677c5761dcb48b5",
        )
        self.assertEqual(
            c_search_config_id(KURE_SPEC),
            "806c554644e676134a8295c1927aaf466a1e2d927c9bc1165ff7316b223bed47",
        )

    def test_changed_kure_chunk_spec_keeps_kure_policy_and_policy_identity(self):
        changed_spec = replace(KURE_SPEC, target_body_tokens=100)
        document_id = "doc"
        chunk = Chunk(
            document_id=document_id,
            revision_id="revision",
            ordinal=0,
            spans=(SourceSpan(0, 1),),
            heading="",
            embedding_header="title",
            text="x",
            embedding_text="x",
            input_key="key",
            chunk_id="chunk",
        )

        hits = _ranked_hits(
            [(chunk, None), (replace(chunk, chunk_id="below"), None)],
            np.array([0.42, 0.36]),
            spec=changed_spec,
        )

        self.assertEqual(policy_for_spec(changed_spec), policy_for_spec(KURE_SPEC))
        self.assertEqual(
            c_search_config_id(changed_spec), c_search_config_id(KURE_SPEC)
        )
        self.assertEqual([item[0].chunk_id for item in hits], [])
        self.assertNotEqual(
            retrieval_spec_id(changed_spec), retrieval_spec_id(KURE_SPEC)
        )

    def test_search_policy_is_immutable_and_injected_policy_gets_a_distinct_id(self):
        custom = SearchPolicy(
            selection="vector_score_threshold",
            minimum_similarity_score=0.6,
        )

        with self.assertRaises((AttributeError, TypeError)):
            custom.minimum_similarity_score = 0.7

        self.assertNotEqual(c_search_config_id(custom), c_search_config_id())
        self.assertEqual(
            KURE_SEARCH_POLICY.minimum_question_similarity_score,
            KURE_MINIMUM_SIMILARITY_SCORE,
        )

    def test_search_policy_rejects_behavior_fields_omitted_from_its_identity(self):
        with self.assertRaises(ValueError):
            replace(KURE_SEARCH_POLICY, minimum_similarity_score=0.9)
        with self.assertRaises(ValueError):
            replace(C_SEARCH_POLICY, top_k_chunks=1)
        with self.assertRaises(ValueError):
            replace(C_SEARCH_POLICY, max_candidates=10)

    def test_bm25_uses_tiny_tokens_without_special_tokens_and_is_deterministic(self):
        tokenizer = TinyLikeTokenizer()
        query = tokenize_terms(tokenizer, "[CLS] 토큰 회전 [SEP]")
        documents = {
            "first": tokenize_terms(tokenizer, "Git 토큰 회전 즉시"),
            "second": tokenize_terms(tokenizer, "토큰 관리 방법"),
            "third": tokenize_terms(tokenizer, "급여 지급일 확인"),
        }

        ranked = bm25_rank(query, documents, top_k=20)

        self.assertNotIn("[CLS]", query)
        self.assertNotIn("[SEP]", query)
        self.assertEqual([key for key, _ in ranked], ["first", "second"])
        self.assertEqual(ranked, bm25_rank(query, documents, top_k=20))

    def test_hybrid_fuses_top_twenty_lists_and_omits_empty_keyword_results(self):
        vector = [(f"chunk-{index}", 1.0 - index / 100) for index in range(25)]
        keyword = [("chunk-1", 3.0), ("chunk-22", 2.0)]

        fused = reciprocal_rank_fusion(vector[:20], keyword, limit=10)
        no_keyword = reciprocal_rank_fusion(vector[:20], [], limit=10)

        self.assertEqual(fused[0][0], "chunk-1")
        self.assertEqual(no_keyword, reciprocal_rank_fusion(vector[:20], [], limit=10))
        self.assertEqual(len(fused), 10)

    def test_default_search_config_has_stable_id_and_hybrid_is_separate(self):
        default = SearchConfig()
        hybrid = SearchConfig(expand_adjacent=True, hybrid_search=True)

        self.assertNotEqual(search_config_id(default), search_config_id(hybrid))
        self.assertEqual(default, SearchConfig())
