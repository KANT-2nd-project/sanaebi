"""Explicit derived-index writer. Status and baseline restore never load a model."""

import argparse
import json
import signal
import sys
from threading import Event

from app.documents.context import DocumentContextProvider
from app.retrieval.baseline import restore_baseline
from app.retrieval.config import SERVER_SPEC
from app.retrieval.embedding import create_embedder
from app.retrieval.repository import IndexRepository
from app.retrieval.service import RetrievalService
from app.retrieval.sync import writer_lock
from app.settings import (
    get_embedding_path,
    get_retrieval_baseline,
    get_retrieval_root,
    get_retrieval_source,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ("once", "watch", "status", "restore-baseline"):
        actions.add_argument("--" + name, action="store_true")
    args = parser.parse_args(argv)
    try:
        root = get_retrieval_root()
        repository = IndexRepository(root, spec=SERVER_SPEC)
        provider = DocumentContextProvider()
        if args.status:
            result = RetrievalService(repository, None).status(provider.snapshot())
            print(json.dumps(result))
            return 0 if result["ready"] else 2
        if args.restore_baseline:
            bundle = get_retrieval_baseline()
            if bundle is None:
                raise ValueError("A baseline bundle is required")
            with writer_lock(root, spec=SERVER_SPEC):
                snapshot = provider.snapshot()
                restore_baseline(repository, bundle, get_retrieval_source(), snapshot)
                result = RetrievalService(repository, None).status(snapshot)
                print(json.dumps(result))
                return 0 if result["ready"] else 2
        embedder = create_embedder(get_embedding_path(), spec=SERVER_SPEC)
        service = RetrievalService(
            repository, embedder, baseline_path=get_retrieval_baseline()
        )
        if args.once:
            with writer_lock(root, spec=SERVER_SPEC):
                snapshot = provider.snapshot()
                service.reconcile(snapshot)
                result = service.status(snapshot)
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
                    with writer_lock(root, spec=SERVER_SPEC):
                        snapshot = provider.snapshot()
                        service.reconcile(snapshot)
                        result = service.status(snapshot)
                    print(json.dumps(result), flush=True)
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
