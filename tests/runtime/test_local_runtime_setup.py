"""Local preparation preserves user state and resolves the exact reset bundle."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import settings
from app.retrieval.baseline import prepare_baseline
from app.retrieval.config import KURE_SPEC
from app.retrieval.types import RetrievalUnavailable
from tests.runtime.kure_helpers import KureFakeEmbedder
from tests.runtime.test_rag_followup_readiness import _write_source


class LocalPathsTests(unittest.TestCase):
    def test_unset_baseline_resolves_prepared_source_and_spec_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            _write_source(source, "회사 규정입니다.")
            bundle = prepare_baseline(
                source,
                root / "artifacts/retrieval-baselines",
                KureFakeEmbedder(),
                spec=KURE_SPEC,
            )
            with (
                patch.object(settings, "PROJECT_ROOT", root),
                patch.dict(
                    os.environ,
                    {
                        "SANAEBI_RETRIEVAL_SOURCE": str(source),
                        "SANAEBI_RETRIEVAL_BASELINE": "",
                    },
                ),
            ):
                self.assertEqual(settings.get_retrieval_baseline(), bundle)
                bundle.unlink()
                self.assertEqual(settings.get_retrieval_baseline(), bundle)
                self.assertFalse(bundle.exists())

    def test_explicit_missing_path_is_not_replaced_by_default(self):
        with patch.dict(
            os.environ, {"SANAEBI_RETRIEVAL_BASELINE": "/missing/explicit"}
        ):
            self.assertEqual(
                settings.get_retrieval_baseline(), Path("/missing/explicit")
            )


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        from scripts import local_runtime, prepare_local_runtime

        self.setup = prepare_local_runtime
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / "source.jsonl"
        _write_source(self.source, "## 휴가\n연차는 사전 신청합니다.")
        self.database = self.root / "documents.sqlite3"
        self.model = self.root / "model"
        self.model.mkdir()
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(self.database),
                    "SANAEBI_RETRIEVAL_SOURCE": str(self.source),
                    "SANAEBI_RETRIEVAL_BASELINE": "",
                    "SANAEBI_RETRIEVAL_ROOT": str(self.root / "index"),
                    "SANAEBI_EMBEDDING_PATH": str(self.model),
                    "SANAEBI_RETRIEVAL_MODE": "rag",
                },
            )
        )
        for module in (settings, local_runtime, prepare_local_runtime):
            self.enterContext(patch.object(module, "PROJECT_ROOT", self.root))
        for module in (local_runtime, prepare_local_runtime):
            self.enterContext(
                patch.object(module, "check_prerequisites", return_value=[])
            )
            self.enterContext(patch.object(module, "check_model"))
        self.embedder = KureFakeEmbedder()
        self.enterContext(
            patch.object(
                prepare_local_runtime, "create_embedder", return_value=self.embedder
            )
        )

    def test_missing_database_requires_explicit_initialization(self):
        result = self.setup.prepare()
        self.assertFalse(result["ready"])
        self.assertFalse(self.database.exists())

    def test_initialization_reuses_bundle_and_preserves_existing_revisions(self):
        from app.documents.context import DocumentContextProvider

        self.assertTrue(self.setup.prepare(init_documents=True)["ready"])
        before = DocumentContextProvider().snapshot()
        with patch.object(
            self.embedder,
            "encode_documents",
            side_effect=AssertionError("unexpected embedding"),
        ):
            self.assertTrue(self.setup.prepare(init_documents=True)["ready"])
        self.assertEqual(before, DocumentContextProvider().snapshot())

    def test_existing_empty_database_is_not_repopulated(self):
        from app.documents.context import DocumentContextProvider
        from app.documents.repository import DocumentRepository

        DocumentRepository(self.database).initialize()
        result = self.setup.prepare(init_documents=True)
        self.assertTrue(result["ready"], result)
        self.assertEqual(DocumentContextProvider().snapshot().documents, ())

    def test_invalid_baseline_does_not_create_document_database(self):
        bundle = prepare_baseline(
            self.source,
            self.root / "artifacts/retrieval-baselines",
            self.embedder,
            spec=KURE_SPEC,
        )
        bundle.write_bytes(b"corrupt")
        with self.assertRaises(RetrievalUnavailable):
            self.setup.prepare(init_documents=True)
        self.assertFalse(self.database.exists())

    def test_diagnostic_is_read_only_and_reports_missing_index(self):
        from app.documents.transfer import import_knowledge
        from scripts.local_runtime import diagnose

        import_knowledge(self.source, self.database, apply=True, publish=True)
        before = self.database.read_bytes()
        result = diagnose()
        self.assertIn("index_not_ready", result["errors"])
        self.assertIn("baseline_missing", result["errors"])
        self.assertEqual(before, self.database.read_bytes())
        self.assertFalse((self.root / "index").exists())

    def test_failed_new_import_can_be_retried_without_poisoned_database(self):
        with patch.dict(os.environ, {"SANAEBI_RETRIEVAL_MODE": "full"}):
            with (
                patch.object(
                    self.setup, "import_knowledge", side_effect=OSError("disk failure")
                ),
                self.assertRaises(OSError),
            ):
                self.setup.prepare(init_documents=True)
            self.assertFalse(self.database.exists())
            self.assertTrue(self.setup.prepare(init_documents=True)["ready"])

    def test_concurrent_database_creation_is_not_overwritten(self):
        from app.documents.context import DocumentContextProvider
        from app.documents.repository import DocumentRepository
        from app.documents.transfer import import_knowledge

        def concurrent_import(*args, **kwargs):
            result = import_knowledge(*args, **kwargs)
            DocumentRepository(self.database).initialize()
            return result

        with (
            patch.object(self.setup, "import_knowledge", side_effect=concurrent_import),
            self.assertRaises(FileExistsError),
        ):
            self.setup.prepare(init_documents=True)
        self.assertEqual(DocumentContextProvider().snapshot().documents, ())

    def test_baseline_preparation_does_not_reread_source_for_target_path(self):
        from app.retrieval import baseline

        raw = self.source.read_bytes()
        with patch.object(
            baseline, "_read_source", wraps=baseline._read_source
        ) as read:
            bundle = prepare_baseline(
                self.source, self.root / "bundle-check", self.embedder, spec=KURE_SPEC
            )
        # one preparation read plus one final validation read, no second path read
        self.assertEqual(read.call_count, 2)
        import hashlib

        self.assertEqual(bundle.parent.name, hashlib.sha256(raw).hexdigest())
