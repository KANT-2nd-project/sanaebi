import copy
import csv
import unittest
from pathlib import Path

from archive.classification_v1.legacy.document_split import (
    make_split_record,
    read_recorded_splits,
    split_documents,
)


class DocumentSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "archive"
            / "document-topics-v0.2"
            / "dataset.csv"
        )
        with path.open(encoding="utf-8-sig", newline="") as file:
            cls.rows = list(csv.DictReader(file))

    def test_every_document_appears_once_and_groups_do_not_leak(self):
        splits = split_documents(self.rows)
        all_ids = [row["document_id"] for rows in splits.values() for row in rows]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(set(all_ids), {row["document_id"] for row in self.rows})
        groups = {
            name: {row["source_group_id"] for row in rows}
            for name, rows in splits.items()
        }
        self.assertFalse(groups["train"] & groups["validation"])
        self.assertFalse(groups["train"] & groups["test"])
        self.assertFalse(groups["validation"] & groups["test"])

    def test_synthetic_documents_only_appear_in_train(self):
        splits = split_documents(self.rows)
        expected = {
            row["document_id"] for row in self.rows if row["kind"] == "synthetic"
        }
        actual = {
            row["document_id"] for row in splits["train"] if row["kind"] == "synthetic"
        }
        self.assertEqual(expected, actual)
        for name in ["validation", "test"]:
            self.assertTrue(all(row["kind"] != "synthetic" for row in splits[name]))

    def test_same_seed_ignores_input_order_and_outputs_sorted_ids(self):
        splits = split_documents(self.rows)
        self.assertEqual(splits, split_documents(list(reversed(self.rows))))
        for rows in splits.values():
            ids = [row["document_id"] for row in rows]
            self.assertEqual(ids, sorted(ids))

    def test_original_in_a_synthetic_group_stays_in_train(self):
        original = next(row for row in self.rows if row["kind"] != "synthetic")
        synthetic = dict(original, document_id="new-synthetic", kind="synthetic")
        splits = split_documents([*self.rows, synthetic])
        train_ids = {row["document_id"] for row in splits["train"]}
        self.assertIn(original["document_id"], train_ids)
        self.assertIn(synthetic["document_id"], train_ids)

    def test_record_restores_the_exact_documents(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "archive"
            / "document-topics-v0.2"
            / "dataset.csv"
        )
        splits = split_documents(self.rows)
        record = make_split_record(splits, path)
        self.assertEqual(read_recorded_splits(record, path), splits)

    def test_legacy_record_restores_from_default_dataset_without_mutation(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "archive"
            / "document-topics-v0.2"
            / "dataset.csv"
        )
        splits = split_documents(self.rows)
        record = make_split_record(splits, path)
        record["dataset"] = "data/dataset.csv"
        original_record = copy.deepcopy(record)

        self.assertEqual(read_recorded_splits(record), splits)
        self.assertEqual(record, original_record)

    def test_record_rejects_changed_dataset(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "archive"
            / "document-topics-v0.2"
            / "dataset.csv"
        )
        record = make_split_record(split_documents(self.rows), path)
        record["dataset_sha256"] = "different-dataset"
        with self.assertRaisesRegex(ValueError, "dataset.csv"):
            read_recorded_splits(record, path)

    def test_record_rejects_overlapping_document_ids(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "archive"
            / "document-topics-v0.2"
            / "dataset.csv"
        )
        record = make_split_record(split_documents(self.rows), path)
        record["splits"]["test"]["document_ids"][0] = record["splits"]["train"][
            "document_ids"
        ][0]
        with self.assertRaisesRegex(ValueError, "중복"):
            read_recorded_splits(record, path)


if __name__ == "__main__":
    unittest.main()
