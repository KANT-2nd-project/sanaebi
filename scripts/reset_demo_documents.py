"""Validate a demo reset; --apply explicitly replaces the disposable document data."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.documents.reset import ResetBusyError, reset_demo_documents
from app.settings import DEFAULT_DOCUMENTS_PATH, get_document_database_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_DOCUMENTS_PATH)
    parser.add_argument("--database", type=Path, default=get_document_database_path())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
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
