from dataclasses import replace
from unittest.mock import patch

import numpy as np

from app.retrieval.chunking import chunk_document
from app.retrieval.config import DEFAULT_SPEC
from app.retrieval.repository import IndexRepository
from app.retrieval.search import search_config_id
from app.retrieval.service import RetrievalService, _ranked_hits
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

    def test_score_threshold_includes_equal_boundary_and_has_stable_ties(self):
        document = make_document(body="abc")
        lower = self._chunk(document, 2, [SourceSpan(2, 3)])
        later_id = replace(
            self._chunk(document, 1, [SourceSpan(1, 2)]), chunk_id="chunk-b"
        )
        earlier_id = replace(
            self._chunk(document, 0, [SourceSpan(0, 1)]), chunk_id="chunk-a"
        )
        boundary = replace(
            self._chunk(document, 3, [SourceSpan(0, 1)]), chunk_id="chunk-boundary"
        )
        current = [
            (lower, None),
            (boundary, None),
            (later_id, None),
            (earlier_id, None),
        ]
        scores = [np.nextafter(0.35, 0.0), 0.35, 0.5, 0.5]

        hits = _ranked_hits(current, scores)

        self.assertEqual(
            [chunk.chunk_id for chunk, _ in hits],
            ["chunk-a", "chunk-b", "chunk-boundary"],
        )

    def test_runtime_uses_score_threshold_without_count_or_text_budgets(self):
        class ReadyRepository:
            spec = DEFAULT_SPEC

            def __init__(self, current):
                self.current = current

            @staticmethod
            def status(_snapshot):
                return {"ready": True}

            def current_chunks(self, _snapshot):
                return self.current

        embedder = FakeEmbedder()
        documents = [
            make_document(
                document_id=f"doc-{index}",
                knowledge_id=f"knowledge-{index}",
                revision_id=f"revision-{index}",
                body=f"source-{index}:" + ("word " * 1_000),
            )
            for index in range(13)
        ]
        snapshot = make_snapshot(*documents)
        current = []
        query = np.zeros(384, dtype=np.float32)
        query[0] = 1.0
        for index, document in enumerate(documents):
            chunk = self._chunk(document, index, [SourceSpan(0, len(document.body))])
            vector = np.zeros(384, dtype=np.float32)
            score = 0.34 if index == 12 else 0.5
            vector[0] = score
            vector[1] = np.sqrt(1 - score**2)
            current.append((replace(chunk, chunk_id=f"chunk-{index:02}"), vector))
        current.reverse()

        service = RetrievalService(ReadyRepository(current), embedder)
        with patch.object(embedder, "encode_queries", return_value=query[None, :]):
            result = service.retrieve("문서 질문", snapshot)

        self.assertEqual(
            result.candidate_chunk_ids, tuple(f"chunk-{i:02}" for i in range(12))
        )
        self.assertEqual(result.candidate_count, 12)
        self.assertEqual(len(result.evidence), 12)
        self.assertGreater(sum(len(item.text) for item in result.evidence), 8_000)
        self.assertGreater(
            sum(len(embedder.tokenizer(e.text)["input_ids"]) for e in result.evidence),
            4_000,
        )
        self.assertTrue(all(len(item.text) > 2_000 for item in result.evidence))
        self.assertEqual(
            [item.text for item in result.evidence],
            [document.body for document in documents[:12]],
        )

    def test_runtime_merges_large_overlapping_spans_without_truncation(self):
        class ReadyRepository:
            spec = DEFAULT_SPEC

            def __init__(self, current):
                self.current = current

            @staticmethod
            def status(_snapshot):
                return {"ready": True}

            def current_chunks(self, _snapshot):
                return self.current

        embedder = FakeEmbedder()
        document = make_document(body="source:" + ("x" * 3_000))
        snapshot = make_snapshot(document)
        chunks = [
            replace(
                self._chunk(document, ordinal, [SourceSpan(start, end)]),
                chunk_id=f"chunk-{ordinal}",
            )
            for ordinal, start, end in ((0, 0, 1_700), (1, 1_500, len(document.body)))
        ]
        vectors = []
        for score in (0.9, 0.8):
            vector = np.zeros(384, dtype=np.float32)
            vector[0] = score
            vector[1] = np.sqrt(1 - score**2)
            vectors.append(vector)

        service = RetrievalService(
            ReadyRepository(list(zip(chunks, vectors, strict=True))), embedder
        )
        query = np.zeros(384, dtype=np.float32)
        query[0] = 1.0
        with patch.object(embedder, "encode_queries", return_value=query[None, :]):
            result = service.retrieve("문서 질문", snapshot)

        self.assertEqual(len(result.evidence), 1)
        evidence = result.evidence[0]
        self.assertEqual(evidence.text, document.body)
        self.assertEqual(evidence.spans, (SourceSpan(0, len(document.body)),))
        self.assertEqual(evidence.chunk_ids, ("chunk-0", "chunk-1"))
        self.assertAlmostEqual(evidence.score, 0.9)

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
        self.assertEqual(result.candidate_count, len(result.candidate_chunk_ids))
        self.assertEqual(result.search_config_id, search_config_id())

    def test_retrieval_rejects_question_over_token_limit_before_encoding(self):
        embedder = FakeEmbedder()
        service = RetrievalService(IndexRepository(self.tmp_path), embedder)
        snapshot = make_snapshot(make_document())
        service.reconcile(snapshot)
        embedder.query_batches.clear()

        with self.assertRaises(RetrievalInputTooLong):
            service.retrieve(" ".join(f"질문{index}" for index in range(520)), snapshot)

        self.assertEqual(embedder.query_batches, [])

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
