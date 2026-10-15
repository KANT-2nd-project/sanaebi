"""Exercise selected evidence through the real API, adapter and JSON parser."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import fastapi_main
from app.dependencies import get_classifier
from app.retrieval.types import (
    RetrievalInputTooLong,
    RetrievalNotReady,
    RetrievalUnavailable,
)
from tests.runtime.test_server_generation import FakeManagedGenerationClient


class RagHttpTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(root / "documents.sqlite3"),
                    "SANAEBI_RETRIEVAL_MODE": "full",
                    "SANAEBI_PUBLIC_DEMO": "0",
                    "SANAEBI_ROUTING_MODE": "shadow",
                    "TRACE_DIR": "",
                },
            )
        )
        self.provider = FakeManagedGenerationClient()
        self.enterContext(
            patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=self.provider,
            )
        )
        previous = fastapi_main.app.dependency_overrides.copy()
        self.addCleanup(
            lambda: (
                fastapi_main.app.dependency_overrides.clear(),
                fastapi_main.app.dependency_overrides.update(previous),
            )
        )
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: Mock(
            predict=Mock(return_value="CLARIFY")
        )
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
        )
        app = fastapi_main.app
        doc = self.client.post(
            "/documents",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"title": "규정", "body": "선택할 근거. 전달하지 않을 비밀 문단."},
        ).json()
        self.client.post(
            f"/documents/{doc['id']}/publish",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "expected_version": doc["record_version"],
                "revision_id": doc["draft"]["id"],
            },
        ).raise_for_status()
        self.snapshot = app.state.document_provider.snapshot()
        self.context = SimpleNamespace(
            snapshot_fingerprint=self.snapshot.fingerprint,
            evidence=(
                SimpleNamespace(
                    knowledge_id="policy", title="규정", revision=1, text="선택할 근거."
                ),
            ),
        )
        self.retriever = Mock()
        self.retriever.retrieve.return_value = self.context
        self.retriever.status.return_value = {"ready": True}
        app.state.retriever = self.retriever
        self.reserve = Mock()
        app.state.answerer.reserve_generation = self.reserve

    def ask(self):
        return self.client.post("/ask", json={"question": "규정?"})

    def test_both_paths_render_only_selected_evidence_and_reserve_once(self):
        responses = [
            self.ask(),
            self.client.post(
                "/assistant",
                json={
                    "response": {"ok": True, "text": "규정?"},
                    "classification_label": "UNSUPPORTED",
                },
            ),
        ]
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(self.reserve.call_count, 2)
        self.assertEqual(self.retriever.retrieve.call_count, 2)
        for prompt in self.provider.prompts:
            self.assertIn("선택할 근거.", prompt.user)
            self.assertNotIn("비밀 문단", prompt.user)

    def test_safe_error_boundaries_and_no_generation_budget(self):
        for error, code in (
            (RetrievalNotReady("private/path"), 503),
            (RetrievalUnavailable("secret"), 503),
            (RetrievalInputTooLong("raw question"), 422),
            (RuntimeError("programming error"), 500),
        ):
            with self.subTest(code=code, error=type(error).__name__):
                self.retriever.retrieve.side_effect = error
                response = self.ask()
                self.assertEqual(response.status_code, code)
                self.assertNotIn(str(error), response.text)
                if isinstance(error, RetrievalNotReady):
                    self.assertEqual(response.headers["Retry-After"], "3")
        self.reserve.assert_not_called()
        self.assertEqual(self.provider.prompts, [])

    def test_ready_checks_index_without_retrieving_or_reserving(self):
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test"}),
            patch.object(
                fastapi_main.app.state.classifier,
                "predict",
                return_value="SEARCH_KNOWLEDGE",
            ),
        ):
            self.assertEqual(self.client.get("/health/ready").status_code, 200)
            self.retriever.status.return_value = {"ready": False}
            self.assertEqual(self.client.get("/health/ready").status_code, 503)
        self.retriever.retrieve.assert_not_called()
        self.reserve.assert_not_called()

    def test_upstream_failure_bypasses_retrieval(self):
        response = self.client.post(
            "/assistant",
            json={
                "response": {"ok": False, "text": ""},
                "classification_label": "CLARIFY",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.retriever.retrieve.assert_not_called()
        self.reserve.assert_not_called()


class AdvisoryRagHttpTests(RagHttpTests):
    def setUp(self):
        super().setUp()
        fastapi_main.app.state.routing_mode = "advisory"

    def test_only_server_prediction_is_in_prompt_and_fallback_is_exact(self):
        from app.classification.errors import ClassificationUnavailable
        from generation.advisory import ClassificationContext, compose_advisory

        self.assertEqual(self.ask().status_code, 200)
        server_prompt = self.provider.prompts[-1]
        client_response = self.client.post(
            "/assistant",
            json={
                "response": {"ok": True, "text": "규정?"},
                "classification_label": "UNSUPPORTED",
            },
        )
        self.assertEqual(client_response.status_code, 200)
        original = self.provider.prompts[-1]
        self.assertEqual(
            server_prompt, compose_advisory(original, ClassificationContext("CLARIFY"))
        )
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: Mock(
            predict=Mock(side_effect=ClassificationUnavailable("private"))
        )
        self.assertEqual(self.ask().status_code, 200)
        self.assertEqual(self.provider.prompts[-1], original)
        self.assertEqual(set(client_response.json()), {"ok", "text", "reason"})
