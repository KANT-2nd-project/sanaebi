"""RAG maintenance must not serve stale vectors or reserve generation early."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar
from unittest.mock import Mock, patch

import numpy as np

from fastapi.testclient import TestClient

from app import fastapi_main
from app.dependencies import get_classifier
from app.retrieval.baseline import prepare_baseline
from app.retrieval.service import RetrievalService
from generation.types import ModelResponse
from tests.retrieval.helpers import FakeEmbedder
from tests.runtime.test_server_generation import FakeManagedGenerationClient


def _row(body: str) -> dict[str, object]:
    return {
        "document_id": "readiness-policy",
        "category": "test",
        "policy_decision_ids": ["D-TEST-001"],
        "source_ids": ["T-TEST-001"],
        "version": "1.0.0",
        "review_status": "ai_reviewed",
        "title": "RAG readiness policy",
        "document": body,
    }


def _write_source(path: Path, body: str) -> None:
    path.write_text(json.dumps(_row(body), ensure_ascii=False) + "\n", encoding="utf-8")


class MatchingEmbedder(FakeEmbedder):
    """Readiness tests use a known relevant vector; ranking has separate tests."""

    @staticmethod
    def _vector(text):
        vector = np.zeros(384, dtype=np.float32)
        vector[0] = 1.0
        return vector


class RuntimeFakeEmbedder(MatchingEmbedder):
    instances: ClassVar[list[RuntimeFakeEmbedder]] = []

    def __init__(self, path: str | Path):
        super().__init__()
        self.path = Path(path)
        self.warmup_calls = 0
        self.__class__.instances.append(self)

    def warmup(self):
        self.warmup_calls += 1


class RagFollowupReadinessTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = root / "company-documents.jsonl"
        self.baseline_text = (
            "## 출근 정책\n\nBASELINE-CONTENT: 출근 기록은 사내 포털에 남긴다.\n"
        )
        _write_source(self.source, self.baseline_text)
        self.bundle = prepare_baseline(
            self.source, root / "baseline-bundles", MatchingEmbedder()
        )
        RuntimeFakeEmbedder.instances.clear()

        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(root / "documents.sqlite3"),
                    "SANAEBI_GENERATION_BUDGET_DB": str(root / "budget.sqlite3"),
                    "SANAEBI_RETRIEVAL_ROOT": str(root / "retrieval"),
                    "SANAEBI_RETRIEVAL_BASELINE": str(self.bundle),
                    "SANAEBI_RETRIEVAL_SOURCE": str(self.source),
                    "SANAEBI_EMBEDDING_PATH": str(root / "fake-model"),
                    "SANAEBI_RETRIEVAL_MODE": "rag",
                    "SANAEBI_ROUTING_MODE": "gate",
                    "SANAEBI_PUBLIC_DEMO": "0",
                    "SANAEBI_ANSWER_PROVIDER": "openai",
                    "OPENAI_API_KEY": "test-key",
                    "TRACE_DIR": "",
                },
            )
        )
        self.enterContext(
            patch("app.documents.router.DEFAULT_DOCUMENTS_PATH", self.source)
        )
        self.enterContext(
            patch("app.retrieval.embedding.TinyEmbedder", RuntimeFakeEmbedder)
        )

        self.provider = FakeManagedGenerationClient(
            response=ModelResponse(
                raw_text='{"answer":"검증용 모의 답변"}',
                input_tokens=10,
                output_tokens=4,
                finish_reason="stop",
            )
        )
        self.enterContext(
            patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=self.provider,
            )
        )
        self.classifier = Mock()
        self.classifier.predict.return_value = "SEARCH_KNOWLEDGE"
        original_overrides = fastapi_main.app.dependency_overrides.copy()
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: self.classifier
        self.addCleanup(
            lambda: (
                fastapi_main.app.dependency_overrides.clear(),
                fastapi_main.app.dependency_overrides.update(original_overrides),
            )
        )
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
        )
        self.retriever = fastapi_main.app.state.retriever
        self.embedder = RuntimeFakeEmbedder.instances[-1]
        self.worker = RetrievalService(
            self.retriever.repository,
            self.embedder,
            baseline_path=self.bundle,
        )
        self.reserve = Mock()
        fastapi_main.app.state.answerer.reserve_generation = self.reserve

    def test_below_threshold_returns_notice_without_generation_or_reservation(self):
        self._maintain("restore")
        snapshot = fastapi_main.app.state.document_provider.snapshot()
        self.worker.reconcile(snapshot)
        orthogonal = np.zeros((1, 384), dtype=np.float32)
        orthogonal[0, 1] = 1.0
        with patch.object(self.embedder, "encode_queries", return_value=orthogonal):
            for path, body in (
                ("/ask", {"question": "무관한 질문"}),
                (
                    "/assistant",
                    {
                        "response": {"ok": True, "text": "무관한 질문"},
                        "classification_label": "SEARCH_KNOWLEDGE",
                    },
                ),
            ):
                response = self.client.post(path, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("근거를 찾지 못했습니다", response.json()["text"])
        self.reserve.assert_not_called()
        self.assertEqual(self.provider.prompts, [])

    def _maintain(self, action: str):
        preview = self.client.get(
            "/documents/maintenance-preview", params={"action": action}
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        return self.client.post(
            "/documents/maintenance",
            json={"action": action, "expected_state": preview.json()["expected_state"]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

    def _ask(self, question="출근 기록은 어디에 남기나요?"):
        return self.client.post("/ask", json={"question": question})

    def _restore_and_index(self):
        response = self._maintain("restore")
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = fastapi_main.app.state.document_provider.snapshot()
        result = self.worker.reconcile(snapshot)
        self.assertTrue(result["ready"], result)
        return snapshot

    def test_clear_then_restore_invalidates_old_revision_until_baseline_reuse(self):
        first_snapshot = self._restore_and_index()
        old_revision = first_snapshot.documents[0].revision_id
        self.assertEqual(self.embedder.document_batches, [])

        first_answer = self._ask()
        self.assertEqual(first_answer.status_code, 200, first_answer.text)
        self.assertEqual(self.reserve.call_count, 1)
        self.assertIn(
            self.baseline_text.split("\n\n")[1].strip(), self.provider.prompts[0].user
        )

        cleared = self._maintain("clear")
        self.assertEqual(cleared.status_code, 200, cleared.text)
        with patch.object(
            self.retriever, "retrieve", wraps=self.retriever.retrieve
        ) as retrieve:
            empty_answer = self._ask()
            retrieve.assert_not_called()
        self.assertEqual(empty_answer.status_code, 200, empty_answer.text)
        self.assertIn("회사 문서가 없어", empty_answer.json()["text"])
        self.assertEqual(self.reserve.call_count, 1)
        self.assertEqual(len(self.provider.prompts), 1)

        restored = self._maintain("restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        new_snapshot = fastapi_main.app.state.document_provider.snapshot()
        new_revision = new_snapshot.documents[0].revision_id
        self.assertNotEqual(old_revision, new_revision)

        with patch.object(
            self.retriever, "retrieve", wraps=self.retriever.retrieve
        ) as retrieve:
            pending = self._ask()
            retrieve.assert_called_once()
        self.assertEqual(pending.status_code, 503, pending.text)
        self.assertEqual(self.reserve.call_count, 1)
        self.assertEqual(len(self.provider.prompts), 1)

        self.embedder.document_batches.clear()
        ready = self.worker.reconcile(new_snapshot)
        self.assertTrue(ready["ready"], ready)
        self.assertEqual(self.embedder.document_batches, [])
        current = self.retriever.retrieve("출근 기록은 어디에 남기나요?", new_snapshot)
        self.assertTrue(current.evidence)
        self.assertEqual(
            {item.revision_id for item in current.evidence}, {new_revision}
        )

        final_answer = self._ask()
        self.assertEqual(final_answer.status_code, 200, final_answer.text)
        self.assertEqual(self.reserve.call_count, 2)
        self.assertEqual(len(self.provider.prompts), 2)

    def test_request_keeps_old_snapshot_while_worker_indexes_new_revision(self):
        old_snapshot = self._restore_and_index()
        old_revision = old_snapshot.documents[0].revision_id
        document_id = old_snapshot.documents[0].document_id
        request_reached_retrieval = threading.Event()
        resume_request = threading.Event()
        original_retrieve = self.retriever.retrieve

        def pause_after_retrieval(question, snapshot):
            context = original_retrieve(question, snapshot)
            request_reached_retrieval.set()
            if not resume_request.wait(timeout=5):
                raise TimeoutError("worker test did not resume the request")
            return context

        with (
            patch.object(self.retriever, "retrieve", side_effect=pause_after_retrieval),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            request = executor.submit(self._ask)
            self.assertTrue(request_reached_retrieval.wait(timeout=3))
            detail = self.client.get(f"/documents/{document_id}")
            self.assertEqual(detail.status_code, 200, detail.text)
            edit = self.client.patch(
                f"/documents/{document_id}",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                json={
                    "expected_version": detail.json()["record_version"],
                    "body": "## 출근 정책\n\nUPDATED-CONTENT: 새 개정은 People 포털에서 확인한다.\n",
                },
            )
            self.assertEqual(edit.status_code, 200, edit.text)
            publish = self.client.post(
                f"/documents/{document_id}/publish",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                json={
                    "expected_version": edit.json()["record_version"],
                    "revision_id": edit.json()["draft"]["id"],
                },
            )
            self.assertEqual(publish.status_code, 200, publish.text)
            new_snapshot = fastapi_main.app.state.document_provider.snapshot()
            self.assertNotEqual(old_revision, new_snapshot.documents[0].revision_id)
            indexed = self.worker.reconcile(new_snapshot)
            self.assertTrue(indexed["ready"], indexed)
            resume_request.set()
            response = request.result(timeout=5)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.provider.prompts), 1)
        self.assertIn("BASELINE-CONTENT", self.provider.prompts[0].user)
        self.assertNotIn("UPDATED-CONTENT", self.provider.prompts[0].user)

        current = self.retriever.retrieve(
            "변경된 안내는 어디에서 확인하나요?", new_snapshot
        )
        self.assertTrue(current.evidence)
        self.assertEqual(
            {item.revision_id for item in current.evidence},
            {new_snapshot.documents[0].revision_id},
        )
        self.assertTrue(
            any("UPDATED-CONTENT" in item.text for item in current.evidence)
        )
        self.assertTrue(
            all("BASELINE-CONTENT" not in item.text for item in current.evidence)
        )

    def test_restore_source_mismatch_reindexes_new_body_without_stale_baseline(self):
        new_text = "## 출근 정책\n\nRESTORED-CURRENT-CONTENT: 변경된 안내는 운영 포털에서 확인한다.\n"
        _write_source(self.source, new_text)

        restored = self._maintain("restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        snapshot = fastapi_main.app.state.document_provider.snapshot()
        pending = self._ask("변경된 안내는 어디에서 확인하나요?")
        self.assertEqual(pending.status_code, 503, pending.text)
        self.assertEqual(self.reserve.call_count, 0)
        self.assertEqual(len(self.provider.prompts), 0)

        status = self.worker.reconcile(snapshot)
        self.assertTrue(status["ready"], status)
        encoded = [text for batch in self.embedder.document_batches for text in batch]
        self.assertTrue(encoded, "mismatched baseline should encode changed content")
        self.assertTrue(any("RESTORED-CURRENT-CONTENT" in text for text in encoded))
        self.assertFalse(any("BASELINE-CONTENT" in text for text in encoded))

        result = self.retriever.retrieve("변경된 안내는 어디에서 확인하나요?", snapshot)
        self.assertTrue(result.evidence)
        self.assertEqual(
            {item.revision_id for item in result.evidence},
            {snapshot.documents[0].revision_id},
        )
        self.assertTrue(
            all("BASELINE-CONTENT" not in item.text for item in result.evidence)
        )

        response = self._ask("변경된 안내는 어디에서 확인하나요?")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.reserve.call_count, 1)
        self.assertIn("RESTORED-CURRENT-CONTENT", self.provider.prompts[-1].user)
        self.assertNotIn("BASELINE-CONTENT", self.provider.prompts[-1].user)

    def test_mock_generation_overlaps_at_one_two_and_four_requests(self):
        self._restore_and_index()

        for request_count in (1, 2, 4):
            with self.subTest(request_count=request_count):
                barrier = threading.Barrier(request_count)
                active_lock = threading.Lock()
                state = {"active": 0, "max_active": 0}

                def generate(
                    _prompt,
                    *,
                    barrier=barrier,
                    active_lock=active_lock,
                    state=state,
                ):
                    with active_lock:
                        state["active"] += 1
                        state["max_active"] = max(state["max_active"], state["active"])
                    try:
                        barrier.wait(timeout=5)
                        return ModelResponse(
                            raw_text='{"answer":"동시성 확인 답변"}',
                            input_tokens=10,
                            output_tokens=4,
                            finish_reason="stop",
                        )
                    finally:
                        with active_lock:
                            state["active"] -= 1

                self.provider.response = generate
                with ThreadPoolExecutor(max_workers=request_count) as executor:
                    futures = [
                        executor.submit(self._ask, f"질문 {request_count}-{index}")
                        for index in range(request_count)
                    ]
                    responses = [future.result(timeout=10) for future in futures]

                self.assertEqual(
                    [response.status_code for response in responses],
                    [200] * request_count,
                )
                self.assertEqual(state["max_active"], request_count)
                self.assertEqual(state["active"], 0)


if __name__ == "__main__":
    unittest.main()
