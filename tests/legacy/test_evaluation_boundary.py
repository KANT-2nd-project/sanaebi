"""학습과 기본 평가가 test 문항에 접근하지 않는 공개 계약."""

import unittest
from unittest.mock import Mock

from archive.classification_v1.types import FittedModel, MeasurementPolicy, Prediction
from archive.classification_v1.workflows.evaluate import evaluate_questions
from archive.classification_v1.workflows.train import train


class EvaluationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "question_id": "v1",
            "question": "validation only",
            "label": "CLARIFY",
        }

    def test_training_receives_only_train_and_validation(self):
        fitted = FittedModel(
            Mock(), Mock(), {}, Mock(return_value=[Prediction("CLARIFY")])
        )
        fit = Mock(return_value=fitted)
        result = train([self.row], [self.row], fit)
        fit.assert_called_once_with([self.row], [self.row])
        fitted.predict_batch.assert_called_once_with(["validation only"])
        self.assertEqual(result.validation_scores["macro_f1"], 1 / 3)
        self.assertFalse(hasattr(result, "test_scores"))

    def test_default_evaluation_never_reads_test_even_for_benchmark(self):
        class GuardedSplits(dict):
            def __getitem__(self, key):
                if key == "test":
                    raise AssertionError("test was accessed")
                return super().__getitem__(key)

            def get(self, key, default=None):
                return self[key] if key in self else default  # noqa: SIM401 - 접근 감시

        predict = Mock(return_value=Prediction("CLARIFY"))
        result = evaluate_questions(
            GuardedSplits(validation=[self.row], test=object()),
            predict,
            MeasurementPolicy("repeated", warmup=2, repeats=3),
        )
        self.assertEqual(set(result.scores), {"validation"})
        self.assertEqual(predict.call_count, 6)
        self.assertTrue(all(r["split"] == "validation" for r in result.predictions))

    def test_explicit_test_only(self):
        predict = Mock(return_value=Prediction("CLARIFY"))
        result = evaluate_questions({"test": [self.row]}, predict, split="test")
        self.assertEqual(set(result.scores), {"test"})
        predict.assert_called_once_with("validation only")

    def test_invalid_split_rejected_before_prediction(self):
        predict = Mock()
        with self.assertRaises(ValueError):
            evaluate_questions({}, predict, split="both")
        predict.assert_not_called()
