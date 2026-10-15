"""Reset and recovery must never re-run source reset to repair an index failure."""

import io
import json
import os
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.documents import service as document_service
from app.documents.context import DocumentContextProvider
from app.documents.repository import DocumentRepository
from app.documents.transfer import _apply_rows, read_source, sha
from app.retrieval import reset as retrieval_reset
from app.retrieval.baseline import prepare_baseline
from app.retrieval.config import KURE_SPEC
from app.retrieval.repository import IndexRepository
from app.retrieval.service import RetrievalService
from scripts import index_documents, reset_demo_retrieval
from tests.runtime.kure_helpers import KureFakeEmbedder as FakeEmbedder


class RagCommandTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        row = json.loads(
            Path("data/company-knowledge/documents.jsonl").read_text().splitlines()[0]
        )
        row["document"] = "기본 문서 본문. 포털에서 신청한다."
        self.source = self.root / "source.jsonl"
        self.source.write_text(json.dumps(row, ensure_ascii=False) + "\n")
        self.database = self.root / "documents.sqlite3"
        self.repository = DocumentRepository(self.database)
        self.repository.initialize()
        raw, rows = read_source(self.source)
        with self.repository.transaction() as connection:
            _apply_rows(self.repository, connection, rows, sha(raw), True)
        self.provider = DocumentContextProvider(repository=self.repository)
        self.bundle = prepare_baseline(
            self.source, self.root / "bundles", FakeEmbedder(), spec=KURE_SPEC
        )
        self.index_root = self.root / "index"
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(self.database),
                    "SANAEBI_RETRIEVAL_ROOT": str(self.index_root),
                    "SANAEBI_RETRIEVAL_BASELINE": str(self.bundle),
                    "SANAEBI_RETRIEVAL_SOURCE": str(self.source),
                },
            )
        )

    def run_cli(self, args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return index_documents.main(args)

    def test_status_does_not_create_index_or_load_model(self):
        with patch.object(
            index_documents, "create_embedder", side_effect=AssertionError("no model")
        ):
            self.assertEqual(self.run_cli(["--status"]), 2)
        self.assertFalse(self.index_root.exists())

    def test_two_resets_map_fresh_revisions_without_model(self):
        before = self.provider.snapshot()
        with patch(
            "app.retrieval.embedding.KureEmbedder.warmup",
            side_effect=AssertionError("no model"),
        ):
            for _ in range(2):
                report = reset_demo_retrieval.reset_with_retrieval(
                    self.source,
                    self.database,
                    self.bundle,
                    self.index_root,
                    spec=KURE_SPEC,
                )
                self.assertTrue(report["documents_reset"], report)
                self.assertTrue(report["retrieval_ready"], report)
                after = self.provider.snapshot()
                self.assertNotEqual(
                    before.documents[0].revision_id, after.documents[0].revision_id
                )
                before = after

    def test_bundle_mismatch_fails_before_source_mutation(self):
        before = self.provider.snapshot().fingerprint
        self.source.write_text(self.source.read_text() + "\n")
        report = reset_demo_retrieval.reset_with_retrieval(
            self.source, self.database, self.bundle, self.index_root, spec=KURE_SPEC
        )
        self.assertFalse(report["documents_reset"])
        self.assertEqual(self.provider.snapshot().fingerprint, before)

    def test_mapping_failure_recovers_without_resetting_source(self):
        with patch.object(
            retrieval_reset,
            "restore_baseline",
            side_effect=OSError("simulated disk failure"),
        ):
            failed = reset_demo_retrieval.reset_with_retrieval(
                self.source, self.database, self.bundle, self.index_root, spec=KURE_SPEC
            )
        self.assertTrue(failed["documents_reset"])
        self.assertFalse(failed["retrieval_ready"])
        before = self.provider.snapshot()
        version = self.repository.get(before.documents[0].document_id)["record_version"]
        with (
            patch(
                "app.documents.reset.reset_demo_documents",
                side_effect=AssertionError("never reset"),
            ),
            patch.object(
                index_documents,
                "create_embedder",
                side_effect=AssertionError("never load"),
            ),
        ):
            self.assertEqual(self.run_cli(["--restore-baseline"]), 0)
        self.assertEqual(self.provider.snapshot(), before)
        self.assertEqual(
            self.repository.get(before.documents[0].document_id)["record_version"],
            version,
        )
        self.assertTrue(
            RetrievalService(
                IndexRepository(self.index_root, spec=KURE_SPEC), None
            ).status(before)["ready"]
        )

    def test_writer_lock_refuses_other_writer_before_reset(self):
        before = self.provider.snapshot().fingerprint
        with index_documents.writer_lock(self.index_root, spec=KURE_SPEC):
            result = reset_demo_retrieval.reset_with_retrieval(
                self.source, self.database, self.bundle, self.index_root, spec=KURE_SPEC
            )
        self.assertFalse(result["documents_reset"])
        self.assertEqual(self.provider.snapshot().fingerprint, before)

    def test_preflight_does_not_require_existing_database(self):
        with (
            redirect_stdout(io.StringIO()),
            patch.object(
                retrieval_reset,
                "reset_demo_documents",
                side_effect=AssertionError("no writes"),
            ),
        ):
            result = reset_demo_retrieval.main(
                [
                    "--source",
                    str(self.source),
                    "--database",
                    str(self.root / "absent.sqlite3"),
                    "--bundle",
                    str(self.bundle),
                    "--check",
                ]
            )
        self.assertEqual(result, 0)
        self.assertFalse((self.root / "absent.sqlite3").exists())

    def test_clear_restore_invalidates_then_reuses_baseline_without_encoding(self):
        from app.retrieval.service import RetrievalService
        from tests.runtime.kure_helpers import KureFakeEmbedder as FakeEmbedder

        index = IndexRepository(self.index_root, spec=KURE_SPEC)
        retriever = RetrievalService(index, FakeEmbedder(), baseline_path=self.bundle)
        retriever.reconcile(self.provider.snapshot())
        previous = self.provider.snapshot()
        repository = DocumentRepository(self.database)
        for action in ("clear", "restore"):
            preview = document_service.preview_maintenance(
                repository, action, self.source
            )
            document_service.maintain_documents(
                repository,
                action,
                preview["expected_state"],
                str(uuid.uuid4()),
                self.source,
            )
            current = self.provider.snapshot()
            if action == "clear":
                self.assertEqual(current.documents, ())
                self.assertEqual(index.current_chunks(current), [])
            else:
                self.assertNotEqual(
                    previous.documents[0].revision_id, current.documents[0].revision_id
                )
                self.assertFalse(retriever.status(current)["ready"])
                with patch.object(
                    retriever.embedder,
                    "encode_documents",
                    side_effect=AssertionError("baseline reuse only"),
                ):
                    retriever.reconcile(current)
                self.assertTrue(retriever.status(current)["ready"])
