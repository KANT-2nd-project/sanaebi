import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib
from sklearn.dummy import DummyClassifier

from classification import model_report
from classification.document_split import (
    LABELS,
    document_input,
    make_split_record,
    split_documents,
)


class DocumentReportTests(unittest.TestCase):
    def test_legacy_question_evaluation_still_works(self):
        row = {"id": "Q1", "text": "VPN 질문", "label": "it"}
        score = model_report.evaluate([row], ["hr"])
        self.assertEqual(len(score["confusion_matrix"]), 5)
        self.assertEqual(score["errors"][0][0], "Q1")

    def test_document_report_uses_saved_ids_input_and_six_labels(self):
        dataset_path = Path(__file__).resolve().parents[1] / "data" / "dataset.csv"
        with dataset_path.open(encoding="utf-8-sig", newline="") as file:
            splits = split_documents(list(csv.DictReader(file)))
        record = make_split_record(splits, dataset_path)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = root / "model" / "tf-idf" / "tfidf_logistic_regression.joblib"
            model_path.parent.mkdir(parents=True)
            # 보고서 연결 검사 전용 모델이며 실제 실험 결과로 저장하지 않음
            model = DummyClassifier(strategy="most_frequent")
            model.fit(
                [document_input(row) for row in splits["train"]],
                [row["label"] for row in splits["train"]],
            )
            joblib.dump(model, model_path)
            model_path.with_suffix(".json").write_text(
                json.dumps({"labels": LABELS, "data_split": record}), encoding="utf-8"
            )
            with (
                patch.object(model_report, "ROOT", root),
                patch.object(model_report, "RESULT_DIR", root / "result"),
                patch.object(sys, "argv", ["model_report.py", "tfidf_lr"]),
                patch.object(
                    model_report,
                    "read_rows",
                    side_effect=AssertionError("기존 질문 CSV를 읽으면 안 됩니다."),
                ),
            ):
                model_report.main()
            directory = root / "result" / "tf-idf"
            metrics = json.loads(
                (directory / "metrics.json").read_text(encoding="utf-8")
            )
            html = (directory / "report.html").read_text(encoding="utf-8")
            self.assertEqual(metrics["settings"]["data_split"], record)
            self.assertEqual(metrics["counts"]["test"], len(splits["test"]))
            self.assertEqual(len(metrics["test"]["confusion_matrix"]), 6)
            self.assertEqual(set(metrics["test"]["per_class"]), set(LABELS))
            self.assertIn("문서 분할 기록", html)
            self.assertIn("보안·법무", html)
            self.assertNotIn("<summary>train 문서 ID</summary>", html)
            self.assertNotIn("<summary>validation 문서 ID</summary>", html)
            self.assertNotIn("<summary>test 문서 ID</summary>", html)
            self.assertTrue((root / "result" / "comparison.html").is_file())
            for error in metrics["test"]["errors"]:
                row = next(
                    row for row in splits["test"] if row["document_id"] == error[0]
                )
                self.assertEqual(error[1], document_input(row))


if __name__ == "__main__":
    unittest.main()
