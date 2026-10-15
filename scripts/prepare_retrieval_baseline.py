"""Build an immutable embedding bundle from the actual reset source."""

import argparse
import json
import sys
from pathlib import Path

from app.retrieval.baseline import prepare_baseline, validate_baseline
from app.retrieval.config import SERVER_SPEC
from app.retrieval.embedding import create_embedder
from app.settings import get_embedding_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundle = prepare_baseline(
            args.source,
            args.output_root,
            create_embedder(get_embedding_path(), spec=SERVER_SPEC),
            spec=SERVER_SPEC,
        )
        metadata = validate_baseline(bundle, args.source, spec=SERVER_SPEC)
        print(json.dumps({"status": "ready", **metadata, "bundle": str(bundle)}))
        return 0
    except Exception as exc:  # noqa: BLE001 - safe CLI failure
        print(
            json.dumps({"status": "failed", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
