import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from generation.documents import load_documents


class GenerationDocumentsTests(unittest.TestCase):
    @staticmethod
    def document(
        document_id: str = "doc-1",
        revision_number: int = 1,
        title: str = "안내 문서",
        body: str = "본문입니다.",
    ) -> dict[str, object]:
        return {
            "document_id": document_id,
            "revision_number": revision_number,
            "title": title,
            "document": body,
        }

    def write_jsonl(self, path: Path, rows: list[object]) -> None:
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_loads_documents_in_order_and_preserves_metadata_and_text(self):
        rows = [
            self.document(" 문서-1 ", 2, " 제목 ", " 본문\n둘째 줄 "),
            self.document("문서-2", 7, "두 번째", "두 번째 본문"),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_jsonl(path, rows)

            documents = load_documents(path)

        self.assertEqual(
            documents,
            [
                "문서 ID:  문서-1 \n개정: 2\n제목:  제목 \n본문:\n 본문\n둘째 줄 ",
                "문서 ID: 문서-2\n개정: 7\n제목: 두 번째\n본문:\n두 번째 본문",
            ],
        )

    def test_rejects_missing_document_fields_with_line_number(self):
        for field in ("document_id", "revision_number", "title", "document"):
            with self.subTest(field=field), TemporaryDirectory() as directory:
                path = Path(directory) / "documents.jsonl"
                row = self.document()
                del row[field]
                self.write_jsonl(path, [self.document(), row])

                with self.assertRaisesRegex(ValueError, r"2번째 줄"):
                    load_documents(path)

    def test_rejects_invalid_string_fields_with_line_number(self):
        for field, invalid_values in {
            "document_id": (None, 1, "", " \n "),
            "title": (None, 1, "", " \t "),
            "document": (None, 1, "", " \n "),
        }.items():
            for value in invalid_values:
                with (
                    self.subTest(field=field, value=value),
                    TemporaryDirectory() as directory,
                ):
                    path = Path(directory) / "documents.jsonl"
                    row = self.document()
                    row[field] = value
                    self.write_jsonl(path, [row])

                    with self.assertRaisesRegex(ValueError, r"1번째 줄"):
                        load_documents(path)

    def test_rejects_invalid_revision_with_line_number(self):
        for revision in (None, "1", 1.0, True, False, 0, -1):
            with (
                self.subTest(revision=revision),
                TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "documents.jsonl"
                self.write_jsonl(path, [self.document(revision_number=revision)])

                with self.assertRaisesRegex(ValueError, r"1번째 줄"):
                    load_documents(path)

    def test_rejects_duplicate_document_id_with_line_number(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_jsonl(
                path,
                [self.document("same-id"), self.document("same-id", 2)],
            )

            with self.assertRaisesRegex(ValueError, r"2번째 줄"):
                load_documents(path)

    def test_rejects_malformed_json_and_blank_line_with_line_number(self):
        cases = (
            ('{"document_id":', 1),
            (json.dumps(self.document()) + "\n\n", 2),
        )
        for contents, line_number in cases:
            with (
                self.subTest(line_number=line_number),
                TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "documents.jsonl"
                path.write_text(contents, encoding="utf-8")

                with self.assertRaisesRegex(ValueError, rf"{line_number}번째 줄"):
                    load_documents(path)

    def test_rejects_non_object_json_with_line_number(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            path.write_text("[]\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"1번째 줄"):
                load_documents(path)

    def test_rejects_empty_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            path.touch()

            with self.assertRaisesRegex(ValueError, "입력 문서가 없습니다"):
                load_documents(path)

    def test_missing_file_error_is_not_hidden(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.jsonl"

            with self.assertRaises(FileNotFoundError):
                load_documents(path)


if __name__ == "__main__":
    unittest.main()
