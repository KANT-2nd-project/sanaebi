"""Explicit demo reset plus model-free baseline mapping under one writer lock."""

import argparse
import json
import sys
from pathlib import Path

from app.documents.context import DocumentContextProvider
from app.documents.reset import reset_demo_documents
from app.retrieval.baseline import restore_baseline, validate_baseline
from app.retrieval.config import DEFAULT_SPEC, SERVER_SPEC
from app.retrieval.repository import IndexRepository
from app.retrieval.service import RetrievalService
from app.settings import get_retrieval_root
from scripts.index_documents import writer_lock


def reset_with_retrieval(source, database, bundle, root, *, spec=DEFAULT_SPEC):
    report = {"documents_reset": False, "retrieval_ready": False}
    try:
        validate_baseline(bundle, source, spec=spec)
        with writer_lock(root, spec=spec):
            # Revalidate after waiting for the writer, before the first source mutation.
            validate_baseline(bundle, source, spec=spec)
            reset_demo_documents(source, database, apply=True)
            report["documents_reset"] = True
            provider = DocumentContextProvider(database_path=database)
            repository = IndexRepository(root, spec=spec)
            restore_baseline(repository, bundle, source, provider.snapshot())
            report.update(
                RetrievalService(repository, None).status(provider.snapshot())
            )
            report["retrieval_ready"] = report["ready"]
    except Exception as exc:  # noqa: BLE001 - preserve partial completion without leaking content
        report.update(status="failed", error_type=type(exc).__name__)
    else:
        report["status"] = "ready" if report["retrieval_ready"] else "incomplete"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate bundle/source without writes or model loading",
    )
    args = parser.parse_args(argv)
    if args.check:
        try:
            metadata = validate_baseline(args.bundle, args.source, spec=SERVER_SPEC)
        except Exception as exc:  # noqa: BLE001 - safe preflight
            print(
                json.dumps({"status": "failed", "error_type": type(exc).__name__}),
                file=sys.stderr,
            )
            return 1
        print(json.dumps({"status": "ready", **metadata}))
        return 0
    report = reset_with_retrieval(
        args.source, args.database, args.bundle, get_retrieval_root(), spec=SERVER_SPEC
    )
    print(
        json.dumps(report), file=sys.stdout if report["retrieval_ready"] else sys.stderr
    )
    return 0 if report["retrieval_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
