import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app.company_knowledge import DEFAULT_DOCUMENTS_PATH, get_documents_path
from app.dependencies import DOCUMENTS_PATH as SERVER_DOCUMENTS_PATH
from sanaebi_assistant import DOCUMENTS_PATH as ANSWER_DOCUMENTS_PATH


class CompanyKnowledgePathTests(unittest.TestCase):
    def test_defaults_to_current_company_knowledge_dataset(self):
        with patch.dict(os.environ):
            os.environ.pop("IEUM_WORKS_PATH", None)
            self.assertEqual(get_documents_path(), DEFAULT_DOCUMENTS_PATH)
            self.assertEqual(
                DEFAULT_DOCUMENTS_PATH.parts[-3:],
                ("data", "company-knowledge", "documents.jsonl"),
            )

    def test_preserves_ieum_works_path_override(self):
        override = Path("/tmp/custom-company-knowledge.jsonl")
        with patch.dict(os.environ, {"IEUM_WORKS_PATH": str(override)}):
            self.assertEqual(get_documents_path(), override)

    def test_server_and_answer_runner_share_the_configured_path(self):
        configured_path = get_documents_path()
        self.assertEqual(SERVER_DOCUMENTS_PATH, configured_path)
        self.assertEqual(ANSWER_DOCUMENTS_PATH, configured_path)


if __name__ == "__main__":
    unittest.main()
