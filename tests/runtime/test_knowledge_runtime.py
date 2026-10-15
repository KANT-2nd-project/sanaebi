"""Runtime tests for published SQLite snapshots and the managed generator."""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.fastapi_main import app
from generation.types import GenerationPrompt, ModelResponse


class FakeManagedGenerationClient:
    def __init__(self):
        self.prompts: list[GenerationPrompt] = []
        self.on_call = None
        self.closed = False

    def __call__(self, prompt: GenerationPrompt) -> ModelResponse:
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(prompt)
        return ModelResponse(
            raw_text=json.dumps({"answer": "검증 답변"}, ensure_ascii=False),
            input_tokens=12,
            output_tokens=5,
            finish_reason="stop",
        )

    async def aclose(self):
        self.closed = True


class KnowledgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(directory / "db.sqlite3"),
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
        self.classify = self.enterContext(
            patch.object(
                app.state.classifier,
                "predict",
                return_value="SEARCH_KNOWLEDGE",
            )
        )

    def write(self, method, path, payload):
        response = self.client.request(
            method, path, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())}
        )
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def ask(self):
        return self.client.post("/ask", json={"question": "정책 알려줘"})

    def assistant(self):
        return self.client.post(
            "/assistant",
            json={
                "response": {"ok": True, "text": "정책 알려줘", "reason": ""},
                "classification_label": "SEARCH_KNOWLEDGE",
            },
        )

    def test_storage_failure_is_503_not_empty_or_model_failure(self):
        with patch.object(
            app.state.document_provider.repository,
            "published_snapshot",
            side_effect=sqlite3.OperationalError("storage failure"),
        ):
            response = self.ask()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])
        self.assertIn("문서 저장소", response.json()["reason"])
        self.factory.assert_not_called()
        self.assertEqual(self.model_client.prompts, [])

    def test_gate_non_search_label_does_not_read_documents_or_initialize_model(self):
        self.classify.return_value = "CLARIFY"
        with (
            patch.object(app.state, "routing_mode", "gate"),
            patch.object(
                app.state.document_provider,
                "snapshot",
                side_effect=AssertionError("non-search label read the store"),
            ),
        ):
            response = self.ask()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.factory.assert_not_called()
        self.assertEqual(self.model_client.prompts, [])

    def test_one_managed_client_keeps_request_snapshot_during_concurrent_withdrawal(
        self,
    ):
        document = self.write(
            "POST", "/documents", {"title": "정책", "body": "호출 중에도 유지될 원문"}
        )
        published = self.write(
            "POST",
            f"/documents/{document['id']}/publish",
            {
                "expected_version": document["record_version"],
                "revision_id": document["draft"]["id"],
            },
        )
        repository = app.state.document_repository

        def withdraw_after_prompt_was_built(_prompt):
            with repository.transaction() as connection:
                repository.withdraw_in_transaction(
                    connection, document["id"], published["record_version"]
                )

        self.model_client.on_call = withdraw_after_prompt_was_built
        provider = app.state.document_provider
        with patch.object(provider, "snapshot", wraps=provider.snapshot) as snapshot:
            response = self.assistant()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["text"], "검증 답변")
        snapshot.assert_called_once_with()
        self.factory.assert_called_once()
        self.assertEqual(len(self.model_client.prompts), 1)
        self.assertIn("호출 중에도 유지될 원문", self.model_client.prompts[0].user)
        self.assertEqual(provider.snapshot().documents, ())

        self.model_client.on_call = None
        later_response = self.assistant()
        self.assertEqual(later_response.status_code, 200, later_response.text)
        self.assertIn("문서가 없어", later_response.json()["text"])
        self.assertEqual(len(self.model_client.prompts), 1)
        self.factory.assert_called_once()

    def test_empty_search_snapshot_has_safe_answer_without_model_call(self):
        response = self.assistant()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["text"],
            "현재 확인 가능한 회사 문서가 없어 답변하기 어렵습니다.",
        )
        self.factory.assert_not_called()
        self.assertEqual(self.model_client.prompts, [])


if __name__ == "__main__":
    unittest.main()
