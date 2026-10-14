"""배포 JSONL의 필수 필드·고유 ID·본문 내 문서 참조를 검사한다."""

import argparse
import json
import re
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "data/company-knowledge/documents.jsonl"


def validate(path=DEFAULT):
    errors = []
    records = []
    for number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"{number}행: JSON 형식 오류")
            continue
        if not isinstance(row, dict):
            errors.append(f"{number}행: 객체가 아닙니다")
            continue
        for key in ("document_id", "title", "document", "version"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                errors.append(f"{number}행: {key} 누락 또는 형식 오류")
        records.append(row)
    if not records:
        errors.append("지식 문서가 없습니다")
    ids = [r["document_id"] for r in records if isinstance(r.get("document_id"), str)]
    if len(ids) != len(set(ids)):
        errors.append("문서 ID 중복")
    for row in records:
        body = row.get("document", "")
        if not isinstance(body, str):
            continue
        for target in re.findall(r"문서 ID: (ieum-\d+)", body):
            if target not in ids:
                errors.append(f"{row.get('document_id')}: 없는 문서 참조 {target}")
        if re.search(r"\]\(ieum-\d+\.md\)", body):
            errors.append(f"{row.get('document_id')}: 로컬 핸드북 파일 링크")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT)
    args = parser.parse_args()
    errors = validate(args.path)
    if errors:
        raise SystemExit("\n".join(errors))
    print("회사 지식 JSONL 검증 통과: 필수 필드·고유 ID·문서 참조")


if __name__ == "__main__":
    main()
