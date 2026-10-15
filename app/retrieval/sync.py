"""Shared process lock and document-index synchronization for RAG writes."""

from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from pathlib import Path

from app.retrieval.config import DEFAULT_SPEC, RetrievalSpec, retrieval_spec_id
from app.retrieval.types import RetrievalNotReady, RetrievalUnavailable

WRITER_LOCK_TIMEOUT_SECONDS = 10.0


class RetrievalWriterBusy(RuntimeError):
    """The shared index writer lock was not acquired before its deadline."""


class RetrievalWriterUnavailable(RuntimeError):
    """The shared writer lock could not be opened or created safely."""


@contextmanager
def writer_lock(
    root: str | Path,
    *,
    spec: RetrievalSpec = DEFAULT_SPEC,
    timeout: float = WRITER_LOCK_TIMEOUT_SECONDS,
):
    """Serialize API, worker, CLI, and maintenance index writers on one inode."""
    lock_path = Path(root) / "schema-v1" / retrieval_spec_id(spec) / "writer.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file_context = lock_path.open("a")
    except OSError as exc:
        raise RetrievalWriterUnavailable from exc
    with lock_file_context as lock_file:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise RetrievalWriterBusy from exc
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            except OSError as exc:
                raise RetrievalWriterUnavailable from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


class DocumentIndexSynchronizer:
    """Reconcile the latest published snapshot while the caller owns writer_lock."""

    def __init__(
        self,
        *,
        repository,
        retrieval_service=None,
        retrieval_indexer=None,
        document_provider,
        baseline_path: str | Path | None,
        source_path: str | Path,
        writer_lock_timeout: float = WRITER_LOCK_TIMEOUT_SECONDS,
    ):
        self.repository = repository
        self.retrieval_service = retrieval_service
        self.indexer = retrieval_indexer or retrieval_service
        if self.indexer is None:
            raise ValueError("a retrieval indexer is required")
        self.document_provider = document_provider
        self.baseline_path = Path(baseline_path) if baseline_path is not None else None
        self.source_path = Path(source_path)
        self.writer_lock_timeout = writer_lock_timeout

    def writer_lock(self):
        return writer_lock(
            self.repository.root,
            spec=self.repository.spec,
            timeout=self.writer_lock_timeout,
        )

    def reconcile_current(self):
        snapshot = self.document_provider.snapshot()
        status = self.indexer.reconcile(snapshot)
        if status.get("ready") is not True:
            raise RetrievalNotReady("현재 게시 문서의 검색 색인이 준비되지 않았습니다.")
        return status

    def preflight_restore(self):
        if self.baseline_path is None:
            raise RetrievalUnavailable("기본 벡터 묶음이 설정되지 않았습니다.")
        from app.retrieval.baseline import validate_baseline

        return validate_baseline(
            self.baseline_path, self.source_path, spec=self.repository.spec
        )

    def restore_current(self):
        if self.baseline_path is None:
            raise RetrievalUnavailable("기본 벡터 묶음이 설정되지 않았습니다.")
        from app.retrieval.baseline import restore_baseline

        snapshot = self.document_provider.snapshot()
        status = restore_baseline(
            self.repository,
            self.baseline_path,
            self.source_path,
            snapshot,
            spec=self.repository.spec,
        )
        if status.get("ready") is not True:
            raise RetrievalNotReady("기본 문서의 검색 색인이 준비되지 않았습니다.")
        return status
