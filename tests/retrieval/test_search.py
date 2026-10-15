from typing import ClassVar

from app.retrieval.search import (
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
