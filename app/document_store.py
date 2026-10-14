import json
from pathlib import Path


def append_document(path: Path, text: str) -> None:
    document = {"doc": text}

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, ensure_ascii=False) + "\n")


def read_documents(path: Path) -> list[str]:
    documents = []

    with path.open("r", encoding="utf-8") as file:
        for i, line in enumerate(file, start=1):
            if not line.strip():
                continue

            item = json.loads(line)

            if not isinstance(item, dict):
                raise TypeError(f"{i}번째 줄은 JSON 객체여야 합니다.")

            title = item.get("title")
            body = item.get("document")

            if not isinstance(title, str) or not isinstance(body, str):
                raise TypeError(f"{i}번째 줄의 title과 document는 문자열이어야 합니다.")

            if not title.strip() or not body.strip():
                raise ValueError(f"{i}번째 줄의 제목과 본문은 비어 있을 수 없습니다.")

            documents.append(f"제목: {title.strip()}\n내용: {body.strip()}")

    return documents
