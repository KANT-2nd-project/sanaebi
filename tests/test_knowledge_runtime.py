import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda

import sanaebi_assistant as runner
from app.documents.context import DocumentContextProvider, DocumentStorageError
from app.fastapi_main import app


class KnowledgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ, {"SANAEBI_DOCUMENT_DB": str(directory / "db.sqlite3")}
            )
        )
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))
        self.prompts = []

        def answer(prompt):
            self.prompts.append(prompt.to_string())
            return runner.AssistantResponse(
                answer="검증 답변", referenced_documents=["정책"], note=""
            )

        class FakeModel:
            def with_structured_output(self, schema):
                return RunnableLambda(answer)

        self.enterContext(
            patch.object(runner, "create_chat_model", return_value=FakeModel())
        )
        self.ready = self.enterContext(patch.object(runner, "ensure_ollama_server"))
        self.classify = self.enterContext(
            patch.object(
                app.state.classifier, "predict", return_value="SEARCH_KNOWLEDGE"
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

    def test_create_publish_edit_publish_withdraw_changes_prompt(self):
        doc = self.write(
            "POST", "/documents", {"title": "정책", "body": "첫번째 정책 본문"}
        )
        self.assertEqual(self.ask().status_code, 200)
        self.assertEqual(self.prompts, [])
        key = doc["id"]
        doc = self.write(
            "POST",
            f"/documents/{key}/publish",
            {
                "expected_version": doc["record_version"],
                "revision_id": doc["draft"]["id"],
            },
        )
        self.assertEqual(self.ask().json()["text"], "검증 답변")
        self.assertIn("첫번째 정책 본문", self.prompts[-1])
        doc = self.write(
            "PATCH",
            f"/documents/{key}",
            {"expected_version": doc["record_version"], "body": "두번째 정책 본문"},
        )
        self.ask()
        self.assertIn("첫번째 정책 본문", self.prompts[-1])
        self.assertNotIn("두번째 정책 본문", self.prompts[-1])
        doc = self.write(
            "POST",
            f"/documents/{key}/publish",
            {
                "expected_version": doc["record_version"],
                "revision_id": doc["draft"]["id"],
            },
        )
        self.ask()
        self.assertIn("두번째 정책 본문", self.prompts[-1])
        self.write(
            "POST",
            f"/documents/{key}/withdraw",
            {"expected_version": doc["record_version"]},
        )
        before = len(self.prompts)
        self.ask()
        self.assertEqual(len(self.prompts), before)

    def test_storage_failure_503_is_not_empty_or_model_failure(self):
        with patch.object(
            app.state.document_provider,
            "snapshot",
            side_effect=DocumentStorageError("failure"),
        ):
            result = self.ask()
        self.assertEqual(result.status_code, 503)
        self.assertFalse(result.json()["ok"])
        self.assertEqual(self.prompts, [])

    def test_non_search_does_not_read_store(self):
        self.classify.return_value = "CLARIFY"
        with patch.object(
            app.state.document_provider,
            "snapshot",
            side_effect=AssertionError("unexpected read"),
        ):
            self.assertEqual(self.ask().status_code, 200)

    def test_both_providers_share_snapshot_even_if_document_changes(self):
        doc = self.write("POST", "/documents", {"title": "정책", "body": "같은 원문"})
        self.write(
            "POST",
            f"/documents/{doc['id']}/publish",
            {"expected_version": 1, "revision_id": doc["draft"]["id"]},
        )
        provider = app.state.document_provider
        with patch.object(provider, "snapshot", wraps=provider.snapshot) as snapshot:
            original = runner.create_chain
            counter = [0]

            def chain(*args, **kwargs):
                counter[0] += 1
                if counter[0] == 2:
                    with app.state.document_repository.transaction() as con:
                        app.state.document_repository.withdraw_in_transaction(
                            con, doc["id"], 2
                        )
                return original(*args, **kwargs)

            with patch.object(runner, "create_chain", side_effect=chain):
                response = self.client.post(
                    "/assistant",
                    json={
                        "response": {"ok": True, "text": "정책", "reason": ""},
                        "classification_label": "SEARCH_KNOWLEDGE",
                    },
                )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual(len(self.prompts), 2)
        self.assertTrue(all("같은 원문" in p for p in self.prompts))
        self.assertEqual(DocumentContextProvider().snapshot().documents, ())

    def test_empty_assistant_reports_no_model_call(self):
        response = self.client.post(
            "/assistant",
            json={
                "response": {"ok": True, "text": "정책", "reason": ""},
                "classification_label": "SEARCH_KNOWLEDGE",
            },
        )
        for result in response.json().values():
            self.assertFalse(result["model_called"])
            self.assertTrue(result["success"])
        self.ready.assert_not_called()
