import json
from pathlib import Path


def append_document(path: Path, text: str) -> None:
    document = {"doc": text}

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, ensure_ascii=False) + "\n")

def read_docukments(path: Path) -> list[str]:
