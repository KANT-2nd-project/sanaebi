import unittest
from unittest.mock import patch

from app.langchain_adapter import generate_assistant_response


class LangChainAdapterTests(unittest.TestCase):
    def test_selected_provider_reaches_runner(self):
        response = {"ok": True, "text": "질문", "reason": ""}
        with patch("sanaebi_assistant.process_response", return_value={}) as run:
            generate_assistant_response(response, "CLARIFY", provider="ollama")
        run.assert_called_once_with(
            response,
            classification_label="CLARIFY",
            provider="ollama",
            document_snapshot=None,
        )

    def test_legacy_assistant_keeps_default_provider_contract(self):
        with patch("sanaebi_assistant.process_response", return_value={}) as run:
            generate_assistant_response({"text": "질문"}, "CLARIFY")
        run.assert_called_once_with(
            {"text": "질문"},
            classification_label="CLARIFY",
            provider=None,
            document_snapshot=None,
        )
