"""Shared writer-lock and periodic index-worker coordination contracts."""

import io
import json
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.documents.context import DocumentContextProvider
from app.documents.repository import DocumentRepository
from app.documents.service import (
    DocumentServiceError,
    create_document,
    publish_document,
)
from app.retrieval.repository import IndexRepository
from app.retrieval.sync import (
    DocumentIndexSynchronizer,
    RetrievalWriterBusy,
    RetrievalWriterUnavailable,
    writer_lock,
)
from scripts import index_documents


class RetrievalWriterLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_real_lock_excludes_another_thread_until_released(self):
        acquired = threading.Event()
        release = threading.Event()

        def hold_lock():
            with writer_lock(self.root, timeout=1):
                acquired.set()
                if not release.wait(timeout=2):
                    raise TimeoutError("test lock holder was not released")

        with ThreadPoolExecutor(max_workers=1) as executor:
            holder = executor.submit(hold_lock)
            try:
                self.assertTrue(acquired.wait(timeout=1), "holder did not acquire lock")
                with (
                    self.assertRaises(RetrievalWriterBusy),
                    writer_lock(self.root, timeout=0.03),
                ):
                    self.fail("a second writer entered while the lock was held")
            finally:
                release.set()
            holder.result(timeout=2)

        with writer_lock(self.root, timeout=0.1):
            pass

    def test_lock_is_released_when_protected_operation_raises(self):
        with (
            self.assertRaisesRegex(RuntimeError, "operation failed"),
            writer_lock(self.root, timeout=0.1),
        ):
            raise RuntimeError("operation failed")

        with writer_lock(self.root, timeout=0.1):
            pass

    def test_lock_open_oserror_becomes_safe_retryable_service_error(self):
        database = self.root / "documents.sqlite3"
        repository = DocumentRepository(database)
        repository.initialize()
        _, detail = create_document(
            repository,
            {"title": "휴가 안내", "body": "휴가 신청 절차"},
            str(uuid.uuid4()),
        )
        sync = DocumentIndexSynchronizer(
            repository=IndexRepository(self.root / "retrieval"),
            retrieval_service=object(),
            document_provider=DocumentContextProvider(repository=repository),
            baseline_path=None,
            source_path=self.root / "unused.jsonl",
            writer_lock_timeout=0.1,
        )
        original_open = Path.open

        def fail_lock_open(path, *args, **kwargs):
            if path.name == "writer.lock":
                raise OSError("simulated lock path permission failure")
            return original_open(path, *args, **kwargs)

        with (
            patch.object(Path, "open", new=fail_lock_open),
            self.assertRaises(DocumentServiceError) as raised,
        ):
            publish_document(
                repository,
                detail["id"],
                expected_version=detail["record_version"],
                revision_id=detail["draft"]["id"],
                idempotency_key=str(uuid.uuid4()),
                retrieval_sync=sync,
            )

        error = raised.exception
        self.assertEqual(error.status_code, 503)
        self.assertEqual(error.code, "retrieval_sync_failed")
        self.assertEqual(error.details, {"document_saved": False, "retryable": True})
        self.assertIsInstance(error.__cause__, RetrievalWriterUnavailable)
        self.assertNotIn("permission failure", str(error))
        self.assertIsNone(repository.get(detail["id"])["published"])

    def test_watch_releases_lock_each_iteration_and_reads_snapshot_inside_lock(self):
        lock_state = {"depth": 0, "entered": 0, "exited": 0}
        snapshots = []
        reconciled = []
        statuses = []
        waits = []
        signal_calls = []

        @contextmanager
        def tracked_lock(_root):
            lock_state["depth"] += 1
            lock_state["entered"] += 1
            try:
                yield
            finally:
                lock_state["depth"] -= 1
                lock_state["exited"] += 1

        class FakeProvider:
            def snapshot(self):
                if lock_state["depth"] != 1:
                    raise AssertionError("worker read the snapshot outside its lock")
                snapshot = object()
                snapshots.append(snapshot)
                return snapshot

        class FakeService:
            def __init__(self, _repository, _embedder, *, baseline_path):
                self.baseline_path = baseline_path

            def reconcile(self, snapshot):
                if lock_state["depth"] != 1:
                    raise AssertionError("worker reconciled outside its lock")
                reconciled.append(snapshot)

            def status(self, snapshot):
                if lock_state["depth"] != 1:
                    raise AssertionError("worker checked status outside its lock")
                statuses.append(snapshot)
                return {"ready": True}

        class FakeEvent:
            def __init__(self):
                self.wait_count = 0

            def is_set(self):
                return self.wait_count >= 2

            def set(self):
                self.wait_count = 2

            def wait(self, delay):
                if lock_state["depth"] != 0:
                    raise AssertionError("worker waited while holding the lock")
                waits.append(delay)
                self.wait_count += 1

        fake_event = FakeEvent()

        def fake_signal(sig, handler):
            signal_calls.append((sig, handler))
            return "previous-handler"

        with (
            patch.object(index_documents, "get_retrieval_root", return_value=self.root),
            patch.object(
                index_documents, "get_embedding_path", return_value=self.root / "model"
            ),
            patch.object(index_documents, "get_retrieval_baseline", return_value=None),
            patch.object(index_documents, "IndexRepository", return_value=object()),
            patch.object(
                index_documents, "DocumentContextProvider", return_value=FakeProvider()
            ),
            patch.object(index_documents, "TinyEmbedder", return_value=object()),
            patch.object(index_documents, "RetrievalService", FakeService),
            patch.object(index_documents, "writer_lock", tracked_lock),
            patch.object(index_documents, "Event", return_value=fake_event),
            patch.object(index_documents.signal, "signal", side_effect=fake_signal),
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()) as stderr,
        ):
            result = index_documents.main(["--watch"])

        self.assertEqual(result, 0, stderr.getvalue())
        self.assertEqual(lock_state, {"depth": 0, "entered": 2, "exited": 2})
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(reconciled, snapshots)
        self.assertEqual(statuses, snapshots)
        self.assertEqual(waits, [3, 3])
        self.assertEqual(len(signal_calls), 4)
        self.assertTrue(
            all(json.loads(line)["ready"] for line in stdout.getvalue().splitlines())
        )


if __name__ == "__main__":
    unittest.main()
