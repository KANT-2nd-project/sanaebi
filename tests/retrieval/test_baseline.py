import json
import sqlite3

from app.retrieval.baseline import (
    prepare_baseline,
    restore_baseline,
    validate_baseline,
)
from app.retrieval.repository import IndexRepository
from app.retrieval.types import RetrievalUnavailable
from tests.retrieval.helpers import (
    FakeEmbedder,
    RetrievalTestCase,
    make_document,
    make_snapshot,
)


def write_source(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def source_row(document_id="ieum-001", title="휴가", body="포털에서 휴가를 신청한다."):
    return {"document_id": document_id, "title": title, "document": body}


class BaselineTests(RetrievalTestCase):
    def test_bundle_is_source_bound_and_has_no_runtime_revision_ids(self):
        source = self.tmp_path / "documents.jsonl"
        write_source(source, [source_row()])
        embedder = FakeEmbedder()

        bundle = prepare_baseline(source, self.tmp_path / "artifacts", embedder)
        report = validate_baseline(bundle, source)

        self.assertEqual(bundle.name, "baseline.sqlite3")
        self.assertIs(report["valid"], True)
        self.assertEqual(report["source_document_count"], 1)
        self.assertGreaterEqual(report["chunk_count"], 1)
        self.assertTrue(report["source_sha256"])

        with sqlite3.connect(bundle) as connection:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("baseline_documents", table_names)
            self.assertIn("baseline_chunks", table_names)
            self.assertNotIn("indexed_revisions", table_names)
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(baseline_chunks)")
            }
            self.assertNotIn("revision_id", columns)

    def test_mapping_only_restore_connects_new_revisions_without_embedding(self):
        source = self.tmp_path / "documents.jsonl"
        write_source(source, [source_row()])
        embedder = FakeEmbedder()
        bundle = prepare_baseline(source, self.tmp_path / "artifacts", embedder)
        embedder.document_batches.clear()
        repository = IndexRepository(self.tmp_path / "runtime")

        first_snapshot = make_snapshot(
            make_document(
                document_id="runtime-doc-a",
                knowledge_id="ieum-001",
                revision_id="reset-revision-a",
                title="휴가",
                body="포털에서 휴가를 신청한다.",
            )
        )
        first = restore_baseline(repository, bundle, source, first_snapshot)
        self.assertIs(first["ready"], True)
        self.assertEqual(first["ready_count"], 1)
        self.assertEqual(first["missing"], 0)
        self.assertEqual(embedder.document_batches, [])

        second_snapshot = make_snapshot(
            make_document(
                document_id="runtime-doc-b",
                knowledge_id="ieum-001",
                revision_id="reset-revision-b",
                revision=1,
                title="휴가",
                body="포털에서 휴가를 신청한다.",
            )
        )
        second = restore_baseline(repository, bundle, source, second_snapshot)
        self.assertIs(second["ready"], True)
        self.assertEqual(repository.status(second_snapshot)["missing"], 0)
        self.assertEqual(embedder.document_batches, [])

    def test_restore_rejects_changed_source_before_mapping(self):
        source = self.tmp_path / "documents.jsonl"
        write_source(source, [source_row()])
        bundle = prepare_baseline(source, self.tmp_path / "artifacts", FakeEmbedder())
        write_source(source, [source_row(body="변경된 문서 본문이다.")])

        with self.assertRaises(RetrievalUnavailable):
            validate_baseline(bundle, source)

    def test_restore_maps_only_matching_current_documents(self):
        source = self.tmp_path / "documents.jsonl"
        write_source(source, [source_row()])
        bundle = prepare_baseline(source, self.tmp_path / "artifacts", FakeEmbedder())
        repository = IndexRepository(self.tmp_path / "runtime")
        snapshot = make_snapshot(
            make_document(
                knowledge_id="ieum-001",
                revision_id="matching-revision",
                title="휴가",
                body="포털에서 휴가를 신청한다.",
            ),
            make_document(
                document_id="runtime-doc-other",
                knowledge_id="ieum-099",
                revision_id="unbundled-revision",
                title="새 문서",
                body="이 문서는 기본 bundle에 없다.",
            ),
        )

        result = restore_baseline(repository, bundle, source, snapshot)

        self.assertIs(result["ready"], False)
        self.assertEqual(result["expected"], 2)
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual(result["missing"], 1)

    def test_invalid_existing_bundle_is_preserved_on_reprepare(self):
        source = self.tmp_path / "documents.jsonl"
        write_source(source, [source_row()])
        bundle = prepare_baseline(source, self.tmp_path / "artifacts", FakeEmbedder())
        original = bundle.read_bytes()
        bundle.write_bytes(b"damaged bundle")

        with self.assertRaises(RetrievalUnavailable):
            prepare_baseline(source, self.tmp_path / "artifacts", FakeEmbedder())

        self.assertEqual(bundle.read_bytes(), b"damaged bundle")
        self.assertNotEqual(bundle.read_bytes(), original)
