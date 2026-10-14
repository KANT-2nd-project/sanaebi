"""로컬 실험의 명시적 재학습과 MLflow 기록 계약."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from classification.cli.train import execute
from classification.models.tfidf import TfidfConfig


class ExplicitTrainingTests(unittest.TestCase):
    def test_existing_folder_exits_without_data_or_model_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "models/tfidf").mkdir(parents=True)
            with patch(
                "classification.cli.train.dataset.prepare_data",
                side_effect=AssertionError("기존 모델이면 데이터 준비도 불필요"),
            ):
                self.assertIsNone(execute("tfidf", TfidfConfig(), artifact_root=root))
            self.assertFalse((root / "tracking").exists())


class TrackingTests(unittest.TestCase):
    def data(self):
        from classification.types import DatasetSplits

        return DatasetSplits({}, {"dataset_sha256": "fixture", "seed": 42}, {})

    def test_sqlite_runs_metrics_artifacts_and_candidate_curves(self):
        from classification import tracking

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with tracking.start_run(
                root, "tfidf", "train", self.data(), model_id="model1"
            ) as run:
                run.params({"C": [0.1, 1.0], "seed": 42})
                run.training(
                    {
                        "validation_scores": {"accuracy": 0.8, "macro_f1": 0.7},
                        "selection_seconds": 1.5,
                        "trials": [
                            {
                                "max_length": 256,
                                "learning_rate": 0.001,
                                "epoch": 1,
                                "train_loss": 0.9,
                            },
                            {
                                "max_length": 256,
                                "learning_rate": 0.001,
                                "epoch": 2,
                                "train_loss": 0.5,
                            },
                            {
                                "max_length": 384,
                                "learning_rate": 0.001,
                                "epoch": 1,
                                "train_loss": 0.8,
                            },
                        ],
                    }
                )
                train_id = run.run_id
            with tracking.start_run(
                root,
                "tfidf",
                "eval",
                self.data(),
                split="validation",
                model_id="model1",
                training_run_id=train_id,
            ) as run:
                run.evaluation(
                    {
                        "validation": {
                            "macro_f1": 0.7,
                            "per_class": {"CLARIFY": {"recall": 0.5}},
                        },
                        "benchmark": {"mean_ms": 2},
                        "data_review": "fixture",
                    },
                    [{"actual": "CLARIFY", "predicted": "UNSUPPORTED"}],
                )
                eval_id = run.run_id
            client = tracking.client_for(root)
            trained = client.get_run(train_id)
            self.assertEqual(trained.info.status, "FINISHED")
            self.assertEqual(trained.data.metrics["validation.macro_f1"], 0.7)
            history = client.get_metric_history(
                train_id, "candidate.length_256_lr_0.001.train_loss"
            )
            self.assertEqual([(m.step, m.value) for m in history], [(1, 0.9), (2, 0.5)])
            files = {f.path for f in client.list_artifacts(train_id)}
            self.assertTrue(
                {
                    "training_summary.json",
                    "trials.csv",
                    "environment.json",
                    "data_split.json",
                }
                <= files
            )
            evaluated = client.get_run(eval_id)
            self.assertEqual(evaluated.data.tags["training_run_id"], train_id)
            self.assertEqual(evaluated.data.tags["model_id"], "model1")
            filtered = client.search_runs(
                [evaluated.info.experiment_id],
                "tags.kind = 'eval' AND tags.split = 'validation'",
            )
            self.assertEqual([r.info.run_id for r in filtered], [eval_id])
            self.assertEqual(
                evaluated.data.metrics["validation.per_class.CLARIFY.recall"], 0.5
            )
            self.assertFalse(any(root.rglob("*.html")))
            self.assertFalse(any(root.rglob("*.joblib")))

    def test_tracking_initialization_fails_before_training(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "classification.cli.train.dataset.prepare_data",
                return_value=self.data(),
            ),
            patch(
                "classification.tracking.client_for",
                side_effect=OSError("db unavailable"),
            ),
            patch("classification.cli.train.train") as train,
        ):
            with self.assertRaisesRegex(RuntimeError, "db unavailable"):
                execute("tfidf", TfidfConfig(), artifact_root=Path(directory))
            train.assert_not_called()
            self.assertFalse((Path(directory) / "models/tfidf").exists())

    def test_tracking_failure_preserves_published_file_and_marks_failed(self):
        from classification import tracking

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = root / "models/tfidf/model.joblib"
            with (
                self.assertRaisesRegex(RuntimeError, "로컬 저장 완료"),
                tracking.start_run(
                    root, "tfidf", "train", self.data(), model_id="saved"
                ) as run,
            ):
                saved.parent.mkdir(parents=True)
                saved.write_bytes(b"preserved")
                run.saved_path = saved.parent
                run_id = run.run_id
                with patch.object(
                    run.client, "log_metric", side_effect=OSError("db write failed")
                ):
                    run.metrics({"accuracy": 1})
            self.assertEqual(saved.read_bytes(), b"preserved")
            self.assertEqual(
                tracking.client_for(root).get_run(run_id).info.status, "FAILED"
            )
