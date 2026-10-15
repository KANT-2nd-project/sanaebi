import os
import unittest
from unittest.mock import patch

from app.settings import get_retrieval_mode


class RetrievalModeSettingsTests(unittest.TestCase):
    def test_retrieval_mode_defaults_to_rag(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_retrieval_mode(), "rag")

    def test_explicit_full_mode_overrides_default(self):
        with patch.dict(os.environ, {"SANAEBI_RETRIEVAL_MODE": "full"}, clear=True):
            self.assertEqual(get_retrieval_mode(), "full")


if __name__ == "__main__":
    unittest.main()
