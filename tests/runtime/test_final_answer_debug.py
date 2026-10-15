"""Current HTTP generation and explicit snapshot regression checks."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.fastapi_main import app
from generation.documents import load_documents
from generation.types import GenerationPrompt, ModelResponse

ANSWER = "인사 시스템에서 신청하세요."
VALID_JSON = '{"answer":"인사 시스템에서 신청하세요."}'


class FakeManagedGenerationClient:
    def __init__(self, response=None):
        self.response = response or ModelResponse(raw_text=VALID_JSON)
        self.prompts: list[GenerationPrompt] = []
        self.closed = False

    def __call__(self, prompt: GenerationPrompt) -> ModelResponse:
        self.prompts.append(prompt)
        if isinstance(self.response, BaseException):
            raise self.response
        if callable(self.response):
            return self.response(prompt)
        return self.response

    async def aclose(self):
        self.closed = True


class OfflineSnapshotFileTests(unittest.TestCase):
    """Explicit CLI/legacy JSONL errors stay local and are not HTTP 502 errors."""

    def test_missing_offline_snapshot_raises_in_the_offline_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "missing.jsonl"
            with self.assertRaises(FileNotFoundError):
                load_documents(snapshot)


class ActiveHttpGenerationTests(unittest.TestCase):
    """The server route runs the production generation path with no network."""

    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(directory / "documents.sqlite3"),
                    "SANAEBI_RETRIEVAL_MODE": "full",
                    "SANAEBI_ANSWER_PROVIDER": "openai",
                    "TRACE_DIR": "",
                },
            )
        )
        self.model_client = FakeManagedGenerationClient()
        self.factory = self.enterContext(
            patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=self.model_client,
            )
        )
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))
        self.classifier = self.enterContext(
            patch.object(
                app.state.classifier,
                "predict",
                return_value="SEARCH_KNOWLEDGE",
            )
        )

    def _write(self, method, path, payload):
        response = self.client.request(
            method,
            path,
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def test_real_generation_pipeline_returns_only_parsed_answer(self):
        draft = self._write(
            "POST",
            "/documents",
            {"title": "연차 신청", "body": "연차는 인사 시스템에서 신청한다."},
        )
        published = self._write(
            "POST",
            f"/documents/{draft['id']}/publish",
            {
                "expected_version": draft["record_version"],
                "revision_id": draft["draft"]["id"],
            },
        )

        response = self.client.post(
            "/ask", json={"question": "연차는 어디서 신청해요?"}
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True, "text": ANSWER, "reason": ""})
        self.assertEqual(self.classifier.call_count, 1)
        self.factory.assert_called_once()
        self.assertEqual(len(self.model_client.prompts), 1)
        prompt = self.model_client.prompts[0]
        self.assertIn("연차는 어디서 신청해요?", prompt.user)
        self.assertIn("연차는 인사 시스템에서 신청한다.", prompt.user)
        self.assertEqual(published["record_version"], 2)


if __name__ == "__main__":
    unittest.main()
