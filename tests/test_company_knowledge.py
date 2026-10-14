"""로컬 집필 자료 없이 배포 JSONL을 읽고 손상을 거부하는지 확인한다."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_company_knowledge import DEFAULT, validate


class CompanyKnowledgeTests(unittest.TestCase):
    def check_rows(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            return validate(path)

    def row(self, **overrides):
        return dict(
            document_id="ieum-001",
            title="휴가",
            document="신청 안내",
            version="2.0.0",
            **overrides,
        )

    def test_published_documents_are_valid(self):
        self.assertEqual(validate(), [])
        from answer_pipeline.run import load_documents

        self.assertEqual(len(load_documents(DEFAULT)), 71)

    def test_empty_and_malformed_records_fail(self):
        for rows in ([], [None], [{"title": "제목"}], [self.row() | {"document": " "}]):
            with self.subTest(rows=rows):
                self.assertTrue(self.check_rows(rows))

    def test_duplicate_id_fails(self):
        self.assertIn("문서 ID 중복", self.check_rows([self.row(), self.row()]))

    def test_dangling_reference_fails(self):
        self.assertTrue(
            self.check_rows([self.row() | {"document": "안내 (문서 ID: ieum-999)"}])
        )

    def test_existing_reference_passes(self):
        rows = [
            self.row() | {"document": "안내 (문서 ID: ieum-002)"},
            self.row() | {"document_id": "ieum-002"},
        ]
        self.assertEqual(self.check_rows(rows), [])

    def test_local_markdown_reference_fails(self):
        self.assertTrue(
            self.check_rows([self.row() | {"document": "[안내](ieum-001.md)"}])
        )


if __name__ == "__main__":
    unittest.main()
