"""Export one immutable published snapshot for explicit evaluation."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.documents.transfer import export_knowledge
from app.settings import get_document_database_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=get_document_database_path())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            export_knowledge(args.database, args.output), ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
