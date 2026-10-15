"""Archived offline answering compatibility; never the server request path."""

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from archive.answering_v1 import assistant as legacy_assistant
from archive.answering_v1.answer_pipeline.run import load_documents
from scripts.validate_company_knowledge import DEFAULT
from tests.support.paths import ROOT

ANSWER = "인사 시스템에서 신청하세요."


class LegacyOfflineChainTests(unittest.TestCase):
    """Keep regression coverage for the archived utility, separate from HTTP."""

    def test_legacy_chain_formats_structured_answer_with_fake_model(self):
        class FakeModel:
            def with_structured_output(self, schema):
                return RunnableLambda(
                    lambda _: schema(
                        answer=ANSWER,
                        referenced_documents=["휴가 규정"],
                        note="신청 위치를 명시함",
                    )
                )

        request = {
            "response": {"ok": True, "text": "연차는 어디서 신청해요?"},
            "classification_label": legacy_assistant.CLARIFY,
        }
        with patch.object(
            legacy_assistant, "create_chat_model", return_value=FakeModel()
        ):
            result = legacy_assistant.create_chain("openai").invoke(request)

        self.assertEqual(result["answer"], ANSWER)
        self.assertEqual(result["document"], "휴가 규정")
        self.assertEqual(result["note(LLM)"], "신청 위치를 명시함")

    def test_legacy_process_response_keeps_provider_error_isolated(self):
        class FakeModel:
            def with_structured_output(self, schema):
                def fail(_):
                    raise ConnectionError("테스트 연결 오류")

                return RunnableLambda(fail)

        with patch.object(
            legacy_assistant, "create_chat_model", return_value=FakeModel()
        ):
            results = legacy_assistant.process_response(
                {"ok": True, "text": "일반 질문", "reason": ""},
                legacy_assistant.UNSUPPORTED,
                provider="openai",
            )

        self.assertFalse(results["openai"]["success"])
        self.assertEqual(results["openai"]["answer"], "")
        self.assertIn("ConnectionError", results["openai"]["error"])


class LegacyDocumentCompatibilityTests(unittest.TestCase):
    def test_published_corpus_remains_readable_by_legacy_loader(self):
        self.assertEqual(len(load_documents(DEFAULT)), 71)


class ArchivedEntrypointTests(unittest.TestCase):
    def test_cli_help_does_not_request_credentials_or_models(self):
        for module in (
            "archive.answering_v1.assistant",
            "archive.answering_v1.answer_pipeline.cli",
        ):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_assistant_keeps_result_in_project_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = {
                "response": {"ok": True, "text": "질문"},
                "classification_label": "SEARCH_KNOWLEDGE",
            }
            expected = {"fake": {"answer": "대역 답변"}}
            with (
                patch.object(legacy_assistant, "PROJECT_ROOT", root),
                patch.object(legacy_assistant, "read_input", return_value=request),
                patch.object(
                    legacy_assistant, "process_response", return_value=expected
                ) as call,
                patch.object(
                    legacy_assistant.getpass, "getpass", return_value="test-only"
                ),
                patch.dict(legacy_assistant.os.environ, {}, clear=False),
                patch("sys.argv", ["assistant"]),
                redirect_stdout(StringIO()),
            ):
                legacy_assistant.main()
            self.assertEqual(json.loads((root / "result.json").read_text()), expected)
            call.assert_called_once_with(
                request["response"], request["classification_label"]
            )

    def test_archived_default_paths_still_point_to_repository_data(self):
        from archive.answering_v1.answer_pipeline.cli import (
            DEFAULT_EVAL_SET_PATH,
            DEFAULT_EVALUATION_DOCUMENTS_PATH,
        )

        root = ROOT
        self.assertEqual(legacy_assistant.PROJECT_ROOT, root)
        self.assertEqual(
            DEFAULT_EVALUATION_DOCUMENTS_PATH,
            root / "data/archive/company-knowledge-v0/ieum_works.jsonl",
        )
        self.assertEqual(
            DEFAULT_EVAL_SET_PATH,
            root / "data/archive/company-knowledge-v0/eval_set_dev.jsonl",
        )
