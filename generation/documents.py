"""Read an explicitly exported JSONL without accessing the runtime database."""

import json
from pathlib import Path


def render_document(
    document_id: str,
    title: str,
    document: str,
    revision_number: int,
) -> str:
    """Render a document using the exact format shared by CLI and server."""
    return (
        f"문서 ID: {document_id}\n개정: {revision_number}\n"
        f"제목: {title}\n본문:\n{document}"
    )


def load_documents(path: Path) -> list[str]:
    documents = []
    document_ids = set()

    with path.open(encoding="utf-8") as file:
        for i, line in enumerate(file, start=1):
            try:
                row = json.loads(line)

                if not isinstance(row, dict):
                    raise TypeError("문서는 JSON 객체여야 합니다.")

                for field in ("document_id", "title", "document"):
                    value = row.get(field)
                    if not isinstance(value, str):
                        raise TypeError(f"{field}는 문자열이어야 합니다.")

                    if not value.strip():
                        raise ValueError(f"{field}는 비어 있을 수 없습니다.")

                revision = row.get("revision_number")

                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise TypeError("revision_number는 정수여야 합니다.")

                if revision < 1:
                    raise ValueError("revision_number는 1 이상이어야 합니다.")

                document_id = row["document_id"]

                if document_id in document_ids:
                    raise ValueError("document_id가 중복되었습니다.")

                document_ids.add(document_id)
                documents.append(
                    render_document(
                        document_id,
                        row["title"],
                        row["document"],
                        revision,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{i}번째 줄의 문서 오류: {exc}") from exc

    if not documents:
        raise ValueError("입력 문서가 없습니다.")

    return documents
