import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from classification import dataset
from classification.persistence import file_sha


class FixedSplitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / "rows.csv"
        self.manifest = self.root / "split.json"
        self.rows = [
            {
                "question_id": f"Q{i}",
                "question": f"질문 {i}",
                "label": label,
                "group_id": f"G{i}",
            }
            for i, label in enumerate(list(dataset.LABELS) * 3)
        ]
        self.ids = {
            s: [f"Q{i}" for i in range(n, n + 3)]
            for s, n in [("train", 0), ("validation", 3), ("test", 6)]
        }
        self.write()

    def write(self):
        with self.csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.rows[0])
            w.writeheader()
            w.writerows(self.rows)
        self.manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "dataset_sha256": file_sha(self.csv),
                    "question_ids": self.ids,
                }
            )
        )

    def test_fixed_split_preserves_order_without_resplitting(self):
        self.ids["train"].reverse()
        self.write()
        splits = dataset.prepare_data_from_manifest(self.csv, self.manifest)
        self.assertEqual([r["question_id"] for r in splits["train"]], self.ids["train"])
        self.assertEqual(
            [r["question_id"] for r in splits["validation"]], self.ids["validation"]
        )

    def test_invalid_partition_rejected(self):
        original = copy.deepcopy(self.ids)
        for mutation in ["missing", "duplicate", "unknown", "empty", "bad_type"]:
            with self.subTest(mutation=mutation):
                self.ids = copy.deepcopy(original)
                if mutation == "missing":
                    self.ids["train"].pop()
                if mutation == "duplicate":
                    self.ids["train"].append("Q0")
                if mutation == "unknown":
                    self.ids["train"][0] = "missing"
                if mutation == "empty":
                    self.ids["train"] = []
                if mutation == "bad_type":
                    self.ids["train"][0] = 1
                self.write()
                with self.assertRaises(ValueError):
                    dataset.prepare_data_from_manifest(self.csv, self.manifest)

    def test_cross_split_group_and_changed_data_rejected(self):
        self.rows[3]["group_id"] = self.rows[0]["group_id"]
        self.write()
        with self.assertRaisesRegex(ValueError, "그룹"):
            dataset.prepare_data_from_manifest(self.csv, self.manifest)
        self.rows[3]["group_id"] = "G3"
        self.write()
        self.csv.write_text(self.csv.read_text(encoding="utf-8-sig") + "\n")
        with self.assertRaisesRegex(ValueError, "해시"):
            dataset.prepare_data_from_manifest(self.csv, self.manifest)

    def test_invalid_label_rejected(self):
        self.rows[0]["label"] = "BAD"
        self.write()
        with self.assertRaises(ValueError):
            dataset.prepare_data_from_manifest(self.csv, self.manifest)


if __name__ == "__main__":
    unittest.main()


class DiagnosticEvaluationTests(unittest.TestCase):
    def test_gate_requires_every_criterion_and_blocks_unsafe_search(self):
        from classification.diagnostic_evaluation import promotion_checks

        root = Path("classification/benchmarks/routing-augmentation-2026-10-15")
        criteria = json.loads((root / "criteria.json").read_text())
        baseline = {"macro_f1": 0.98}
        regression = {
            "correct": 42,
            "search_to_unsupported": 4,
            "clarify_correct": 6,
            "pure_lookup_execution_to_search": 0,
        }
        fresh = {
            "correct": 27,
            "pure_lookup_execution_to_search": 0,
            "classification_report": {
                label: {"recall": 0.8} for label in dataset.LABELS
            },
        }
        checks = promotion_checks(
            baseline, {"macro_f1": 0.97}, regression, fresh, criteria
        )
        self.assertTrue(all(checks.values()))
        fresh["pure_lookup_execution_to_search"] = 1
        self.assertFalse(
            promotion_checks(baseline, baseline, regression, fresh, criteria)[
                "no_unsafe_search"
            ]
        )
        fresh["pure_lookup_execution_to_search"] = 0
        fresh["classification_report"]["CLARIFY"]["recall"] = 0.79
        self.assertFalse(
            promotion_checks(baseline, baseline, regression, fresh, criteria)[
                "fresh_recall"
            ]
        )

    def test_invalid_cases_and_existing_output_fail_before_inference(self):
        from classification.diagnostic_evaluation import evaluate_cases, load_cases

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "cases.json"
            case = {
                "id": "1",
                "group_id": "G",
                "question": "질문",
                "source": "fixture",
                "expected_label": "CLARIFY",
                "pure_lookup_execution": False,
            }
            path.write_text(json.dumps([case, case]))
            with self.assertRaises(ValueError):
                load_cases(path)
            with self.assertRaises(FileExistsError):
                evaluate_cases(root / "missing-model", path, root)
            case["pure_lookup_execution"] = True
            path.write_text(json.dumps([case]))
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_experiment_preserves_original_rows_and_groups(self):
        root = Path("classification/benchmarks/routing-augmentation-2026-10-15")
        splits = dataset.prepare_data_from_manifest(
            root / "combined.csv", root / "split-manifest.json"
        )
        original = dataset.prepare_rows()
        by_id = {r["question_id"]: r for r in original}
        combined = dataset.prepare_rows(root / "combined.csv")
        self.assertEqual([r for r in combined if r["question_id"] in by_id], original)
        manifest = json.loads((root / "split-manifest.json").read_text())
        self.assertEqual(
            [len(splits[s]) for s in ("train", "validation", "test")], [722, 133, 135]
        )
        self.assertEqual(
            set(manifest["question_ids"]["train"]) - set(by_id),
            {f"AUG{i:04}" for i in range(1, 91)},
        )
        # Original source bytes are frozen in the manifest; weights are not needed.
        self.assertEqual(
            file_sha(dataset.DATASET_PATH), manifest["base_dataset_sha256"]
        )
