import csv
import io
import json
import os
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from classification import model_report, test_jev
from classification.document_split import LABELS, document_input, split_input_hashes


class JevDocumentTests(unittest.TestCase):
    def test_preview_needs_no_api_key_or_requests(self):
        script = Path(test_jev.__file__)
        splits, _ = test_jev.prepare_document_data()
        expected_calls = len(splits["validation"]) + len(splits["test"])
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}),
            patch(
                "urllib.request.urlopen", side_effect=AssertionError("API 호출 금지")
            ),
            patch.object(sys, "argv", [str(script), "--preview-documents"]),
            patch.object(sys, "path", [str(script.parent), *sys.path]),
            redirect_stdout(io.StringIO()) as output,
        ):
            runpy.run_path(str(script), run_name="__main__")
        self.assertIn(f"Jev 평가 요청 수: {expected_calls}", output.getvalue())

    def test_request_sends_document_and_six_categories(self):
        text = document_input(
            {"title": "VPN 안내", "text": "VPN 접속 오류는 IT에 문의한다."}
        )
        answer = {"answers": {"category": {"choice": "IT"}}}
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "mock-key"}),
            patch.object(
                test_jev,
                "urlopen",
                return_value=io.BytesIO(json.dumps(answer).encode()),
            ) as request,
        ):
            test_jev.request_classification(text)
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["state"], text)
        self.assertEqual(list(payload["questions"]["category"]["criteria"]), LABELS)

    def test_evaluation_only_sends_validation_and_test_and_saves_six_probabilities(
        self,
    ):
        splits, record = test_jev.prepare_document_data()
        expected_rows = splits["validation"] + splits["test"]
        expected_inputs = [document_input(row) for row in expected_rows]
        labels_by_input = {document_input(row): row["label"] for row in expected_rows}
        calls = []

        def fake_request(text):
            calls.append(text)
            category = labels_by_input[text]
            probabilities = {label: 0.05 for label in LABELS}
            probabilities[category] = 0.75
            return {
                "model": "mock-jev",
                "answers": {
                    "category": {
                        "choice": category,
                        "confidence": 0.7,
                        "probabilities": probabilities,
                    }
                },
                "usage": {"input_tokens": 10},
            }

        with tempfile.TemporaryDirectory() as temp:
            with (
                patch.dict(os.environ, {"TYPESAFE_API_KEY": "mock-key"}),
                patch.object(model_report, "RESULT_DIR", Path(temp)),
                patch.object(
                    test_jev, "request_classification", side_effect=fake_request
                ),
                redirect_stdout(io.StringIO()),
            ):
                test_jev.evaluate_csv()
            self.assertEqual(calls, expected_inputs)
            self.assertFalse(
                set(calls) & {document_input(row) for row in splits["train"]}
            )
            directory = Path(temp) / "jev"
            metrics = json.loads(
                (directory / "metrics.json").read_text(encoding="utf-8")
            )
            predictions = json.loads(
                (directory / "predictions.json").read_text(encoding="utf-8")
            )
            with (directory / "prediction_probabilities.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                probability_rows = list(csv.DictReader(file))
            self.assertEqual(metrics["settings"]["data_split"], record)
            self.assertEqual(metrics["data_hashes"], split_input_hashes(splits))
            self.assertEqual(
                metrics["counts"],
                {
                    "train": 0,
                    "validation": len(splits["validation"]),
                    "test": len(splits["test"]),
                },
            )
            self.assertEqual(
                metrics["settings"]["evaluation_calls"], len(expected_rows)
            )
            self.assertEqual(len(metrics["test"]["confusion_matrix"]), 6)
            self.assertEqual(len(predictions), len(expected_rows))
            self.assertEqual(len(probability_rows), len(predictions))
            for row, prediction, percentages in zip(
                expected_rows, predictions, probability_rows
            ):
                self.assertEqual(prediction["document_id"], row["document_id"])
                self.assertEqual(prediction["input_text"], document_input(row))
                self.assertEqual(set(prediction["probabilities"]), set(LABELS))
                self.assertEqual(float(percentages[row["label"] + "_percent"]), 75.0)
            html = (directory / "report.html").read_text(encoding="utf-8")
            self.assertIn("JEV · API 문서 분류", html)
            self.assertIn("train 문서를 학습하거나 API에 전달하지 않습니다", html)
            self.assertIn("보안·법무", html)
            self.assertNotIn("<summary>train 문서 ID", html)
            self.assertFalse((directory / "split_manifest.json").exists())
            self.assertNotIn("mock-key", (directory / "metrics.json").read_text())


if __name__ == "__main__":
    unittest.main()
