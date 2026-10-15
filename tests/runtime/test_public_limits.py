"""Regression tests for public demo quotas, rate limits, and health checks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from unittest.mock import Mock, patch

import anyio
from fastapi.testclient import TestClient

from app import fastapi_main
from app.dependencies import get_classifier
from app.documents.context import DocumentContext, DocumentContextSnapshot
from app.public_limits import DailyGenerationBudget, GenerationBudgetExceeded
from app.questions.router import _run_handler_and_release_slot
from generation.types import ModelResponse


class FakeGenerationClient:
    def __init__(self):
        self.prompts = []
        self.next_error = None
        self.response = ModelResponse(raw_text='{"answer":"가상 답변"}')

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.next_error is not None:
            error, self.next_error = self.next_error, None
            raise error
        return self.response

    async def aclose(self):
        pass


def published_snapshot() -> DocumentContextSnapshot:
    body = "게시된 시험 문서"
    return DocumentContextSnapshot(
        (
            DocumentContext(
                document_id="document-1",
                knowledge_id="knowledge-1",
                revision_id="revision-1",
                revision=1,
                title="시험 정책",
                body=body,
                source_reference="document:knowledge-1",
                content_hash=hashlib.sha256(body.encode()).hexdigest(),
                metadata=MappingProxyType({}),
            ),
        )
    )


class PublicDemoApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.env = self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_PUBLIC_DEMO": "1",
                    "SANAEBI_GENERATION_BUDGET_DB": str(
                        self.directory / "generation-budget.sqlite3"
                    ),
                    "SANAEBI_DAILY_GENERATION_LIMIT": "1",
                    "SANAEBI_DOCUMENT_DB": str(self.directory / "documents.sqlite3"),
                    "SANAEBI_ANSWER_PROVIDER": "openai",
                    "OPENAI_API_KEY": "test-key",
                    "TRACE_DIR": "",
                },
            )
        )
        self.classifier = Mock()
        self.classifier.predict.return_value = "CLARIFY"
        self._original_overrides = fastapi_main.app.dependency_overrides.copy()
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: self.classifier
        self.addCleanup(self._restore_dependency_overrides)
        self.model_client = FakeGenerationClient()
        self.build_model_client = self.enterContext(
            patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=self.model_client,
            )
        )

    def _restore_dependency_overrides(self):
        fastapi_main.app.dependency_overrides.clear()
        fastapi_main.app.dependency_overrides.update(self._original_overrides)

    def _client(self, ip: str):
        return TestClient(
            fastapi_main.app,
            raise_server_exceptions=False,
            client=(ip, 41000),
        )

    def _ask(self, ip: str, label: str, snapshot=None):
        self.classifier.predict.return_value = label
        with self._client(ip) as client:
            if snapshot is not None:
                with patch.object(
                    fastapi_main.app.state.document_provider,
                    "snapshot",
                    return_value=snapshot,
                ):
                    return client.post("/ask", json={"question": "시험 질문"})
            return client.post("/ask", json={"question": "시험 질문"})

    def test_ask_and_document_write_limits_return_retryable_responses(self):
        with self._client("198.51.100.41") as client:
            responses = [
                client.post("/ask", json={"question": "확인"}) for _ in range(4)
            ]
            self.assertEqual(
                [response.status_code for response in responses[:3]], [200] * 3
            )
            limited = responses[3]
            self.assertEqual(limited.status_code, 429)
            self.assertGreaterEqual(int(limited.headers["retry-after"]), 1)
            self.assertEqual(set(limited.json()), {"ok", "text", "reason"})
            self.assertFalse(limited.json()["ok"])

        with self._client("198.51.100.42") as client:
            writes = [
                client.post(
                    "/documents",
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    json={"title": f"문서 {index}", "body": f"본문 {index}"},
                )
                for index in range(6)
            ]
        self.assertEqual([response.status_code for response in writes[:5]], [201] * 5)
        self.assertEqual(writes[5].status_code, 429)
        self.assertGreaterEqual(int(writes[5].headers["retry-after"]), 1)

    def test_daily_budget_counts_only_actual_generation_attempts(self):
        with patch.dict(os.environ, {"SANAEBI_ROUTING_MODE": "gate"}):
            fixed = self._ask("198.51.100.51", "CLARIFY", published_snapshot())
        self.assertEqual(fixed.status_code, 200)

        empty = self._ask(
            "198.51.100.52", "SEARCH_KNOWLEDGE", DocumentContextSnapshot(())
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(len(self.model_client.prompts), 0)

        generated = self._ask("198.51.100.53", "SEARCH_KNOWLEDGE", published_snapshot())
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(len(self.model_client.prompts), 1)

        exhausted = self._ask("198.51.100.54", "SEARCH_KNOWLEDGE", published_snapshot())
        self.assertEqual(exhausted.status_code, 429)
        self.assertGreaterEqual(int(exhausted.headers["retry-after"]), 1)
        self.assertEqual(len(self.model_client.prompts), 1)
        self.assertEqual(set(exhausted.json()), {"ok", "text", "reason"})

    def test_shadow_counts_generation_for_all_classification_labels(self):
        with patch.dict(
            os.environ,
            {"SANAEBI_ROUTING_MODE": "shadow", "SANAEBI_DAILY_GENERATION_LIMIT": "2"},
        ):
            for ip, label in (
                ("198.51.100.71", "CLARIFY"),
                ("198.51.100.72", "UNSUPPORTED"),
            ):
                response = self._ask(ip, label, published_snapshot())
                self.assertEqual(response.status_code, 200, response.text)
            exhausted = self._ask(
                "198.51.100.73", "SEARCH_KNOWLEDGE", published_snapshot()
            )
        self.assertEqual(exhausted.status_code, 429)
        self.assertEqual(len(self.model_client.prompts), 2)

    def test_failed_provider_attempt_consumes_the_daily_budget(self):
        self.model_client.next_error = TimeoutError("private provider details")
        failed = self._ask("198.51.100.55", "SEARCH_KNOWLEDGE", published_snapshot())
        self.assertEqual(failed.status_code, 502)
        self.assertNotIn("private", failed.text)
        self.assertEqual(len(self.model_client.prompts), 1)

        exhausted = self._ask("198.51.100.56", "SEARCH_KNOWLEDGE", published_snapshot())
        self.assertEqual(exhausted.status_code, 429)
        self.assertEqual(len(self.model_client.prompts), 1)

    def test_generation_logs_safe_metadata_without_trace_directory(self):
        question = "PRIVATE-QUESTION-84bde2"
        answer = "PRIVATE-ANSWER-d1ae01"
        self.classifier.predict.return_value = "SEARCH_KNOWLEDGE"
        self.model_client.response = ModelResponse(
            raw_text=json.dumps({"answer": answer}),
            input_tokens=23,
            output_tokens=7,
            finish_reason="stop",
        )

        with (
            patch.dict(os.environ),
            self.assertLogs("uvicorn.error", level="INFO") as captured,
            self._client("198.51.100.57") as client,
            patch.object(
                fastapi_main.app.state.document_provider,
                "snapshot",
                return_value=published_snapshot(),
            ),
        ):
            os.environ.pop("TRACE_DIR", None)
            response = client.post("/ask", json={"question": question})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["text"], answer)
        [record] = captured.records
        metadata = json.loads(record.getMessage())
        self.assertEqual(
            set(metadata),
            {
                "event",
                "status",
                "provider_attempted",
                "input_tokens",
                "output_tokens",
                "seconds",
            },
        )
        self.assertEqual(metadata["event"], "generation_result")
        self.assertEqual(metadata["status"], "completed")
        self.assertTrue(metadata["provider_attempted"])
        self.assertEqual(metadata["input_tokens"], 23)
        self.assertEqual(metadata["output_tokens"], 7)
        self.assertIsInstance(metadata["seconds"], float)
        self.assertNotIn(question, record.getMessage())
        self.assertNotIn(answer, record.getMessage())

    def test_generation_metadata_uses_default_uvicorn_info_logging(self):
        script = """
import logging
import logging.config
from uvicorn.config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
from app.answering.adapter import logger

if logger.getEffectiveLevel() != logging.INFO:
    raise RuntimeError(f"unexpected effective level: {logger.getEffectiveLevel()}")
logger.info('{"event":"generation_result","status":"completed","provider_attempted":true,"input_tokens":23,"output_tokens":7,"seconds":0.01}')
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            'INFO:     {"event":"generation_result","status":"completed"',
            result.stderr,
        )

    def test_health_endpoints_warm_classifier_once_without_generation(self):
        warm_classifier = Mock()
        warm_classifier.predict.return_value = "CLARIFY"
        with self._client("198.51.100.61") as client:
            fastapi_main.app.state.classifier = warm_classifier
            with patch.object(
                fastapi_main.app.state.document_provider,
                "snapshot",
                return_value=DocumentContextSnapshot(()),
            ) as read_documents:
                self.assertEqual(client.get("/health/live").status_code, 200)
                first = client.get("/health/ready")
                second = client.get("/health/ready")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(warm_classifier.predict.call_count, 1)
        self.assertEqual(read_documents.call_count, 2)
        self.assertEqual(len(self.model_client.prompts), 0)

    def test_readiness_reports_missing_generation_configuration(self):
        with self._client("198.51.100.62") as client:
            fastapi_main.app.state.classifier = Mock()
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "not_ready"})

    def test_ask_inflight_limit_rejects_without_waiting(self):
        worker_started = threading.Event()
        release_worker = threading.Event()
        active = 0
        active_lock = threading.Lock()

        def blocking_classifier(question):
            nonlocal active
            with active_lock:
                active += 1
                if active == 2:
                    worker_started.set()
            release_worker.wait(timeout=5)
            with active_lock:
                active -= 1
            return "CLARIFY"

        self.classifier.predict.side_effect = blocking_classifier
        with (
            self._client("198.51.100.63") as client,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(client.post, "/ask", json={"question": "첫 질문"})
            second = executor.submit(
                client.post, "/ask", json={"question": "둘째 질문"}
            )
            self.assertTrue(worker_started.wait(timeout=3))
            rejected = client.post("/ask", json={"question": "셋째 질문"})
            self.assertEqual(rejected.status_code, 429)
            self.assertIn("현재 질문 요청", rejected.json()["reason"])
            release_worker.set()
            self.assertEqual(first.result(timeout=3).status_code, 200)
            self.assertEqual(second.result(timeout=3).status_code, 200)

    def test_cancelled_request_keeps_slot_until_sync_worker_finishes(self):
        slots = threading.BoundedSemaphore(1)
        self.assertTrue(slots.acquire(blocking=False))
        worker_started = threading.Event()
        worker_finished = threading.Event()
        release_worker = threading.Event()

        def blocking_handler(question):
            worker_started.set()
            release_worker.wait(timeout=5)
            worker_finished.set()
            return question

        async def scenario():
            task = asyncio.create_task(
                _run_handler_and_release_slot(blocking_handler, "질문", slots)
            )
            self.assertTrue(await anyio.to_thread.run_sync(worker_started.wait, 3))
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(slots.acquire(blocking=False))
            release_worker.set()
            with suppress(asyncio.CancelledError):
                await task
            self.assertTrue(await anyio.to_thread.run_sync(worker_finished.wait, 3))
            for _ in range(100):
                if slots.acquire(blocking=False):
                    return
                await asyncio.sleep(0.01)
            self.fail("the worker completion callback did not release the slot")

        anyio.run(scenario)


class DailyGenerationBudgetTests(unittest.TestCase):
    def test_atomic_reservations_persist_and_roll_over_at_kst_midnight(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "budget.sqlite3"
            current = [datetime(2026, 10, 15, 14, 59, 59, tzinfo=UTC)]
            budget = DailyGenerationBudget(
                database_path,
                daily_limit=3,
                clock=lambda: current[0],
            )
            budget.initialize()

            def reserve_once():
                try:
                    budget.reserve()
                except GenerationBudgetExceeded:
                    return False
                return True

            with ThreadPoolExecutor(max_workers=12) as executor:
                results = list(executor.map(lambda _: reserve_once(), range(12)))
            self.assertEqual(sum(results), 3)

            restarted = DailyGenerationBudget(
                database_path,
                daily_limit=3,
                clock=lambda: current[0],
            )
            restarted.initialize()
            with self.assertRaises(GenerationBudgetExceeded) as raised:
                restarted.reserve()
            self.assertEqual(raised.exception.retry_after, 1)

            current[0] += timedelta(seconds=1)
            restarted.reserve()


class AskWorkerContextTests(unittest.TestCase):
    def test_executor_preserves_context_vars(self):
        request_context = ContextVar("request_context", default=None)
        slots = threading.BoundedSemaphore(1)

        async def scenario():
            self.assertTrue(slots.acquire(blocking=False))
            token = request_context.set("trace-id-from-request-context")
            try:
                return await _run_handler_and_release_slot(
                    lambda _question: request_context.get(), "질문", slots
                )
            finally:
                request_context.reset(token)

        self.assertEqual(anyio.run(scenario), "trace-id-from-request-context")


if __name__ == "__main__":
    unittest.main()
