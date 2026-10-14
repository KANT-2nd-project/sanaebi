import copy
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

from classification import test_jev as jev_cli
from classification.cli import evaluate as jev_evaluation
from classification.dataset import LABELS, question_input, split_input_hashes
from classification.models import jev as jev_client
from classification.models import jev_prompt


class JevQuestionTests(unittest.TestCase):
    def test_preview_needs_no_api_key_or_requests(self):
        script = Path(jev_cli.__file__)
        splits = jev_evaluation.prepare_jev_data().rows
        expected_calls = len(splits["validation"]) + len(splits["test"])
        self.assertEqual(expected_calls, 263)
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}),
            patch(
                "urllib.request.urlopen", side_effect=AssertionError("API 호출 금지")
            ),
            patch.object(sys, "argv", [str(script), "--preview-questions"]),
            patch.object(sys, "path", [str(script.parent), *sys.path]),
            redirect_stdout(io.StringIO()) as output,
        ):
            runpy.run_path(str(script), run_name="__main__")
        self.assertIn(f"Jev 평가 요청 수: {expected_calls}", output.getvalue())

    def test_request_sends_only_question_and_three_categories(self):
        text = question_input(
            {"question": "출장비 정산 절차 알려줘", "label": "SEARCH_KNOWLEDGE"}
        )
        answer = {"answers": {"category": {"choice": "SEARCH_KNOWLEDGE"}}}
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "mock-key"}),
            patch.object(
                jev_client,
                "urlopen",
                return_value=io.BytesIO(json.dumps(answer).encode()),
            ) as request,
        ):
            jev_client.request_classification(text)
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["state"], text)
        self.assertNotIn("label", payload)
        self.assertEqual(
            payload["questions"]["category"]["instructions"],
            jev_prompt.INSTRUCTIONS,
        )
        self.assertEqual(list(payload["questions"]["category"]["criteria"]), LABELS)
        self.assertEqual(
            payload["questions"]["category"]["criteria"], jev_prompt.CATEGORIES
        )
        for criteria in payload["questions"]["category"]["criteria"].values():
            self.assertEqual(
                set(criteria), {"description", "includes", "not_for", "examples"}
            )
            self.assertEqual(len(criteria["examples"]), 4)

    def test_prompt_examples_are_train_only_and_reject_validation_ids(self):
        splits = jev_evaluation.prepare_jev_data().rows
        train_ids = {row["question_id"] for row in splits["train"]}
        example_ids = {
            question_id
            for ids in jev_prompt.EXAMPLE_QUESTION_IDS.values()
            for question_id in ids
        }
        self.assertEqual(len(example_ids), 12)
        self.assertTrue(example_ids <= train_ids)
        changed = copy.deepcopy(jev_prompt.EXAMPLE_QUESTION_IDS)
        changed["SEARCH_KNOWLEDGE"][0] = splits["validation"][0]["question_id"]
        with (
            patch.object(jev_prompt, "EXAMPLE_QUESTION_IDS", changed),
            self.assertRaisesRegex(ValueError, "train"),
        ):
            jev_evaluation.prepare_jev_data()

    def test_evaluation_only_sends_validation_and_test_and_saves_three_probabilities(
        self,
    ):
        data = jev_evaluation.prepare_jev_data()
        splits, record = data.rows, data.record
        expected_rows = splits["validation"] + splits["test"]
        expected_inputs = [question_input(row) for row in expected_rows]
        labels_by_input = {question_input(row): row["label"] for row in expected_rows}
        calls = []

        def fake_request(text):
            calls.append(text)
            category = labels_by_input[text]
            probabilities = {label: 0.1 for label in LABELS}
            probabilities[category] = 0.8
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
                patch.object(
                    jev_client, "request_classification", side_effect=fake_request
                ),
                redirect_stdout(io.StringIO()),
            ):
                jev_evaluation.evaluate_jev(result_dir=Path(temp))
            self.assertEqual(calls, expected_inputs)
            self.assertFalse(
                set(calls) & {question_input(row) for row in splits["train"]}
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
                    "train": 12,
                    "validation": len(splits["validation"]),
                    "test": len(splits["test"]),
                },
            )
            self.assertEqual(
                metrics["settings"]["evaluation_calls"], len(expected_rows)
            )
            self.assertEqual(metrics["settings"]["prompt_examples_count"], 12)
            self.assertEqual(metrics["settings"]["prompt_example_source"], "train")
            self.assertEqual(
                metrics["settings"]["prompt_example_ids"],
                jev_prompt.EXAMPLE_QUESTION_IDS,
            )
            self.assertEqual(len(metrics["test"]["confusion_matrix"]), 3)
            self.assertEqual(len(predictions), len(expected_rows))
            self.assertEqual(len(probability_rows), len(predictions))
            for row, prediction, percentages in zip(
                expected_rows, predictions, probability_rows
            ):
                self.assertEqual(prediction["question_id"], row["question_id"])
                self.assertEqual(prediction["input_text"], question_input(row))
                self.assertEqual(set(prediction["probabilities"]), set(LABELS))
                self.assertEqual(float(percentages[row["label"] + "_percent"]), 80.0)
            html = (directory / "report.html").read_text(encoding="utf-8")
            self.assertIn("JEV · API 요청 처리 분류", html)
            self.assertIn("train 중 12개 질문을 대표 예시로 제공", html)
            self.assertIn("추가 확인 필요", html)
            self.assertNotIn("<summary>train 문서 ID", html)
            self.assertFalse((directory / "split_manifest.json").exists())
            self.assertNotIn("mock-key", (directory / "metrics.json").read_text())


if __name__ == "__main__":
    unittest.main()
