"""HTTP checks for mutation/index synchronization and retry behavior.

All document, baseline, lock, and retrieval-index files live under a fresh
TemporaryDirectory. The runtime embedder is deterministic and never loads a
model.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.documents.repository import DocumentRepository
from app.fastapi_main import app
from app.retrieval.baseline import prepare_baseline
from app.retrieval.config import SERVER_SPEC
from tests.runtime.kure_helpers import KureFakeEmbedder


def _baseline_row() -> dict[str, object]:
    return {
        "document_id": "qa-baseline-001",
        "category": "qa",
        "policy_decision_ids": ["QA-POLICY-001"],
        "source_ids": ["QA-SOURCE-001"],
        "version": "1.0.0",
        "review_status": "reviewed",
        "title": "격리 QA 기준 문서",
        "document": "격리 QA 본문은 가짜 임베더로 색인한다.",
    }


class FakeRuntimeEmbedder(KureFakeEmbedder):
    """Deterministic 1024-dim embedder with no model or network access."""

    def warmup(self):
        return None


class ControlledSync:
    """Gate or fail one real synchronizer call, then delegate to its indexer."""

    def __init__(self, delegate):
        self.delegate = delegate
        self._writer_mutex = threading.Lock()
        self._guard = threading.Lock()
        self.armed_method: str | None = None
        self.block = False
        self.fail = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = {"reconcile_current": 0, "restore_current": 0}

    @contextmanager
    def writer_lock(self):
        with self._writer_mutex, self.delegate.writer_lock():
            yield

    def arm(self, method: str, *, block: bool = False, fail: bool = False):
        if method not in self.calls:
            raise ValueError(f"unsupported sync method: {method}")
        with self._guard:
            self.armed_method = method
            self.block = block
            self.fail = fail
            self.started = threading.Event()
            self.release = threading.Event()
            self.calls[method] = 0

    def disarm(self):
        with self._guard:
            self.armed_method = None
            self.block = False
            self.fail = False
            self.release.set()

    def _before(self, method: str):
        with self._guard:
            self.calls[method] += 1
            armed = self.armed_method == method
            should_block = armed and self.block
            should_fail = armed and self.fail
            started = self.started
            release = self.release
        if not armed:
            return
        started.set()
        if should_block and not release.wait(timeout=10):
            raise TimeoutError(f"test did not release {method}")
        if should_fail:
            raise RuntimeError(f"injected isolated {method} failure")

    def reconcile_current(self):
        self._before("reconcile_current")
        return self.delegate.reconcile_current()

    def preflight_restore(self):
        return self.delegate.preflight_restore()

    def restore_current(self):
        self._before("restore_current")
        return self.delegate.restore_current()


class DocumentSyncBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sanaebi-http-sync-qa-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "baseline.jsonl"
        self.source.write_text(
            json.dumps(_baseline_row(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        baseline_embedder = FakeRuntimeEmbedder()
        self.bundle = prepare_baseline(
            self.source,
            self.root / "bundles",
            baseline_embedder,
            spec=SERVER_SPEC,
        )

        previous_state = app.state._state.copy()
        self.addCleanup(self._restore_app_state, previous_state)
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(self.root / "documents.sqlite3"),
                    "SANAEBI_RETRIEVAL_MODE": "rag",
                    "SANAEBI_RETRIEVAL_ROOT": str(self.root / "retrieval"),
                    "SANAEBI_RETRIEVAL_BASELINE": str(self.bundle),
                    "SANAEBI_RETRIEVAL_SOURCE": str(self.source),
                    "SANAEBI_EMBEDDING_PATH": str(self.root / "fake-model"),
                    "SANAEBI_ROUTING_MODE": "gate",
                    "SANAEBI_PUBLIC_DEMO": "0",
                    "SANAEBI_ANSWER_PROVIDER": "openai",
                    "OPENAI_API_KEY": "isolated-test-key",
                    "TRACE_DIR": "",
                },
            )
        )
        self.embedder = FakeRuntimeEmbedder()
        self.enterContext(
            patch(
                "app.retrieval.embedding.create_embedder",
                return_value=self.embedder,
            )
        )
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))
        self.real_sync = app.state.retrieval_sync
        self.sync = ControlledSync(self.real_sync)
        app.state.retrieval_sync = self.sync
        self.repository = DocumentRepository(self.root / "documents.sqlite3")

    @staticmethod
    def _restore_app_state(previous_state):
        app.state._state.clear()
        app.state._state.update(previous_state)

    def create_published(self, title="QA 게시 문서"):
        created = self.client.post(
            "/documents",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"title": title, "body": f"{title}의 격리된 게시 본문"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        detail = created.json()
        published = self.client.post(
            f"/documents/{detail['id']}/publish",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "expected_version": detail["record_version"],
                "revision_id": detail["draft"]["id"],
            },
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertTrue(
            app.state.retriever.status(app.state.document_provider.snapshot())["ready"]
        )
        return published.json()

    def maintenance_preview(self, action):
        response = self.client.get(
            "/documents/maintenance-preview", params={"action": action}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def maintenance_request(self, action, preview, key):
        return self.client.post(
            "/documents/maintenance",
            headers={"Idempotency-Key": key},
            json={"action": action, "expected_state": preview["expected_state"]},
        )

    def revision_state(self, detail):
        return (
            detail["record_version"],
            detail["draft"]["id"],
            detail["draft"]["revision_number"],
            detail["published"]["id"] if detail["published"] else None,
            detail["published"]["revision_number"] if detail["published"] else None,
        )

    def test_withdraw_http_response_waits_for_index_sync(self):
        published = self.create_published()
        path = f"/documents/{published['id']}/withdraw"
        payload = {"expected_version": published["record_version"]}
        key = str(uuid.uuid4())
        self.sync.arm("reconcile_current", block=True)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self.client.post,
                path,
                headers={"Idempotency-Key": key},
                json=payload,
            )
            try:
                self.assertTrue(self.sync.started.wait(timeout=3))
                self.assertFalse(future.done(), "withdraw responded before index sync")
                during_sync = self.client.get(f"/documents/{published['id']}").json()
                self.assertTrue(during_sync["withdrawn"])
                self.assertEqual(
                    during_sync["published"]["id"], published["published"]["id"]
                )
            finally:
                self.sync.release.set()
            response = future.result(timeout=8)

        final = self.client.get(f"/documents/{published['id']}").json()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(final["withdrawn"])
        self.assertEqual(self.revision_state(final), self.revision_state(during_sync))

    def test_withdraw_sync_failure_returns_saved_503_then_same_key_replays_once(self):
        published = self.create_published()
        path = f"/documents/{published['id']}/withdraw"
        payload = {"expected_version": published["record_version"]}
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        self.sync.arm("reconcile_current", fail=True)

        failed = self.client.post(path, headers=headers, json=payload)
        after_failure = self.client.get(f"/documents/{published['id']}").json()
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertEqual(failed.json()["error"]["code"], "retrieval_sync_failed")
        self.assertEqual(
            failed.json()["error"]["details"],
            {"document_saved": True, "retryable": True},
        )
        self.assertTrue(after_failure["withdrawn"])
        self.assertEqual(
            after_failure["record_version"], published["record_version"] + 1
        )

        self.sync.disarm()
        replay = self.client.post(path, headers=headers, json=payload)
        after_replay = self.client.get(f"/documents/{published['id']}").json()
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            self.revision_state(after_replay), self.revision_state(after_failure)
        )
        self.assertEqual(self.sync.calls["reconcile_current"], 2)
        self.assertNotIn("injected isolated", failed.text)

    def test_clear_http_response_waits_for_index_sync(self):
        self.create_published()
        preview = self.maintenance_preview("clear")
        self.assertEqual(preview["total_count"], 1)
        self.sync.arm("reconcile_current", block=True)
        key = str(uuid.uuid4())

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.maintenance_request, "clear", preview, key)
            try:
                self.assertTrue(self.sync.started.wait(timeout=3))
                self.assertFalse(future.done(), "clear responded before index sync")
                self.assertEqual(self.repository.list()["total"], 0)
            finally:
                self.sync.release.set()
            response = future.result(timeout=8)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted_count"], 1)
        self.assertEqual(self.repository.list()["total"], 0)

    def test_clear_sync_failure_replay_does_not_clear_later_document(self):
        self.create_published()
        preview = self.maintenance_preview("clear")
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        payload = {"action": "clear", "expected_state": preview["expected_state"]}
        self.sync.arm("reconcile_current", fail=True)

        failed = self.client.post(
            "/documents/maintenance", headers=headers, json=payload
        )
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertEqual(failed.json()["error"]["code"], "retrieval_sync_failed")
        self.assertEqual(
            failed.json()["error"]["details"],
            {"document_saved": True, "retryable": True},
        )
        self.assertEqual(self.repository.list()["total"], 0)

        self.sync.disarm()
        later = self.client.post(
            "/documents",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"title": "clear 이후 문서", "body": "재시도에서 보존될 문서"},
        )
        self.assertEqual(later.status_code, 201, later.text)
        replay = self.client.post(
            "/documents/maintenance", headers=headers, json=payload
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["deleted_count"], 1)
        listing = self.repository.list()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["id"], later.json()["id"])
        self.assertEqual(self.sync.calls["reconcile_current"], 2)

    def test_restore_http_response_waits_for_real_index_mapping(self):
        preview = self.maintenance_preview("restore")
        self.assertEqual(preview["total_count"], 0)
        self.sync.arm("restore_current", block=True)
        key = str(uuid.uuid4())

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.maintenance_request, "restore", preview, key)
            try:
                self.assertTrue(self.sync.started.wait(timeout=3))
                self.assertFalse(
                    future.done(), "restore responded before index mapping"
                )
                during_sync = app.state.document_provider.snapshot()
                self.assertEqual(len(during_sync.documents), 1)
                self.assertFalse(app.state.retriever.status(during_sync)["ready"])
            finally:
                self.sync.release.set()
            response = future.result(timeout=8)

        after_sync = app.state.document_provider.snapshot()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(app.state.retriever.status(after_sync)["ready"])
        self.assertEqual(
            during_sync.documents[0].revision_id,
            after_sync.documents[0].revision_id,
        )

    def test_restore_sync_failure_replay_preserves_revision_and_version(self):
        preview = self.maintenance_preview("restore")
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        payload = {"action": "restore", "expected_state": preview["expected_state"]}
        self.sync.arm("restore_current", fail=True)

        failed = self.client.post(
            "/documents/maintenance", headers=headers, json=payload
        )
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertEqual(failed.json()["error"]["code"], "retrieval_sync_failed")
        self.assertEqual(
            failed.json()["error"]["details"],
            {"document_saved": True, "retryable": True},
        )
        after_failure = self.client.get("/documents").json()["items"][0]
        detail_after_failure = self.client.get(
            f"/documents/{after_failure['id']}"
        ).json()
        self.assertFalse(
            app.state.retriever.status(app.state.document_provider.snapshot())["ready"]
        )

        self.sync.disarm()
        replay = self.client.post(
            "/documents/maintenance", headers=headers, json=payload
        )
        after_replay = self.client.get(f"/documents/{after_failure['id']}").json()
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            self.revision_state(after_replay), self.revision_state(detail_after_failure)
        )
        self.assertTrue(
            app.state.retriever.status(app.state.document_provider.snapshot())["ready"]
        )
        self.assertEqual(self.sync.calls["restore_current"], 2)

    def test_corrupt_index_file_is_quarantined_then_same_restore_retry_recovers(self):
        index_path = self.real_sync.repository.database_path
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_bytes(b"isolated corrupt index fixture")
        preview = self.maintenance_preview("restore")
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        payload = {"action": "restore", "expected_state": preview["expected_state"]}

        failed = self.client.post(
            "/documents/maintenance", headers=headers, json=payload
        )
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertEqual(failed.json()["error"]["code"], "retrieval_sync_failed")
        self.assertEqual(
            failed.json()["error"]["details"],
            {"document_saved": True, "retryable": True},
        )
        stored = self.client.get("/documents").json()["items"][0]
        detail_after_failure = self.client.get(f"/documents/{stored['id']}").json()

        quarantined = []
        for damaged in (
            index_path,
            Path(f"{index_path}-wal"),
            Path(f"{index_path}-shm"),
        ):
            if damaged.exists():
                target = damaged.with_name(damaged.name + ".qa-quarantined")
                damaged.replace(target)
                quarantined.append(target)
        self.assertIn(
            index_path.with_name(index_path.name + ".qa-quarantined"), quarantined
        )

        replay = self.client.post(
            "/documents/maintenance", headers=headers, json=payload
        )
        detail_after_replay = self.client.get(f"/documents/{stored['id']}").json()
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            self.revision_state(detail_after_replay),
            self.revision_state(detail_after_failure),
        )
        self.assertTrue(
            app.state.retriever.status(app.state.document_provider.snapshot())["ready"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
