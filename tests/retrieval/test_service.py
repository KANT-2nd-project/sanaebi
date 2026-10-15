import numpy as np

from app.retrieval.chunking import chunk_document
from app.retrieval.repository import IndexRepository
from app.retrieval.service import RetrievalService, _apply_budgets, _merge_hits
from app.retrieval.types import (
    Chunk,
    RetrievalInputTooLong,
    RetrievalUnavailable,
    SourceSpan,
)
from tests.retrieval.helpers import (
    FakeEmbedder,
    RetrievalTestCase,
    make_document,
    make_snapshot,
)


class RetrievalServiceTests(RetrievalTestCase):
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

    def test_reconcile_indexes_only_missing_revision_and_reuses_ready_vectors(self):
        embedder = FakeEmbedder()
        service = RetrievalService(IndexRepository(self.tmp_path), embedder)
        first = make_document(body="휴가 신청은 포털에서 한다. 팀장은 일정을 확인한다.")
        snapshot = make_snapshot(first)

        before = service.status(snapshot)
        self.assertEqual(
            before,
            {"ready": False, "expected": 1, "ready_count": 0, "missing": 1},
        )

        reconciled = service.reconcile(snapshot)
        self.assertIs(reconciled["ready"], True)
        self.assertEqual(reconciled["expected"], 1)
        self.assertEqual(reconciled["ready_count"], 1)
        first_batch_count = sum(map(len, embedder.document_batches))
        self.assertGreater(first_batch_count, 0)

        service.reconcile(snapshot)
        self.assertEqual(sum(map(len, embedder.document_batches)), first_batch_count)
        self.assertEqual(service.status(snapshot)["missing"], 0)

    def test_retrieval_filters_old_revision_and_returns_snapshot_provenance(self):
        embedder = FakeEmbedder()
        service = RetrievalService(IndexRepository(self.tmp_path), embedder)
        old = make_document(
            revision_id="revision-old", body="오래된 기준은 이전 포털 절차다."
        )
        service.reconcile(make_snapshot(old))

        current = make_document(
            revision_id="revision-current",
            revision=2,
            body="현재 기준은 인사 포털에서 신청한다.",
            source_reference="https://intra.example/leave",
        )
        snapshot = make_snapshot(current)
        service.reconcile(snapshot)

        result = service.retrieve("휴가 신청 방법", snapshot)

        self.assertEqual(result.snapshot_fingerprint, snapshot.fingerprint)
        self.assertTrue(result.spec_id)
        self.assertTrue(result.evidence)
        self.assertEqual(
            {item.revision_id for item in result.evidence}, {"revision-current"}
        )
        self.assertEqual(
            {item.source_reference for item in result.evidence},
            {"https://intra.example/leave"},
        )
        self.assertTrue(all("오래된 기준" not in item.text for item in result.evidence))

    def test_retrieval_rejects_question_over_token_limit_before_encoding(self):
        embedder = FakeEmbedder()
        service = RetrievalService(IndexRepository(self.tmp_path), embedder)
        snapshot = make_snapshot(make_document())
        service.reconcile(snapshot)
        embedder.query_batches.clear()

        with self.assertRaises(RetrievalInputTooLong):
            service.retrieve(" ".join(f"질문{index}" for index in range(520)), snapshot)

        self.assertEqual(embedder.query_batches, [])

    def test_retrieval_caps_evidence_count_and_text_budget(self):
        embedder = FakeEmbedder()
        service = RetrievalService(IndexRepository(self.tmp_path), embedder)
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

    def test_status_is_read_only_and_can_run_without_an_embedder(self):
        repository = IndexRepository(self.tmp_path)
        service = RetrievalService(repository, embedder=None)
        snapshot = make_snapshot(make_document())

        status = service.status(snapshot)

        self.assertIs(status["ready"], False)
        self.assertFalse(repository.database_path.exists())

    def test_identical_input_reuses_vectors_across_new_revision_ids(self):
        embedder = FakeEmbedder()
        service = RetrievalService(IndexRepository(self.tmp_path), embedder)
        old = make_document(revision_id="before-reset")
        service.reconcile(make_snapshot(old))
        embedded_count = sum(map(len, embedder.document_batches))

        restored = make_document(revision_id="after-reset", revision=1)
        status = service.reconcile(make_snapshot(restored))

        self.assertIs(status["ready"], True)
        self.assertEqual(sum(map(len, embedder.document_batches)), embedded_count)

    def test_failed_document_replace_keeps_previously_ready_index(self):
        embedder = FakeEmbedder()
        repository = IndexRepository(self.tmp_path)
        service = RetrievalService(repository, embedder)
        document = make_document()
        snapshot = make_snapshot(document)
        service.reconcile(snapshot)

        chunks = chunk_document(document, embedder.tokenizer)
        invalid_vectors = np.zeros((len(chunks), 383), dtype=np.float32)
        with self.assertRaises(RetrievalUnavailable):
            repository.store_documents(((document, chunks, invalid_vectors),))

        self.assertIs(service.status(snapshot)["ready"], True)

    def test_corrupt_vector_is_not_reported_as_ready(self):
        import sqlite3

        embedder = FakeEmbedder()
        repository = IndexRepository(self.tmp_path)
        service = RetrievalService(repository, embedder)
        snapshot = make_snapshot(make_document())
        service.reconcile(snapshot)

        with sqlite3.connect(repository.database_path) as connection:
            connection.execute("UPDATE chunks SET vector_blob = ?", (b"invalid",))

        with self.assertRaises(RetrievalUnavailable):
            service.status(snapshot)

    def test_multi_document_index_write_rolls_back_as_one_transaction(self):
        embedder = FakeEmbedder()
        repository = IndexRepository(self.tmp_path)
        service = RetrievalService(repository, embedder)
        first = make_document(document_id="doc-a", knowledge_id="ieum-001")
        second = make_document(
            document_id="doc-b", knowledge_id="ieum-002", revision_id="revision-b"
        )
        first_chunks = chunk_document(first, embedder.tokenizer)
        second_chunks = chunk_document(second, embedder.tokenizer)
        first_vectors = embedder.encode_documents(
            [chunk.embedding_text for chunk in first_chunks]
        )
        invalid_vectors = np.zeros((len(second_chunks), 383), dtype=np.float32)

        with self.assertRaises(RetrievalUnavailable):
            repository.store_documents(
                (
                    (first, first_chunks, first_vectors),
                    (second, second_chunks, invalid_vectors),
                )
            )

        status = service.status(make_snapshot(first, second))
        self.assertIs(status["ready"], False)
        self.assertEqual(status["ready_count"], 0)
        self.assertTrue(repository.database_path.exists())
