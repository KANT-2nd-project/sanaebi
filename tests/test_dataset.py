from __future__ import annotations

import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.validate_dataset import (
    COLUMNS,
    LABELS,
    REVIEW_COLUMNS,
    DatasetValidationError,
    validate_dataset,
)


def valid_rows() -> list[dict[str, str]]:
    rows = []
    for label in LABELS:
        for index in range(300):
            rows.append(
                {
                    "question_id": f"RQ-{label}-{index:03}",
                    "question": f"직원 요청 {label} {index}",
                    "label": label,
                    "group_id": f"group-{label}-{index // 5}",
                    "source": f"synthetic-v1:{label.lower()}",
                    "review_status": "ai_reviewed",
                }
            )
    return rows


def valid_review_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    audit = []
    for row in rows:
        audit.append(
            {
                "question_id": row["question_id"],
                "question_sha256": hashlib.sha256(
                    row["question"].encode("utf-8")
                ).hexdigest(),
                "writer": "writer-model",
                "reviewer_1": "review-model-one",
                "reviewer_1_label": row["label"],
                "reviewer_1_reason": "검수 근거 1",
                "reviewer_1_flags": "",
                "reviewer_2": "review-model-two",
                "reviewer_2_label": row["label"],
                "reviewer_2_reason": "검수 근거 2",
                "reviewer_2_flags": "",
                "decision": "consensus",
                "decision_reason": "두 검수자의 판단이 일치함",
                "final_label": row["label"],
                "scenario": "업무 요청",
                "subtype": "info",
                "personal_context": "0",
                "mixed": "0",
                "revision_history": "[]",
            }
        )
    return audit


class DatasetValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "dataset.csv"
        self.review_path = self.path.with_name("dataset-review.csv")
        self.rows = valid_rows()

    def write_dataset(
        self,
        rows: list[dict[str, str]],
        header: tuple[str, ...] = COLUMNS,
        *,
        encoding: str = "utf-8-sig",
    ) -> None:
        with self.path.open("w", encoding=encoding, newline="") as dataset_file:
            writer = csv.DictWriter(
                dataset_file, fieldnames=header, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)

    def write_review(
        self,
        rows: list[dict[str, str]],
        header: tuple[str, ...] = REVIEW_COLUMNS,
    ) -> None:
        with self.review_path.open("w", encoding="utf-8-sig", newline="") as audit_file:
            writer = csv.DictWriter(
                audit_file, fieldnames=header, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)

    def write_valid_files(self) -> None:
        self.write_dataset(self.rows)
        self.write_review(valid_review_rows(self.rows))

    def assert_invalid(self, expected: str) -> None:
        with self.assertRaisesRegex(DatasetValidationError, expected):
            validate_dataset(self.path)

    def test_accepts_canonical_dataset_and_matching_audit(self) -> None:
        self.write_valid_files()

        summary = validate_dataset(self.path)

        self.assertEqual(summary.rows, 900)
        self.assertEqual(summary.labels, dict.fromkeys(LABELS, 300))
        self.assertEqual(summary.groups, 180)
        self.assertEqual(summary.review_rows, 900)

    def test_rejects_wrong_dataset_header_and_malformed_row(self) -> None:
        self.write_dataset(self.rows, header=("wrong", *COLUMNS[1:]))
        self.assert_invalid("dataset.csv header must be exactly")

        with self.path.open("w", encoding="utf-8-sig", newline="") as dataset_file:
            writer = csv.writer(dataset_file)
            writer.writerow(COLUMNS)
            writer.writerow(("only", "two"))
        self.assert_invalid("expected 6 columns, got 2")

    def test_requires_utf8_bom(self) -> None:
        self.write_dataset(self.rows, encoding="utf-8")
        self.assert_invalid("dataset CSV must be UTF-8 with BOM")

    def test_rejects_blank_required_field(self) -> None:
        rows = [row.copy() for row in self.rows]
        rows[0]["question"] = " \n "
        self.write_dataset(rows)
        self.assert_invalid("question must not be blank")

    def test_rejects_duplicate_question_id(self) -> None:
        rows = [row.copy() for row in self.rows]
        rows[1]["question_id"] = rows[0]["question_id"]
        self.write_dataset(rows)
        self.assert_invalid("duplicate question_id")

    def test_rejects_nfkc_casefold_and_punctuation_normalized_question_duplicate(
        self,
    ) -> None:
        rows = [row.copy() for row in self.rows]
        rows[0]["question"] = "ＡＢＣ 요청"
        rows[1]["question"] = "abc-요청"
        self.write_dataset(rows)
        self.assert_invalid("duplicate normalized question")

    def test_rejects_unknown_or_multilabel_values(self) -> None:
        for label in ("UNKNOWN", "ANSWER_FROM_DOCS;CLARIFY"):
            with self.subTest(label=label):
                rows = [row.copy() for row in self.rows]
                rows[0]["label"] = label
                self.write_dataset(rows)
                self.assert_invalid("invalid label")

    def test_rejects_wrong_total_and_per_label_counts(self) -> None:
        rows = [row.copy() for row in self.rows[:-1]]
        self.write_dataset(rows)
        self.assert_invalid("expected 900 rows, got 899")

        rows = [row.copy() for row in self.rows]
        rows[300]["label"] = LABELS[0]
        self.write_dataset(rows)
        self.assert_invalid("label count for CLARIFY must be 300, got 299")

    def test_requires_ai_reviewed_status(self) -> None:
        rows = [row.copy() for row in self.rows]
        rows[0]["review_status"] = "approved"
        self.write_dataset(rows)
        self.assert_invalid("review_status must be 'ai_reviewed'")

    def test_enforces_minimum_group_count_and_maximum_group_size(self) -> None:
        rows = [row.copy() for row in self.rows]
        for row in rows:
            row["group_id"] = "one-group"
        self.write_dataset(rows)
        self.assert_invalid("expected at least 180 groups, got 1")

        rows = [row.copy() for row in self.rows]
        rows[5]["group_id"] = rows[0]["group_id"]
        self.write_dataset(rows)
        self.assert_invalid("maximum is 5")

    def test_rejects_mismatched_audit_question_hash(self) -> None:
        self.write_dataset(self.rows)
        audit = valid_review_rows(self.rows)
        audit[0]["question_sha256"] = "0" * 64
        self.write_review(audit)
        self.assert_invalid("question_sha256 mismatch")

    def test_rejects_mismatched_or_invalid_audit_labels(self) -> None:
        self.write_dataset(self.rows)
        audit = valid_review_rows(self.rows)
        audit[0]["final_label"] = LABELS[1]
        self.write_review(audit)
        self.assert_invalid("final_label does not match dataset label")

        audit = valid_review_rows(self.rows)
        audit[0]["reviewer_2_label"] = "UNKNOWN"
        self.write_review(audit)
        self.assert_invalid("invalid reviewer_2_label")

    def test_rejects_wrong_review_header(self) -> None:
        self.write_dataset(self.rows)
        self.write_review(
            valid_review_rows(self.rows), header=("wrong", *REVIEW_COLUMNS[1:])
        )
        self.assert_invalid("dataset-review.csv header must be exactly")

    def test_requires_two_reviewer_models_and_reasons_but_allows_empty_flags(
        self,
    ) -> None:
        self.write_dataset(self.rows)
        audit = valid_review_rows(self.rows)
        self.write_review(audit)
        self.assertEqual(validate_dataset(self.path).review_rows, 900)

        for field in (
            "reviewer_1",
            "reviewer_1_reason",
            "reviewer_2",
            "reviewer_2_reason",
        ):
            with self.subTest(field=field):
                audit = valid_review_rows(self.rows)
                audit[0][field] = "  "
                self.write_review(audit)
                self.assert_invalid(f"{field} must not be blank")

    def test_requires_full_unique_audit_join(self) -> None:
        self.write_dataset(self.rows)
        audit = valid_review_rows(self.rows[:-1])
        self.write_review(audit)
        with self.assertRaises(DatasetValidationError) as context:
            validate_dataset(self.path)
        self.assertIn("review audit expected 900 rows", str(context.exception))
        self.assertIn("missing 1 dataset question_id", str(context.exception))

        audit = valid_review_rows(self.rows)
        audit[-1] = audit[0].copy()
        self.write_review(audit)
        self.assert_invalid("duplicate question_id")


if __name__ == "__main__":
    unittest.main()
