"""Explicit derived-index writer. Status and baseline restore never load a model."""

import argparse
import fcntl
import json
import signal
import sys
from contextlib import contextmanager
from threading import Event

from app.documents.context import DocumentContextProvider
from app.retrieval.baseline import restore_baseline
from app.retrieval.config import SPEC_ID
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from app.retrieval.service import RetrievalService
from app.settings import (
    get_embedding_path,
    get_retrieval_baseline,
    get_retrieval_root,
    get_retrieval_source,
)


@contextmanager
def writer_lock(root):
    directory = root / "schema-v1" / SPEC_ID
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ("once", "watch", "status", "restore-baseline"):
        actions.add_argument("--" + name, action="store_true")
    args = parser.parse_args(argv)
    try:
        root = get_retrieval_root()
        repository = IndexRepository(root)
        provider = DocumentContextProvider()
        if args.status:
            result = RetrievalService(repository, None).status(provider.snapshot())
            print(json.dumps(result))
            return 0 if result["ready"] else 2
        with writer_lock(root):
            if args.restore_baseline:
                bundle = get_retrieval_baseline()
                if bundle is None:
                    raise ValueError("A baseline bundle is required")
                restore_baseline(
                    repository, bundle, get_retrieval_source(), provider.snapshot()
                )
                result = RetrievalService(repository, None).status(provider.snapshot())
                print(json.dumps(result))
                return 0 if result["ready"] else 2
            embedder = TinyEmbedder(get_embedding_path())
            service = RetrievalService(
                repository, embedder, baseline_path=get_retrieval_baseline()
            )
            if args.once:
                service.reconcile(provider.snapshot())
                result = service.status(provider.snapshot())
                print(json.dumps(result))
                return 0 if result["ready"] else 1
            stopped = Event()
            previous = {}
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, lambda *_: stopped.set())
            delay = 3
            try:
                while not stopped.is_set():
                    try:
                        service.reconcile(provider.snapshot())
                        print(
                            json.dumps(service.status(provider.snapshot())), flush=True
                        )
                        delay = 3
                    except Exception as exc:  # noqa: BLE001 - safe worker diagnostics
                        print(
                            json.dumps(
                                {"status": "failed", "error_type": type(exc).__name__}
                            ),
                            file=sys.stderr,
                            flush=True,
                        )
                        delay = min(delay * 2, 30)
                    stopped.wait(delay)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
            return 0
    except Exception as exc:  # noqa: BLE001 - never expose document-bearing exceptions
        print(
            json.dumps({"status": "failed", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
