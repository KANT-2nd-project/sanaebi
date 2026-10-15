"""Explicit demo reset plus model-free baseline mapping under one writer lock."""

import argparse
import json
import sys
from pathlib import Path

from app.retrieval.baseline import validate_baseline
from app.retrieval.config import SERVER_SPEC
from app.retrieval.reset import reset_with_retrieval
from app.settings import get_retrieval_root


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
