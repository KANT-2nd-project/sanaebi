import json
import tempfile
import unittest
from pathlib import Path

from archive.server_legacy.document_store import read_documents


class DocumentReaderTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "documents.jsonl"

    def write_row(self, value):
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_preserves_titles_content_and_order_without_modifying_file(self):
        rows = [
            {"title": " 첫 제목 ", "document": " 첫 줄\n둘째 줄 "},
            {"title": "둘째 제목", "document": "다른 본문"},
        ]
        self.path.write_text(
            "\n" + "\n \n".join(json.dumps(row, ensure_ascii=False) for row in rows),
            encoding="utf-8",
        )
        original = self.path.read_bytes()

        self.assertEqual(
            read_documents(self.path),
            ["제목: 첫 제목\n내용: 첫 줄\n둘째 줄", "제목: 둘째 제목\n내용: 다른 본문"],
        )
        self.assertEqual(self.path.read_bytes(), original)

    def test_empty_or_blank_file_returns_empty_list(self):
        for content in ("", "\n \n\t\n"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                self.assertEqual(read_documents(self.path), [])

    def test_missing_file_is_not_treated_as_empty(self):
        with self.assertRaises(FileNotFoundError):
            read_documents(self.path)

    def test_rejects_non_object_json_before_accessing_fields(self):
        for value in ([], None, "문자열", 1, False):
            with self.subTest(value=value):
                self.write_row(value)
                with self.assertRaisesRegex(TypeError, "1번째 줄"):
                    read_documents(self.path)

    def test_rejects_missing_or_non_string_fields(self):
        for field in ("title", "document"):
            for invalid in (None, 123, False, [], {}):
                with self.subTest(field=field, invalid=invalid):
                    row = {"title": "제목", "document": "본문", field: invalid}
                    self.write_row(row)
                    with self.assertRaises(TypeError):
                        read_documents(self.path)
            with self.subTest(missing=field):
                row = {"title": "제목", "document": "본문"}
                del row[field]
                self.write_row(row)
                with self.assertRaises(TypeError):
                    read_documents(self.path)

    def test_rejects_blank_title_or_body(self):
        for field in ("title", "document"):
            for blank in ("", " \t\n"):
                with self.subTest(field=field, blank=blank):
                    self.write_row({"title": "제목", "document": "본문", field: blank})
                    with self.assertRaises(ValueError):
                        read_documents(self.path)

    def test_reports_physical_line_number_after_blank_lines(self):
        self.path.write_text('\n\n{"title": "제목"}\n', encoding="utf-8")
        with self.assertRaisesRegex(TypeError, "3번째 줄"):
            read_documents(self.path)

    def test_malformed_later_row_fails_instead_of_returning_partial_documents(self):
        self.path.write_text(
            '{"title": "제목", "document": "본문"}\n{broken', encoding="utf-8"
        )
        with self.assertRaises(json.JSONDecodeError):
            read_documents(self.path)


if __name__ == "__main__":
    unittest.main()
