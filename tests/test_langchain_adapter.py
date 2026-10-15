"""Server adapters exercise the real final prompt/parser with a fake provider."""

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import AsyncMock, Mock, patch

from httpx import Request
from openai import APIConnectionError

from app.answering.adapter import GenerationAnswerer
from app.answering.output import LLMResponseError
from app.documents.context import DocumentContext, DocumentContextSnapshot
from generation.documents import load_documents
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.types import ModelResponse

ROOT = Path(__file__).resolve().parent.parent


def snapshot(body="인사 포털에서 신청합니다.", revision=3):
    return DocumentContextSnapshot(
        (
            DocumentContext(
                document_id="managed-uuid",
                knowledge_id="original-id",
                revision_id="revision-uuid",
                revision=revision,
                title="신청",
                body=body,
                source_reference="policy:1",
                content_hash="hash",
                metadata={},
            ),
        )
    )


class LangChainAdapterTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_runtime_settings(ROOT)
        self.answerer = GenerationAnswerer(self.settings)
        self.client = Mock(
            return_value=ModelResponse('{"answer":"안내입니다."}', 10, 5, "stop")
        )
        self.client.aclose = AsyncMock()
        self.factory = self.enterContext(
            patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=self.client,
            )
        )
        self.addCleanup(lambda: asyncio.run(self.answerer.aclose()))

    def test_same_exported_snapshot_renders_identical_final_prompt(self):
        docs = snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "docs.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "document_id": "original-id",
                        "revision_number": 3,
                        "title": "신청",
                        "document": docs.documents[0].body,
                    }
                )
                + "\n"
            )
            expected = build_profile_prompt(
                "어디서 신청하나요?", load_documents(path), self.settings.prompt_profile
            )
        answer = self.answerer.answer("어디서 신청하나요?", docs)
        self.assertEqual(answer, "안내입니다.")
        self.client.assert_called_once_with(expected)
        self.assertNotIn("managed-uuid", expected.user)
        self.factory.assert_called_once_with(self.settings.config)

    def test_failure_statuses_are_never_answers(self):
        for response in (
            ModelResponse("plain"),
            ModelResponse('{"answer":"답", "extra":1}'),
            ModelResponse('{"answer":"   "}'),
            ModelResponse('{"answer":"답"}', finish_reason="length"),
            ModelResponse(None, refusal="refused"),
        ):
            with self.subTest(response=response):
                self.client.return_value = response
                with self.assertRaises(LLMResponseError):
                    self.answerer.answer("질문", snapshot())
        self.client.side_effect = TimeoutError()
        with self.assertRaises(LLMResponseError):
            self.answerer.answer("질문", snapshot())

    def test_api_error_and_programming_error_are_distinct(self):
        self.client.side_effect = APIConnectionError(
            request=Request("POST", "https://invalid.test")
        )
        with self.assertRaises(LLMResponseError):
            self.answerer.answer("질문", snapshot())
        self.client.side_effect = RuntimeError("bug")
        with self.assertRaisesRegex(RuntimeError, "bug"):
            self.answerer.answer("질문", snapshot())

    def test_initialization_failure_is_not_cached_or_retried_within_request(self):
        self.factory.side_effect = [
            APIConnectionError(request=Request("POST", "https://invalid.test")),
            self.client,
        ]
        with self.assertRaises(LLMResponseError):
            self.answerer.answer("질문", snapshot())
        self.assertEqual(self.factory.call_count, 1)
        self.assertEqual(self.answerer.answer("다음 요청", snapshot()), "안내입니다.")
        self.assertEqual(self.factory.call_count, 2)

    def test_concurrent_initialization_reuses_client_without_serializing_calls(self):
        barrier = Barrier(2)

        def invoke(prompt):
            barrier.wait(timeout=3)
            return ModelResponse('{"answer":"답변"}')

        self.client.side_effect = invoke
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda q: self.answerer.answer(q, snapshot()), ["질문A", "질문B"]
                )
            )
        self.assertEqual(results, ["답변", "답변"])
        self.factory.assert_called_once()
        self.assertEqual(
            len({call.args[0].user for call in self.client.call_args_list}), 2
        )

    def test_close_is_idempotent_and_never_initializes_unused_client(self):
        asyncio.run(self.answerer.aclose())
        self.factory.assert_not_called()
        self.client.aclose.assert_not_called()
        other = GenerationAnswerer(self.settings)
        other.answer("질문", snapshot())
        asyncio.run(other.aclose())
        asyncio.run(other.aclose())
        self.client.aclose.assert_awaited_once()

    def test_server_import_does_not_import_legacy_or_evaluation(self):
        code = """import sys
import app.fastapi_main
assert 'sanaebi_assistant' not in sys.modules
assert not any(k == 'archive.answering_v1' or k.startswith('archive.answering_v1.') for k in sys.modules)
assert not any(k == 'answer_pipeline' or k.startswith('answer_pipeline.') for k in sys.modules)
assert not any(k == 'generation_evaluation' or k.startswith('generation_evaluation.') for k in sys.modules)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_trace_callback_failure_does_not_replace_generation_result(self):
        from app.diagnostics import trace

        callback = trace.TraceCallback()
        token = trace._current_trace.set(callback)
        self.addCleanup(trace._current_trace.reset, token)
        with patch.object(callback, "record_generation", side_effect=OSError("secret")):
            self.assertEqual(self.answerer.answer("질문", snapshot()), "안내입니다.")
            self.client.return_value = ModelResponse("invalid")
            with self.assertRaises(LLMResponseError):
                self.answerer.answer("질문", snapshot())
        with patch.object(
            callback, "record_classification", side_effect=OSError("secret")
        ):
            trace.record_classification("CLARIFY")

    def test_trace_includes_safe_configuration_and_distinct_role_hash(self):
        from app.diagnostics import trace

        callback = trace.TraceCallback()
        token = trace._current_trace.set(callback)
        self.addCleanup(trace._current_trace.reset, token)
        self.answerer.answer("질문", snapshot())
        row = callback.record_rows("/ask", {"question": "질문"}, 200)[-1]
        self.assertEqual(row["config"]["reasoning_effort"], "xhigh")
        self.assertEqual(row["config"]["timeout_seconds"], 180)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(len(row["prompt_roles_sha256"]), 64)
        self.assertNotIn("prompt_sha256", row)
        self.assertIsNone(row["input"])
        self.assertIsNone(row["output"])
