"""Validate a demo reset; --apply explicitly replaces the disposable document data."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.documents.reset import ResetBusyError, reset_demo_documents
from app.settings import (
    DEFAULT_DOCUMENTS_PATH,
    get_document_database_path,
    get_retrieval_baseline,
    get_retrieval_mode,
    get_retrieval_root,
    get_retrieval_source,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    retrieval_mode = get_retrieval_mode()
    default_source = (
        get_retrieval_source() if retrieval_mode == "rag" else DEFAULT_DOCUMENTS_PATH
    )
    parser.add_argument("--source", type=Path, default=default_source)
    parser.add_argument("--database", type=Path, default=get_document_database_path())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and retrieval_mode == "rag":
        from app.documents.context import DocumentContextProvider
        from app.documents.repository import DocumentRepository
        from app.retrieval.config import SERVER_SPEC
        from app.retrieval.repository import IndexRepository
        from app.retrieval.service import RetrievalService
        from app.retrieval.sync import DocumentIndexSynchronizer

        report = {"documents_reset": False, "retrieval_ready": False}
        try:
            bundle = get_retrieval_baseline()
            database = DocumentRepository(args.database)
            index = IndexRepository(get_retrieval_root(), spec=SERVER_SPEC)
            synchronizer = DocumentIndexSynchronizer(
                repository=index,
                retrieval_service=RetrievalService(index, None, baseline_path=bundle),
                document_provider=DocumentContextProvider(repository=database),
                baseline_path=bundle,
                source_path=args.source,
            )
            synchronizer.preflight_restore()
            with synchronizer.writer_lock():
                # Revalidate after waiting for other writers, before reset mutates DB.
                synchronizer.preflight_restore()
                reset_report = reset_demo_documents(
                    args.source, args.database, apply=True
                )
                report.update(
                    documents_reset=True,
                    restored_count=reset_report["restored_count"],
                )
                synchronizer.restore_current()
            report.update(retrieval_ready=True, status="ready")
        except Exception as exc:  # noqa: BLE001 - do not expose document-bearing errors
            report.update(status="failed", error_type=type(exc).__name__)
            if report["documents_reset"]:
                report["recovery_hint"] = (
                    "python -m scripts.index_documents --restore-baseline"
                )
            print(json.dumps(report), file=sys.stderr)
            return 1
        print(json.dumps(report), file=sys.stdout)
        return 0
    try:
        report = reset_demo_documents(args.source, args.database, apply=args.apply)
    except Exception as exc:  # noqa: BLE001 - CLI must never print document-bearing exceptions
        # Exception text can contain submitted titles or other document content.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": "RuntimeError"
                    if isinstance(exc, ResetBusyError)
                    else type(exc).__name__,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "database": str(args.database.resolve()),
                    "source": str(args.source.resolve()),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
