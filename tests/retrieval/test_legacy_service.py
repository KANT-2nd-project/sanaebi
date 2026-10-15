from dataclasses import replace

import numpy as np

from app.retrieval.repository import IndexRepository
from app.retrieval.types import Chunk, SourceSpan
from retrieval.experiments.legacy_search import SearchConfig, search_config_id
from retrieval.experiments.legacy_service import (
    LegacyRetrievalService,
    _apply_budgets,
    _bm25_document_terms,
    _expand_adjacent_hits,
    _merge_hits,
)
from tests.retrieval.helpers import (
    FakeEmbedder,
    RetrievalTestCase,
    make_document,
    make_snapshot,
)


class LegacyRetrievalTests(RetrievalTestCase):
    @staticmethod
    def _chunk(document, ordinal, spans):
        return Chunk(
            document_id=document.document_id,
            revision_id=document.revision_id,
            ordinal=ordinal,
            spans=tuple(spans),
            heading="",
            embedding_header=document.title,
            text="본문",
            embedding_text="passage: 본문",
            input_key=f"key-{ordinal}",
            chunk_id=f"chunk-{ordinal}",
        )

    def test_merge_handles_three_transitively_overlapping_hits(self):
        document = make_document(body="x" * 40)
        snapshot = make_snapshot(document)
        first = self._chunk(document, 0, [SourceSpan(0, 15)])
        bridge = self._chunk(document, 1, [SourceSpan(10, 25)])
        last = self._chunk(document, 2, [SourceSpan(20, 35)])

        groups = _merge_hits(
            [(last, 0.9), (first, 0.8), (bridge, 0.7)],
            snapshot,
        )

        self.assertEqual(len(groups), 1)
        _, spans, group = groups[0]
        self.assertEqual(spans, (SourceSpan(0, 35),))
        self.assertEqual(group["chunks"], {"chunk-0", "chunk-1", "chunk-2"})

    def test_adjacent_expansion_adds_only_immediate_chunks_and_marks_provenance(self):
        body = "앞 근거\n핵심 조건\n다음 조건\n먼 다음 절"
        document = make_document(body=body)
        snapshot = make_snapshot(document)
        boundaries = [0, 5, 11, 17, len(body)]
        chunks = [
            self._chunk(
                document,
                index,
                [SourceSpan(boundaries[index], boundaries[index + 1])],
            )
            for index in range(4)
        ]
        old_revision = make_document(
            document_id=document.document_id,
            revision_id="revision-old",
            body=body,
        )
        old_neighbor = replace(
            self._chunk(old_revision, 0, [SourceSpan(0, 5)]),
            chunk_id="old-revision-chunk-0",
        )
        hits = _expand_adjacent_hits(
            [(chunks[1], 0.91)],
            chunks + [old_neighbor],
            SearchConfig(expand_adjacent=True),
        )

        self.assertEqual(
            [(chunk.chunk_id, role) for chunk, _, role, _ in hits],
            [("chunk-1", "anchor"), ("chunk-0", "expanded"), ("chunk-2", "expanded")],
        )
        evidence = _apply_budgets(_merge_hits(hits, snapshot), snapshot)
        self.assertEqual(len(evidence), 1)
        self.assertIn("앞 근거", evidence[0].text)
        self.assertIn("핵심 조건", evidence[0].text)
        self.assertIn("다음 조건", evidence[0].text)
        self.assertEqual(set(evidence[0].expanded_chunk_ids), {"chunk-0", "chunk-2"})
        self.assertEqual(evidence[0].score, 0.91)
        self.assertNotIn(old_neighbor.chunk_id, evidence[0].chunk_ids)

    def test_repeated_table_header_does_not_merge_separate_row_groups(self):
        header = "| 항목 | 값 |\n|---|---|\n"
        rows = [f"| row-{index:03} | {'x' * 40} |\n" for index in range(300)]
        body = header + "".join(rows)
        document = make_document(body=body)
        snapshot = make_snapshot(document)
        selected_rows = (0, 1, len(rows) - 1)
        hits = []
        scores = {0: 0.8, 1: 0.7, len(rows) - 1: 1.0}
        for ordinal, row_index in enumerate(selected_rows):
            row_start = len(header) + sum(len(row) for row in rows[:row_index])
            row_end = row_start + len(rows[row_index])
            chunk = self._chunk(
                document,
                ordinal,
                [
                    SourceSpan(0, len(header), "table_header"),
                    SourceSpan(row_start, row_end),
                ],
            )
            hits.append((chunk, scores[row_index]))

        groups = _merge_hits(hits, snapshot)
        evidence = _apply_budgets(groups, snapshot)

        self.assertEqual(len(groups), 3)
        self.assertEqual(len(evidence), 3)
        self.assertIn("row-299", evidence[0].text)
        self.assertEqual(evidence[0].chunk_ids, ("chunk-2",))

    def test_budget_keeps_highest_scoring_late_overlapping_span_and_provenance(self):
        body = "a" * 1_000 + "b" * 1_000 + "HIGHEST-RANKED-DETAIL" + "c" * 1_500
        document = make_document(body=body)
        snapshot = make_snapshot(document)
        first = self._chunk(document, 0, [SourceSpan(0, 1_500)])
        bridge = self._chunk(document, 1, [SourceSpan(1_000, 2_500)])
        last = self._chunk(document, 2, [SourceSpan(2_000, len(body))])

        groups = _merge_hits(
            [(last, 1.0), (first, 0.8), (bridge, 0.7)],
            snapshot,
        )
        evidence = _apply_budgets(groups, snapshot)

        self.assertEqual(len(evidence), 3)
        self.assertIn("HIGHEST-RANKED-DETAIL", evidence[0].text)
        self.assertEqual(evidence[0].chunk_ids, ("chunk-2",))
        self.assertTrue(all(len(item.text) <= 2_000 for item in evidence))

    def test_budget_provenance_excludes_chunk_without_selected_source_text(self):
        documents = [
            make_document(
                document_id=f"doc-{index}",
                knowledge_id=f"knowledge-{index}",
                revision_id=f"revision-{index}",
                body="a" * 1_800,
            )
            for index in range(5)
        ]
        snapshot = make_snapshot(*documents)
        hits = [
            (
                self._chunk(document, index, [SourceSpan(0, len(document.body))]),
                1.0 - index * 0.01,
            )
            for index, document in enumerate(documents[:4])
        ]
        final_document = documents[4]
        hits.extend(
            [
                (self._chunk(final_document, 10, [SourceSpan(0, 900)]), 0.9),
                (self._chunk(final_document, 11, [SourceSpan(850, 1_000)]), 0.8),
            ]
        )

        evidence = _apply_budgets(_merge_hits(hits, snapshot), snapshot)

        self.assertEqual(len(evidence), 5)
        self.assertEqual(evidence[-1].chunk_ids, ("chunk-10",))
        self.assertEqual(evidence[-1].spans, (SourceSpan(0, 800),))

    def test_expansion_never_uses_global_budget_reserved_for_original_anchors(self):
        documents = [
            make_document(
                document_id=f"doc-{index}",
                knowledge_id=f"knowledge-{index}",
                revision_id=f"revision-{index}",
                body=("a" * 2_000 if index == 0 else "b" * 1_600),
            )
            for index in range(5)
        ]
        snapshot = make_snapshot(*documents)
        anchors = []
        for index, document in enumerate(documents):
            anchor = replace(
                self._chunk(document, 0, [SourceSpan(0, 1_600)]),
                chunk_id=f"anchor-{index}",
            )
            anchors.append((anchor, 1.0 - index * 0.1))

        expansion = replace(
            self._chunk(documents[0], 1, [SourceSpan(1_200, 2_000)]),
            chunk_id="expanded-anchor-0",
        )
        hits = [
            (anchors[0][0], anchors[0][1], "anchor", None),
            (expansion, anchors[0][1], "expanded", anchors[0][0].chunk_id),
            *anchors[1:],
        ]

        evidence = _apply_budgets(_merge_hits(hits, snapshot), snapshot)

        self.assertEqual(len(evidence), 5)
        self.assertEqual([len(item.text) for item in evidence], [1_600] * 5)
        self.assertTrue(all("a" * 1_600 in item.text for item in evidence[:1]))
        self.assertNotIn(expansion.chunk_id, evidence[0].chunk_ids)
        self.assertEqual(evidence[0].expanded_chunk_ids, ())

    def test_bm25_document_terms_exclude_embedding_only_context(self):
        embedder = FakeEmbedder()
        document = make_document(title="원문 제목", body="원문 본문")
        snapshot = make_snapshot(document)
        chunk = replace(
            self._chunk(document, 0, [SourceSpan(0, len(document.body))]),
            heading="원문 소제목",
            embedding_header="embedding-only-secret-context",
            text="원문 본문",
        )

        terms = _bm25_document_terms(
            [(chunk, np.zeros(384))], snapshot, embedder.tokenizer
        )

        self.assertIn("원문", terms[chunk.chunk_id])
        self.assertNotIn("embedding-only-secret-context", terms[chunk.chunk_id])

    def test_anchor_scores_and_neighbor_ordinals_make_expansion_deterministic(self):
        document = make_document(body="x" * 3_000)
        snapshot = make_snapshot(document)
        left = replace(
            self._chunk(document, 0, [SourceSpan(1_000, 1_800)]),
            chunk_id="anchor-left",
        )
        right = replace(
            self._chunk(document, 1, [SourceSpan(1_400, 2_300)]),
            chunk_id="anchor-right",
        )
        left_neighbor = replace(
            self._chunk(document, -1, [SourceSpan(400, 1_400)]),
            chunk_id="expanded-left",
        )
        right_neighbor = replace(
            self._chunk(document, 2, [SourceSpan(1_700, 2_700)]),
            chunk_id="expanded-right",
        )

        set_iteration = tuple({left.chunk_id, right.chunk_id})
        low_id, high_id = set_iteration
        scores = {low_id: 0.8, high_id: 0.9}
        anchors = {
            left.chunk_id: left,
            right.chunk_id: right,
        }
        neighbors = {
            left.chunk_id: left_neighbor,
            right.chunk_id: right_neighbor,
        }

        def retrieve_in_order(anchor_order, neighbor_order):
            hits = [
                (anchors[anchor_id], scores[anchor_id], "anchor", None)
                for anchor_id in anchor_order
            ]
            hits.extend(
                (
                    neighbors[anchor_id],
                    scores[anchor_id],
                    "expanded",
                    anchor_id,
                )
                for anchor_id in neighbor_order
            )
            return _apply_budgets(_merge_hits(hits, snapshot), snapshot)

        forward = retrieve_in_order(
            (left.chunk_id, right.chunk_id),
            (left.chunk_id, right.chunk_id),
        )
        reversed_inputs = retrieve_in_order(
            (right.chunk_id, left.chunk_id),
            (right.chunk_id, left.chunk_id),
        )

        self.assertEqual(forward, reversed_inputs)
        expected_first_expansion = {
            "anchor-left": "expanded-left",
            "anchor-right": "expanded-right",
        }[high_id]
        self.assertEqual(forward[0].expanded_chunk_ids[0], expected_first_expansion)

    def test_total_budget_preserves_late_high_score_span_and_matching_score(self):
        documents = [
            make_document(
                document_id=f"doc-{index}",
                knowledge_id=f"knowledge-{index}",
                revision_id=f"revision-{index}",
                body="a" * 1_800,
            )
            for index in range(4)
        ]
        last_body = "l" * 850 + "HIGHEST-SCORE-EVIDENCE" + "h" * 128
        final_document = make_document(
            document_id="doc-final",
            knowledge_id="knowledge-final",
            revision_id="revision-final",
            body=last_body,
        )
        snapshot = make_snapshot(*documents, final_document)
        hits = [
            (
                self._chunk(document, index, [SourceSpan(0, len(document.body))]),
                1.0 - index * 0.01,
            )
            for index, document in enumerate(documents)
        ]
        hits.extend(
            [
                (
                    self._chunk(final_document, 10, [SourceSpan(850, 1_000)]),
                    0.9,
                ),
                (
                    self._chunk(final_document, 11, [SourceSpan(0, 900)]),
                    0.8,
                ),
            ]
        )

        evidence = _apply_budgets(_merge_hits(hits, snapshot), snapshot)

        final = evidence[-1]
        self.assertIn("HIGHEST-SCORE-EVIDENCE", final.text)
        self.assertEqual(final.chunk_ids, ("chunk-10", "chunk-11"))
        self.assertEqual(final.score, 0.9)
        self.assertEqual(final.spans[-1], SourceSpan(850, 1_000))

    def test_hybrid_search_runs_one_query_embedding_and_records_search_config(self):
        embedder = FakeEmbedder()
        config = SearchConfig(hybrid_search=True)
        service = LegacyRetrievalService(
            IndexRepository(self.tmp_path), embedder, search_config=config
        )
        documents = [
            make_document(
                document_id=f"doc-{index}",
                revision_id=f"revision-{index}",
                body=f"Git 토큰 {index} 정책을 보안 포털에서 확인한다.",
            )
            for index in range(12)
        ]
        snapshot = make_snapshot(*documents)
        service.reconcile(snapshot)
        embedder.query_batches.clear()

        result = service.retrieve("Git 토큰", snapshot)

        self.assertEqual(len(embedder.query_batches), 1)
        self.assertEqual(result.search_config_id, search_config_id(config))
        self.assertEqual(result.candidate_count, 10)
        self.assertEqual(len(result.candidate_chunk_ids), 10)
        self.assertLessEqual(len(result.evidence), 5)

    def test_retrieval_caps_evidence_count_and_text_budget(self):
        embedder = FakeEmbedder()
        service = LegacyRetrievalService(IndexRepository(self.tmp_path), embedder)
        body = "\n\n".join(
            f"## 항목 {index}\n"
            + " ".join(f"정책{index}_{word}" for word in range(100))
            for index in range(30)
        )
        snapshot = make_snapshot(make_document(body=body))
        service.reconcile(snapshot)

        result = service.retrieve("정책 신청", snapshot)

        self.assertGreaterEqual(len(result.evidence), 1)
        self.assertLessEqual(len(result.evidence), 5)
        self.assertLessEqual(sum(len(item.text) for item in result.evidence), 8_000)
        self.assertTrue(all(len(item.text) <= 2_000 for item in result.evidence))
