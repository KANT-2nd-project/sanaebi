import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.documents.context import DocumentContextProvider
from app.settings import get_document_database_path


class CompanyKnowledgePathTests(unittest.TestCase):
    def test_runtime_provider_and_shared_resolver_use_same_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom.sqlite3"
            with patch.dict(os.environ, {"SANAEBI_DOCUMENT_DB": str(path)}):
                self.assertEqual(get_document_database_path(), path)
                self.assertEqual(DocumentContextProvider().repository.path, path)
                self.assertFalse(path.exists())

    def test_legacy_jsonl_override_cannot_change_runtime_source(self):
        with patch.dict(os.environ, {"IEUM_WORKS_PATH": "/missing/legacy.jsonl"}):
            with patch("app.documents.context.warnings.warn") as warning:
                provider = DocumentContextProvider()
                warning.assert_called_once()
            self.assertEqual(provider.repository.path, get_document_database_path())
