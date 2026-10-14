"""실제 릴리스의 참조 검증과 변조 거부를 확인한다. 원본은 수정하지 않는다."""

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_company_knowledge import DEFAULT, validate


class CompanyKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.base = Path(self.directory) / "knowledge"
        shutil.copytree(DEFAULT, self.base)

    def rewrite(self, relative, transform):
        path = self.base / relative
        rows = [
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        ]
        transform(rows)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        )

    def test_missing_decision_content_is_rejected(self):
        path = self.base / "policy-decisions.csv"
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        rows[0]["decision_value"] = ""
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.assertTrue(any("결정 필수 정보" in e for e in validate(self.base)))

    def test_missing_source_metadata_is_rejected(self):
        path = self.base / "sources.csv"
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        rows[0]["source_url"] = ""
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.assertTrue(any("출처 필수 정보" in e for e in validate(self.base)))

    def test_wrong_evidence_section_is_rejected(self):
        def corrupt(rows):
            rows[0]["evidence_sections"][0]["section"] = "존재하지 않는 구역"

        self.rewrite("evaluations/evidence.jsonl", corrupt)
        self.assertTrue(any("근거 구역" in e for e in validate(self.base)))

    def test_release_references_and_review_hashes(self):
        self.assertEqual(validate(self.base), [])

    def test_changed_policy_invalidates_manifest_and_review(self):
        self.rewrite(
            "documents.jsonl",
            lambda rows: rows[0].update(document=rows[0]["document"] + "\n수정"),
        )
        errors = validate(self.base)
        self.assertTrue(any("manifest 해시" in e for e in errors))
        self.assertTrue(any("검수 해시" in e for e in errors))

    def test_unknown_source_is_rejected(self):
        self.rewrite(
            "documents.jsonl", lambda rows: rows[0].update(source_ids=["UNKNOWN"])
        )
        self.assertTrue(any("출처 참조" in e for e in validate(self.base)))

    def test_invalid_evidence_is_rejected(self):
        def corrupt(rows):
            rows[0]["evidence_sections"][0]["quote"] = "문서에 존재하지 않는 인용문"

        self.rewrite("evaluations/evidence.jsonl", corrupt)
        self.assertTrue(any("인용 불일치" in e for e in validate(self.base)))

    def test_empty_policy_file_is_rejected_by_evaluation_loader(self):
        from answer_pipeline.run import load_documents

        path = self.base / "empty.jsonl"
        path.write_text("\n \n")
        with self.assertRaisesRegex(ValueError, "회사 문서가 없습니다"):
            load_documents(path)

    def test_conflicting_fixture_preserves_both_sources(self):
        from answer_pipeline.run import load_documents

        fixture = (
            Path(__file__).parent
            / "fixtures/company-knowledge/conflicting-documents.jsonl"
        )
        docs = load_documents(fixture)
        self.assertEqual(set(docs), {"fixture-cost-a", "fixture-cost-b"})
        self.assertIn("5영업일", docs["fixture-cost-a"]["text"])
        self.assertIn("10영업일", docs["fixture-cost-b"]["text"])

    def test_missing_evidence_positions_are_rejected(self):
        self.rewrite(
            "evaluations/evidence.jsonl",
            lambda rows: rows[0].update(evidence_sections=[]),
        )
        self.assertTrue(any("근거 위치 누락" in e for e in validate(self.base)))

    def test_unknown_document_reference_is_rejected(self):
        self.rewrite(
            "evaluations/eval_set.jsonl",
            lambda rows: rows[0].update(expected_document_ids=["missing"]),
        )
        self.assertTrue(any("없는 문서 참조" in e for e in validate(self.base)))


if __name__ == "__main__":
    unittest.main()
