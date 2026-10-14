"""Dry-run by default; use --apply --publish-imported for the initial transition."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.company_knowledge import get_document_database_path
from app.services.knowledge_transfer import import_knowledge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=get_document_database_path())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--publish-imported", action="store_true")
    args = parser.parse_args()
    report = import_knowledge(
        args.source, args.database, apply=args.apply, publish=args.publish_imported
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
