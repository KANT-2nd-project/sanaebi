import asyncio
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from app.answering.adapter import GenerationAnswerer
from app.answering.output import LLMResponseError
from app.documents.context import DocumentContextSnapshot, DocumentStorageError
from app.public_limits import GenerationBudgetExceeded
from app.questions.service import handle_classified_question, handle_question
from app.retrieval.types import RetrievalNotReady, RetrievedContext
from generation.presets import load_runtime_settings
from generation.profiles import RAG_PROMPT_PROFILE
from generation.types import ModelResponse
from tests.runtime.test_server_generation import FakeManagedGenerationClient


class EmptyRagTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = DocumentContextSnapshot(())
        self.context = RetrievedContext(
            self.snapshot.fingerprint,
            "spec",
            (),
            0,
            0,
            datetime.now(UTC),
            source_document_count=0,
        )
        settings = replace(
            load_runtime_settings(Path.cwd()), prompt_profile=RAG_PROMPT_PROFILE
        )
        self.reserve = Mock()
        self.answerer = GenerationAnswerer(settings, self.reserve)
        self.addCleanup(lambda: asyncio.run(self.answerer.aclose()))
        self.client = FakeManagedGenerationClient()
        self.enterContext(
            patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=self.client,
            )
        )
        self.read = Mock(return_value=self.snapshot)
        self.retrieve = Mock(return_value=self.context)

    def call(self, **kwargs):
        return handle_question(
            "안녕하세요",
            classify=Mock(return_value="CLARIFY"),
            read_documents=self.read,
            retrieve=self.retrieve,
            answer=self.answerer.answer_retrieved,
            routing_mode="advisory",
            allow_empty_retrieval=True,
            **kwargs,
        )

    def test_empty_published_goes_to_real_adapter_and_reserves_once(self):
        self.call()
        self.assertEqual(len(self.client.prompts), 1)
        self.assertIn("게시 문서 없음", self.client.prompts[0].system)
        self.reserve.assert_called_once()
        self.read.assert_called_once()

    def test_no_matches_has_distinct_state_and_assistant_path(self):
        self.context = replace(self.context, source_document_count=1)
        self.retrieve.return_value = self.context
        result = handle_classified_question(
            "안녕",
            "UNSUPPORTED",
            read_documents=self.read,
            retrieve=self.retrieve,
            answer=self.answerer.answer_retrieved,
            routing_mode="advisory",
            allow_empty_retrieval=True,
        )
        self.assertTrue(result.text)
        self.assertIn("검색 결과 없음", self.client.prompts[0].system)

    def test_storage_and_index_failures_do_not_generate(self):
        for error in [DocumentStorageError("safe"), RetrievalNotReady("safe")]:
            with self.subTest(error=type(error).__name__):
                self.retrieve.side_effect = error
                with self.assertRaises(type(error)):
                    self.call()
        self.reserve.assert_not_called()
        self.assertEqual(self.client.prompts, [])

    def test_gate_nonsearch_does_not_retrieve_or_generate(self):
        handle_classified_question(
            "안녕",
            "CLARIFY",
            read_documents=self.read,
            retrieve=self.retrieve,
            answer=self.answerer.answer_retrieved,
            routing_mode="gate",
            allow_empty_retrieval=True,
        )
        self.read.assert_not_called()
        self.reserve.assert_not_called()

    def test_budget_error_no_model_call(self):
        self.reserve.side_effect = GenerationBudgetExceeded(60)
        with self.assertRaises(GenerationBudgetExceeded):
            self.call()
        self.assertEqual(self.client.prompts, [])

    def test_invalid_json_remains_failure(self):
        self.client.response = ModelResponse(raw_text="not json", finish_reason="stop")
        with self.assertRaises(LLMResponseError):
            self.call()
        self.assertEqual(len(self.client.prompts), 1)

    def test_legacy_profile_still_rejects_empty(self):
        old = GenerationAnswerer(load_runtime_settings(Path.cwd()))
        with self.assertRaises(ValueError):
            old.answer_retrieved("안녕", self.context)
        self.assertIsNone(old._client)

    def test_both_http_routes_use_real_empty_rag_pipeline(self):
        import os

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.answering.router import router as assistant_router
        from app.errors import register_error_handlers
        from app.questions.router import router as questions_router

        app = FastAPI()
        register_error_handlers(app)
        app.include_router(questions_router)
        app.include_router(assistant_router)
        app.state.classifier = Mock(predict=Mock(return_value="CLARIFY"))
        app.state.document_provider = Mock(snapshot=self.read)
        app.state.retriever = Mock(retrieve=self.retrieve)
        app.state.answerer = self.answerer
        app.state.routing_mode = "advisory"
        with (
            patch.dict(os.environ, {"SANAEBI_PUBLIC_DEMO": "0"}),
            TestClient(app) as client,
        ):
            for route, payload in [
                ("/ask", {"question": "안녕"}),
                (
                    "/assistant",
                    {
                        "response": {"ok": True, "text": "안녕"},
                        "classification_label": "UNSUPPORTED",
                    },
                ),
            ]:
                response = client.post(route, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["ok"])
            self.assertEqual(len(self.client.prompts), 2)
            self.retrieve.side_effect = RetrievalNotReady("safe")
            self.assertEqual(
                client.post("/ask", json={"question": "안녕"}).status_code, 503
            )
            self.assertEqual(len(self.client.prompts), 2)
            self.retrieve.side_effect = None
            self.client.response = ModelResponse(raw_text="bad", finish_reason="stop")
            self.assertEqual(
                client.post("/ask", json={"question": "안녕"}).status_code, 502
            )

    def test_rag_profile_setting_default_rollback_and_invalid(self):
        import os

        from app.settings import get_rag_prompt_profile
        from generation.profiles import (
            DEFAULT_PROMPT_PROFILE,
            RAG_READABILITY_V7_PROFILE,
        )

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_rag_prompt_profile(), RAG_READABILITY_V7_PROFILE)
            os.environ["SANAEBI_RAG_PROMPT_PROFILE"] = RAG_PROMPT_PROFILE
            self.assertEqual(get_rag_prompt_profile(), RAG_PROMPT_PROFILE)
            os.environ["SANAEBI_RAG_PROMPT_PROFILE"] = DEFAULT_PROMPT_PROFILE
            self.assertEqual(get_rag_prompt_profile(), DEFAULT_PROMPT_PROFILE)
            os.environ["SANAEBI_RAG_PROMPT_PROFILE"] = "unknown"
            with self.assertRaises(ValueError):
                get_rag_prompt_profile()

    def test_expansion_setting_default_rollback_and_invalid(self):
        import os

        from app.settings import get_rag_expand_context

        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(get_rag_expand_context())
            os.environ["SANAEBI_RAG_EXPAND_CONTEXT"] = "0"
            self.assertFalse(get_rag_expand_context())
            os.environ["SANAEBI_RAG_EXPAND_CONTEXT"] = "invalid"
            with self.assertRaises(ValueError):
                get_rag_expand_context()
