import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from classification import persistence
from tests.support.learning import prepare_learning_evaluation


class LearningStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / "model"
        self.texts = ["휴가 안내", "그거 뭐야", "신청 해줘"]
        self.labels = ["SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"]
        self.model = make_pipeline(
            TfidfVectorizer(analyzer="char"), LogisticRegression()
        )
        self.model.fit(self.texts, self.labels)

    def test_roundtrip_preserves_predictions_and_existing_bundle(self):
        persistence.save_bundle(
            self.model, self.destination, {"model_id": "fixture"}, self.texts
        )
        self.assertTrue((self.destination / "model.joblib").is_file())
        restored = joblib.load(self.destination / "model.joblib")
        self.assertEqual(
            restored.predict(self.texts).tolist(),
            self.model.predict(self.texts).tolist(),
        )
        metadata_path = self.destination / "metadata.json"
        before = metadata_path.read_bytes()
        self.assertEqual(json.loads(before)["model_id"], "fixture")
        with self.assertRaises(FileExistsError):
            persistence.save_bundle(self.model, self.destination, {}, self.texts)
        self.assertEqual(metadata_path.read_bytes(), before)

    def test_reload_failure_does_not_publish_bundle(self):
        with (
            patch.object(joblib, "load", side_effect=ValueError("broken")),
            self.assertRaises(ValueError),
        ):
            persistence.save_bundle(self.model, self.destination, {}, self.texts)
        self.assertFalse(self.destination.exists())


class LearningEvaluationTests(unittest.TestCase):
    def setUp(self):
        prepare_learning_evaluation(self)

    def test_requested_split_only_and_results_coexist(self):
        from classification.evaluate import evaluate_bundle

        seen = []
        predict = self.model.predict

        def record(texts):
            seen.extend(texts)
            return predict(texts)

        with (
            patch("classification.evaluate.joblib.load", return_value=self.model),
            patch.object(self.model, "predict", side_effect=record),
        ):
            val, _ = evaluate_bundle(
                self.bundle, self.dataset, output=self.root / "validation"
            )
            self.assertEqual(seen, [r["question"] for r in self.rows[3:6]])
            seen.clear()
            test, _ = evaluate_bundle(
                self.bundle, self.dataset, split="test", output=self.root / "test"
            )
            self.assertEqual(seen, [r["question"] for r in self.rows[6:]])
        self.assertEqual(val["model_id"], test["model_id"])
        self.assertTrue((self.root / "validation/metrics.json").exists())
        self.assertTrue((self.root / "test/metrics.json").exists())
        with self.assertRaises(FileExistsError):
            evaluate_bundle(self.bundle, self.dataset, output=self.root / "validation")

    def test_changed_data_and_invalid_split_are_rejected(self):
        from classification.evaluate import evaluate_bundle, main

        with self.assertRaises(SystemExit) as error:
            main([str(self.bundle), "--split", "both"])
        self.assertEqual(error.exception.code, 2)
        self.dataset.write_bytes(self.dataset.read_bytes() + b"\n")
        with patch("classification.evaluate.joblib.load") as load:
            with self.assertRaisesRegex(ValueError, "데이터"):
                evaluate_bundle(self.bundle, self.dataset)
            load.assert_not_called()

    def test_damaged_split_record_is_rejected(self):
        from classification.evaluate import evaluate_bundle

        metadata_path = self.bundle / "metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["question_ids"]["validation"][0] = metadata["question_ids"]["test"][0]
        persistence.write_json(metadata_path, metadata)
        with self.assertRaisesRegex(ValueError, "분할"):
            evaluate_bundle(self.bundle, self.dataset)


class LearningSelectionTests(unittest.TestCase):
    def test_tie_keeps_first_winner_and_reports_selected_model(self):
        from classification import tfidf

        rows = [{"question": "질문", "label": "CLARIFY"}]
        models = [Mock() for _ in range(3)]
        for model in models:
            model.predict.return_value = ["CLARIFY"]
        pipeline = Mock()
        pipeline.predict.return_value = ["CLARIFY"]
        with (
            patch.object(tfidf, "TfidfVectorizer"),
            patch.object(tfidf, "LogisticRegression", side_effect=models),
            patch.object(tfidf, "f1_score", side_effect=[0.8, 0.8, 0.6, 0.8]),
            patch.object(tfidf, "make_pipeline", return_value=pipeline) as combine,
        ):
            _, selection = tfidf.select_model(rows, rows, [0.1, 1.0, 10.0])
        self.assertEqual(selection["selected_C"], 0.1)
        self.assertIs(combine.call_args.args[1], models[0])
        self.assertEqual(len(selection["trials"]), 3)

    def test_existing_output_prevents_training(self):
        from classification import tfidf

        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(tfidf, "select_model") as train,
        ):
            with self.assertRaises(SystemExit):
                tfidf.main(["--output", temp])
            train.assert_not_called()
