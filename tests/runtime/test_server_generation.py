"""HTTP integration tests for the adopted server-side generation pipeline.

The real GenerationAnswerer, prompt builder, parser, API routes, and temporary
SQLite document store are exercised. Only the managed model client is fake.
"""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from openai import APIConnectionError, AuthenticationError, RateLimitError

from app import fastapi_main
from app.dependencies import get_classifier
from generation.types import GenerationPrompt, ModelResponse

VALID_JSON = '{"answer":"가상 생성 답변"}'


class FakeManagedGenerationClient:
    def __init__(self, response=None):
        self.response = response or ModelResponse(
            raw_text=VALID_JSON,
            input_tokens=17,
            output_tokens=6,
            finish_reason="stop",
        )
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


class ServerGenerationIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db_path = directory / "documents.sqlite3"
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(self.db_path),
                    "SANAEBI_ANSWER_PROVIDER": "openai",
                    "TRACE_DIR": "",
                },
            )
        )

        self.model_client = FakeManagedGenerationClient()
        self.build_client = self.enterContext(
            patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=self.model_client,
            )
        )
        self.classifier = Mock()
        self.classifier.predict.return_value = "SEARCH_KNOWLEDGE"
        self._original_overrides = fastapi_main.app.dependency_overrides.copy()
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: self.classifier
        self.addCleanup(self._restore_dependency_overrides)
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
        )

    def _restore_dependency_overrides(self):
        fastapi_main.app.dependency_overrides.clear()
        fastapi_main.app.dependency_overrides.update(self._original_overrides)

    @property
    def repository(self):
        return fastapi_main.app.state.document_repository

    def ask(self, question="규정 알려줘"):
        return self.client.post("/ask", json={"question": question})

    def assistant(self, question="규정 알려줘"):
        return self.client.post(
            "/assistant",
            json={
                "response": {"ok": True, "text": question, "reason": ""},
                "classification_label": "SEARCH_KNOWLEDGE",
            },
        )

    def create_draft(self, title="규정", body="게시된 원문"):
        return self.client.post(
            "/documents",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"title": title, "body": body},
        ).json()

    def publish(self, document):
        return self.client.post(
            f"/documents/{document['id']}/publish",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "expected_version": document["record_version"],
                "revision_id": document["draft"]["id"],
            },
        )

    def test_both_routes_use_real_generation_pipeline_and_reuse_managed_client(self):
        draft = self.create_draft()
        self.assertEqual(self.publish(draft).status_code, 200)

        responses = [self.ask(), self.assistant("다른 규정 알려줘")]

        for response in responses:
            with self.subTest(response=response.request.url.path):
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.json(),
                    {"ok": True, "text": "가상 생성 답변", "reason": ""},
                )
        self.assertEqual(self.classifier.predict.call_count, 1)
        self.build_client.assert_called_once()
        self.assertEqual(len(self.model_client.prompts), 2)
        self.assertIn("게시된 원문", self.model_client.prompts[0].user)
        self.assertIn(
            "질문에 답할 수 있는 범위를 구분하세요.",
            self.model_client.prompts[0].system,
        )

    def test_invalid_or_incomplete_generation_results_are_safe_502(self):
        draft = self.create_draft()
        self.assertEqual(self.publish(draft).status_code, 200)
        cases = (
            ("invalid JSON", ModelResponse(raw_text="not json")),
            ("additional key", ModelResponse(raw_text='{"answer":"ok","x":1}')),
            ("blank answer", ModelResponse(raw_text='{"answer":"   "}')),
            ("refusal", ModelResponse(raw_text=None, refusal="private refusal")),
            (
                "length stop",
                ModelResponse(
                    raw_text='{"answer":"부분 답변"}', finish_reason="length"
                ),
            ),
            ("timeout", TimeoutError("private timeout body")),
        )
        raw_values = ("not json", '"x":1', "부분 답변", "private refusal", "부분 답변")

        for index, (name, result) in enumerate(cases):
            with self.subTest(case=name):
                self.model_client.response = result
                response = self.ask(f"질문 {index}")
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["ok"], False)
                self.assertNotIn("private", response.text)
                self.assertNotIn("부분 답변", response.text)
                if index < len(raw_values):
                    self.assertNotIn(raw_values[index], response.text)
        self.assertEqual(len(self.model_client.prompts), len(cases))

    def test_openai_http_and_connection_errors_are_502_but_code_errors_are_500(self):
        draft = self.create_draft()
        self.assertEqual(self.publish(draft).status_code, 200)
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        errors = (
            (
                "401",
                AuthenticationError(
                    "private credential detail",
                    response=httpx.Response(
                        401, request=request, json={"error": "private"}
                    ),
                    body={"error": "private"},
                ),
            ),
            (
                "429",
                RateLimitError(
                    "private rate detail",
                    response=httpx.Response(
                        429, request=request, json={"error": "private"}
                    ),
                    body={"error": "private"},
                ),
            ),
            (
                "OpenAI connection",
                APIConnectionError(
                    message="private SDK connection detail", request=request
                ),
            ),
            (
                "connection",
                httpx.ConnectError("private connection detail", request=request),
            ),
        )

        for name, error in errors:
            with self.subTest(error=name):
                self.model_client.response = error
                response = self.ask()
                self.assertEqual(response.status_code, 502)
                self.assertNotIn("private", response.text)

        self.model_client.response = RuntimeError("private implementation detail")
        unexpected = self.ask()
        self.assertEqual(unexpected.status_code, 500)
        self.assertNotIn("private", unexpected.text)

    def test_empty_snapshot_does_not_initialize_or_call_model_client(self):
        for path, request_body in (
            ("/ask", {"question": "아직 게시 전인 규정 알려줘"}),
            (
                "/assistant",
                {
                    "response": {"ok": True, "text": "아직 게시 전인 규정 알려줘"},
                    "classification_label": "SEARCH_KNOWLEDGE",
                },
            ),
        ):
            with self.subTest(path=path):
                response = self.client.post(path, json=request_body)
                self.assertEqual(response.status_code, 200)
                self.assertIn("문서가 없어", response.json()["text"])
        self.build_client.assert_not_called()
        self.assertEqual(self.model_client.prompts, [])

    def test_draft_revision_publication_and_withdrawal_affect_the_next_request(self):
        draft = self.create_draft(body="첫 번째 게시 본문")
        response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.model_client.prompts, [])

        published = self.publish(draft)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(self.ask().status_code, 200)
        first_prompt = self.model_client.prompts[-1].user
        self.assertIn("첫 번째 게시 본문", first_prompt)

        edited = self.client.patch(
            f"/documents/{draft['id']}",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "expected_version": published.json()["record_version"],
                "body": "아직 초안인 두 번째 본문",
            },
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(self.ask().status_code, 200)
        self.assertIn("첫 번째 게시 본문", self.model_client.prompts[-1].user)
        self.assertNotIn("아직 초안인 두 번째 본문", self.model_client.prompts[-1].user)

        republished = self.publish(edited.json())
        self.assertEqual(republished.status_code, 200, republished.text)
        self.assertEqual(self.ask().status_code, 200)
        revised_prompt = self.model_client.prompts[-1].user
        self.assertIn("아직 초안인 두 번째 본문", revised_prompt)
        self.assertNotIn("첫 번째 게시 본문", revised_prompt)

        withdrawn = self.client.post(
            f"/documents/{draft['id']}/withdraw",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": republished.json()["record_version"]},
        )
        self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
        before_withdraw_request = len(self.model_client.prompts)
        answer = self.ask()
        self.assertEqual(answer.status_code, 200)
        self.assertIn("문서가 없어", answer.json()["text"])
        self.assertEqual(len(self.model_client.prompts), before_withdraw_request)

    def test_more_than_71_documents_and_long_body_reach_prompt_without_truncation(self):
        long_body = f"긴 문서 시작:{'본문' * 4096}:LONG_BODY_END_MARKER"
        repository = self.repository
        with repository.transaction() as connection:
            for index in range(72):
                document = repository.create_in_transaction(
                    connection,
                    {
                        "title": f"정책 문서 {index:02d}",
                        "body": long_body if index == 0 else f"본문 {index}",
                        "source_label": "통합 테스트",
                    },
                    document_id=str(uuid.uuid4()),
                )
                repository.publish_in_transaction(
                    connection,
                    document["id"],
                    document["record_version"],
                    document["draft"]["id"],
                )

        response = self.ask()
        self.assertEqual(response.status_code, 200, response.text)
        user_prompt = self.model_client.prompts[0].user
        self.assertEqual(user_prompt.count("문서 ID: "), 72)
        self.assertIn(long_body, user_prompt)
        self.assertIn("LONG_BODY_END_MARKER", user_prompt)

    def test_model_call_allows_document_write_and_keeps_held_snapshot(self):
        draft = self.create_draft(body="호출 중에도 유지될 snapshot 원문")
        published = self.publish(draft)
        self.assertEqual(published.status_code, 200)
        document_id = draft["id"]

        def withdraw_during_call(prompt):
            with self.repository.transaction() as connection:
                self.repository.withdraw_in_transaction(connection, document_id, 2)
            return ModelResponse(raw_text=VALID_JSON)

        self.model_client.response = withdraw_during_call
        response = self.ask()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(
            "호출 중에도 유지될 snapshot 원문", self.model_client.prompts[0].user
        )
        self.assertEqual(self.repository.published_snapshot(), [])

    def test_generation_settings_provider_defaults_and_invalid_values(self):
        for provider in (None, "openai"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp:
                env = {
                    "SANAEBI_DOCUMENT_DB": str(Path(temp) / "documents.sqlite3"),
                    "TRACE_DIR": "",
                }
                if provider is not None:
                    env["SANAEBI_ANSWER_PROVIDER"] = provider
                with (
                    patch.dict(os.environ, env, clear=True),
                    TestClient(fastapi_main.app) as client,
                ):
                    self.assertEqual(client.get("/").status_code, 200)

        for provider in ("ollama", "unknown"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp:
                env = {
                    "SANAEBI_DOCUMENT_DB": str(Path(temp) / "documents.sqlite3"),
                    "SANAEBI_ANSWER_PROVIDER": provider,
                    "TRACE_DIR": "",
                }
                with (
                    self.assertRaises(ValueError),
                    patch.dict(os.environ, env, clear=True),
                    TestClient(fastapi_main.app),
                ):
                    pass


if __name__ == "__main__":
    unittest.main()
