from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.validate_dataset import COLUMNS, DatasetValidationError, validate_dataset

LABELS = ("HR", "IT", "FINANCE_PROCUREMENT", "WORKPLACE", "SECURITY_LEGAL", "COMPANY")
SPLIT_COUNTS = {"train": 70, "validation": 15, "test": 15}


def valid_rows() -> list[dict[str, str]]:
    rows = []
    for label in LABELS:
        for split, count in SPLIT_COUNTS.items():
            for index in range(count):
                kind = (
                    ("excerpt", "translation", "synthetic")[index % 3]
                    if split == "train"
                    else ("excerpt" if index % 2 == 0 else "translation")
                )
                rows.append(
                    {
                        "document_id": f"doc-{label}-{split}-{index}",
                        "title": f"Title {label} {split} {index}",
                        "text": f"Body {label} {split} {index}",
                        "label": label,
                        "split": split,
                        "source_id": f"source-{label}-{split}-{index}",
                        "source_group_id": f"group-{label}-{split}-{index}",
                        "kind": kind,
                    }
                )
    return rows


class DatasetValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "dataset.csv"
        self.rows = valid_rows()

    def write_rows(
        self, rows: list[dict[str, str]], header: tuple[str, ...] = COLUMNS
    ) -> None:
        with self.path.open("w", encoding="utf-8-sig", newline="") as dataset_file:
            writer = csv.DictWriter(
                dataset_file, fieldnames=header, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)

    def assert_invalid(self, expected: str) -> None:
        with self.assertRaisesRegex(DatasetValidationError, expected):
            validate_dataset(self.path)

    def test_accepts_canonical_dataset_and_reports_counts(self) -> None:
        self.write_rows(self.rows)
        summary = validate_dataset(self.path)

        self.assertEqual(summary.rows, 600)
        self.assertEqual(summary.splits, {"train": 420, "validation": 90, "test": 90})
        self.assertEqual(summary.labels, dict.fromkeys(LABELS, 100))

    def test_rejects_blank_required_field_and_duplicate_id(self) -> None:
        for field, value in (("source_group_id", "  "), ("text", " \n ")):
            with self.subTest(field=field):
                rows = [row.copy() for row in self.rows]
                rows[0][field] = value
                self.write_rows(rows)
                self.assert_invalid(f"{field} must not be blank")

        rows = [row.copy() for row in self.rows]
        rows[1]["document_id"] = rows[0]["document_id"]
        self.write_rows(rows)
        self.assert_invalid("duplicate document_id")

    def test_rejects_non_scalar_or_unknown_labels(self) -> None:
        for label in ("HR;IT", '["HR"]', "UNKNOWN"):
            with self.subTest(label=label):
                rows = [row.copy() for row in self.rows]
                rows[0]["label"] = label
                self.write_rows(rows)
                self.assert_invalid("invalid scalar label")

    def test_rejects_group_leakage_and_wrong_quotas(self) -> None:
        rows = [row.copy() for row in self.rows]
        rows[0]["source_group_id"] = rows[70]["source_group_id"]
        self.write_rows(rows)
        self.assert_invalid("appears in multiple splits")

        rows = [row.copy() for row in self.rows]
        rows[0]["split"] = "validation"
        self.write_rows(rows)
        self.assert_invalid("split counts must be")

    def test_rejects_invalid_split_and_kind(self) -> None:
        rows = [row.copy() for row in self.rows]
        rows[0]["split"] = "dev"
        self.write_rows(rows)
        self.assert_invalid("invalid split")

        rows = [row.copy() for row in self.rows]
        rows[0]["kind"] = "source"
        self.write_rows(rows)
        self.assert_invalid("invalid kind")

    def test_rejects_whitespace_normalized_duplicates_and_synthetic_evaluation(
        self,
    ) -> None:
        rows = [row.copy() for row in self.rows]
        rows[1]["title"] = f"  {rows[0]['title']}  "
        rows[1]["text"] = rows[0]["text"].replace(" ", " \n ")
        self.write_rows(rows)
        self.assert_invalid("duplicate whitespace-normalized")

        rows = [row.copy() for row in self.rows]
        rows[70]["kind"] = "synthetic"
        self.write_rows(rows)
        self.assert_invalid("synthetic rows must be in train")

    def test_rejects_wrong_header_and_malformed_row(self) -> None:
        self.write_rows(self.rows, header=("wrong", *COLUMNS[1:]))
        self.assert_invalid("header must be exactly")

        with self.path.open("w", encoding="utf-8-sig", newline="") as dataset_file:
            writer = csv.writer(dataset_file)
            writer.writerow(COLUMNS)
            writer.writerow(("only", "two"))
        self.assert_invalid("expected 8 columns, got 2")

    def test_requires_utf8_bom(self) -> None:
        with self.path.open("w", encoding="utf-8", newline="") as dataset_file:
            writer = csv.DictWriter(dataset_file, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(self.rows)
        self.assert_invalid("UTF-8 with BOM")


if __name__ == "__main__":
    unittest.main()
