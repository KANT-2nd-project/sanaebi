import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import joblib
from sklearn.dummy import DummyClassifier

from classification import dataset as question_split
from classification.cli.evaluate import evaluate_saved_model


# 모델의 test 점수를 구하는 코드가 아니라 분할·보고서 코드의 동작 검사
class QuestionSplitTests(unittest.TestCase):
    # 테스트 전체에서 사용할 실제 데이터와 공통 분할을 한 번 준비
    @classmethod
    def setUpClass(cls):
        with question_split.DATASET_PATH.open(encoding="utf-8-sig", newline="") as file:
            cls.rows = list(csv.DictReader(file))
        cls.splits = question_split.split_questions(cls.rows)

    def test_all_questions_appear_once_without_group_leakage(self):
        ids = [row["question_id"] for rows in self.splits.values() for row in rows]
        self.assertEqual(len(ids), 900)
        self.assertEqual(len(set(ids)), 900)
        self.assertEqual(set(ids), {row["question_id"] for row in self.rows})
        groups = [{row["group_id"] for row in rows} for rows in self.splits.values()]
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertFalse(groups[i] & groups[j])

    def test_documented_counts_labels_and_order_are_reproduced(self):
        expected = {"train": 632, "validation": 133, "test": 135}
        self.assertEqual(self.splits, question_split.split_questions(self.rows[::-1]))
        for name, rows in self.splits.items():
            self.assertEqual(len(rows), expected[name])
            self.assertEqual({row["label"] for row in rows}, set(question_split.LABELS))
            ids = [row["question_id"] for row in rows]
            self.assertEqual(ids, sorted(ids))

    def test_label_ratios_stay_close_to_the_overall_dataset(self):
        overall = Counter(row["label"] for row in self.rows)
        for name, rows in self.splits.items():
            counts = Counter(row["label"] for row in rows)
            for label in question_split.LABELS:
                with self.subTest(split=name, label=label):
                    target = len(rows) * overall[label] / len(self.rows)
                    self.assertLessEqual(abs(counts[label] - target), 2)

    def test_input_contains_only_question(self):
        row = self.rows[0]
        self.assertEqual(question_split.question_input(row), row["question"])
        changed = dict(row, source="secret", review_status="other", label="UNSUPPORTED")
        self.assertEqual(
            question_split.question_input(row), question_split.question_input(changed)
        )

    def test_record_restores_questions_and_rejects_modified_data(self):
        record = question_split.make_split_record(self.splits)
        self.assertEqual(question_split.read_recorded_splits(record), self.splits)
        record["dataset_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "dataset.csv"):
            question_split.read_recorded_splits(record)

    def test_record_rejects_repeated_question_id(self):
        record = question_split.make_split_record(self.splits)
        record["splits"]["test"]["question_ids"][0] = record["splits"]["train"][
            "question_ids"
        ][0]
        with self.assertRaisesRegex(ValueError, "중복"):
            question_split.read_recorded_splits(record)

    def test_question_report_restores_new_input_and_three_labels(self):
        record = question_split.make_split_record(self.splits)
        # 검사 결과는 임시 폴더에만 저장해 실제 모델·실험 결과에 영향을 주지 않음
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = root / "model" / "tf-idf" / "tfidf_logistic_regression.joblib"
            model_path.parent.mkdir(parents=True)
            # 보고서 연결 검사 전용 모델이며 실제 실험 결과로 남기지 않음
            model = DummyClassifier(strategy="most_frequent")
            model.fit(
                [row["question"] for row in self.splits["train"]],
                [row["label"] for row in self.splits["train"]],
            )
            joblib.dump(model, model_path)
            model_path.with_suffix(".json").write_text(
                json.dumps({"labels": question_split.LABELS, "data_split": record}),
                encoding="utf-8",
            )
            with patch.object(
                question_split,
                "split_questions",
                side_effect=AssertionError("보고서 평가 시 재분할하면 안 됩니다."),
            ):
                evaluate_saved_model(
                    "tfidf_lr", model_dir=root / "model", result_dir=root / "result"
                )
            directory = root / "result" / "tf-idf"
            metrics = json.loads(
                (directory / "metrics.json").read_text(encoding="utf-8")
            )
            self.assertFalse((directory / "report.html").exists())
            self.assertEqual(
                metrics["counts"], {"train": 632, "validation": 133, "test": 135}
            )
            self.assertEqual(len(metrics["test"]["confusion_matrix"]), 3)
            self.assertEqual(
                metrics["data_hashes"], question_split.split_input_hashes(self.splits)
            )
            by_id = {row["question_id"]: row for row in self.rows}
            for question_id, text, _, _ in metrics["test"]["errors"]:
                self.assertEqual(text, by_id[question_id]["question"])


if __name__ == "__main__":
    unittest.main()
