import tempfile
import unittest
from pathlib import Path

from classification import storage


class ModelStorageTests(unittest.TestCase):
    def test_complete_manifest_detects_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            (bundle / "model.joblib").write_bytes(b"weights")
            (bundle / "training_summary.json").write_text("{}")
            storage.complete_manifest(
                bundle, "tfidf", {"seed": 42}, {"kind": "trained"}
            )
            self.assertEqual(
                storage.validate_bundle(bundle, "tfidf")["status"], "complete"
            )
            (bundle / "model.joblib").write_bytes(b"broken")
            with self.assertRaisesRegex(ValueError, "해시"):
                storage.validate_bundle(bundle, "tfidf")

    def test_missing_and_unlisted_files_are_rejected(self):
        for change in ("missing", "extra"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "model.joblib").write_bytes(b"weights")
                (root / "training_summary.json").write_text("{}")
                storage.complete_manifest(root, "tfidf", {}, {"kind": "trained"})
                if change == "missing":
                    (root / "model.joblib").unlink()
                else:
                    (root / "extra.joblib").write_bytes(b"other weights")
                with self.assertRaises(ValueError):
                    storage.validate_bundle(root, "tfidf")

    def test_lock_rejects_concurrent_writer_and_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                storage.lock(root, "tfidf"),
                self.assertRaisesRegex(ValueError, "진행 중"),
                storage.lock(root, "tfidf"),
            ):
                self.fail("second writer acquired lock")
            with storage.lock(root, "tfidf"):
                pass

    def test_publish_failure_restores_old_bundle(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "models/tfidf"
            old.mkdir(parents=True)
            (old / "value").write_text("old")
            staged = storage.stage(root, "tfidf")
            (staged / "value").write_text("new")
            replace = storage.os.replace

            def fail_new(source, target):
                if source == staged:
                    raise OSError("disk failure")
                return replace(source, target)

            with (
                patch.object(storage.os, "replace", side_effect=fail_new),
                self.assertRaises(OSError),
            ):
                storage.publish(root, "models", "tfidf", staged)
            self.assertEqual((old / "value").read_text(), "old")
            self.assertFalse((root / ".staging/models-tfidf.json").exists())

    def test_interrupted_swap_recovers_before_and_after_publish(self):
        for published in (False, True):
            with (
                self.subTest(published=published),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                old = storage.stage(root, "previous")
                (old / "value").write_text("old")
                staged = storage.stage(root, "new")
                (staged / "value").write_text("new")
                target = root / "models/tfidf"
                target.parent.mkdir()
                storage.atomic_json(
                    root / ".staging/models-tfidf.json",
                    {
                        "old": str(old.relative_to(root)),
                        "temporary": str(staged.relative_to(root)),
                        "target": "models/tfidf",
                    },
                )
                if published:
                    storage.os.replace(staged, target)
                storage.recover(root, "models", "tfidf")
                self.assertEqual(
                    (target / "value").read_text(), "new" if published else "old"
                )
                if published:
                    self.assertEqual(
                        (root / ".backup/models/tfidf/value").read_text(), "old"
                    )
                storage.recover(root, "models", "tfidf")  # idempotent

    def test_skip_mismatch_and_failed_force_preserve_model(self):
        from unittest.mock import patch

        from classification.cli.train import execute
        from classification.models.tfidf import TfidfConfig
        from classification.types import DatasetSplits

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "models/tfidf"
            bundle.mkdir(parents=True)
            (bundle / "model.joblib").write_bytes(b"existing")
            (bundle / "training_summary.json").write_text("{}")
            storage.complete_manifest(
                bundle, "tfidf", {"seed": 42}, {"kind": "trained"}
            )
            before = {
                p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in bundle.iterdir()
            }
            with (
                patch(
                    "classification.cli.train.dataset.prepare_data",
                    return_value=DatasetSplits({}, {}, {}),
                ),
                patch.object(
                    storage, "request_conditions", return_value={"seed": 42}
                ) as conditions,
                patch(
                    "classification.cli.train.train",
                    side_effect=RuntimeError("training failed"),
                ) as train,
                patch("huggingface_hub.HfApi.model_info") as remote,
                patch.object(storage, "stage") as stage,
            ):
                execute("tfidf", TfidfConfig(), artifact_root=root)
                train.assert_not_called()
                remote.assert_not_called()
                stage.assert_not_called()
                conditions.return_value = {"seed": 43}
                with self.assertRaisesRegex(ValueError, "--force"):
                    execute("tfidf", TfidfConfig(), artifact_root=root)
                train.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, "training failed"):
                    execute("tfidf", TfidfConfig(), artifact_root=root, force=True)
            self.assertEqual(
                before,
                {
                    p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in bundle.iterdir()
                },
            )

    def test_failed_force_save_keeps_model_and_results(self):
        from unittest.mock import Mock, patch

        from classification.cli.train import execute
        from classification.models.tfidf import TfidfConfig
        from classification.types import DatasetSplits

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "models/tfidf"
            bundle.mkdir(parents=True)
            (bundle / "model.joblib").write_bytes(b"old")
            (bundle / "training_summary.json").write_text("{}")
            storage.complete_manifest(bundle, "tfidf", {}, {"kind": "trained"})
            result_file = root / "results/tfidf/metrics.json"
            result_file.parent.mkdir(parents=True)
            result_file.write_text("old result")
            before = (bundle / "manifest.json").read_bytes()
            with (
                patch(
                    "classification.cli.train.dataset.prepare_data",
                    return_value=DatasetSplits({}, {}, {}),
                ),
                patch.object(storage, "request_conditions", return_value={}),
                patch("classification.cli.train.train", return_value=Mock()),
                patch(
                    "classification.cli.train.artifacts.training_summary",
                    return_value={},
                ),
                patch(
                    "classification.cli.train.artifacts.save_training",
                    side_effect=OSError("disk full"),
                ),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                execute("tfidf", TfidfConfig(), artifact_root=root, force=True)
            self.assertEqual((bundle / "manifest.json").read_bytes(), before)
            self.assertEqual(result_file.read_text(), "old result")
            self.assertEqual(list((root / ".staging").iterdir()), [])

    def test_corrupt_old_model_does_not_replace_normal_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for directory, value in (
                (root / "models/tfidf", "corrupt"),
                (root / ".backup/models/tfidf", "normal"),
            ):
                directory.mkdir(parents=True)
                (directory / "value").write_text(value)
            staged = storage.stage(root, "new")
            (staged / "value").write_text("new")
            storage.publish(root, "models", "tfidf", staged, backup_old=False)
            self.assertEqual(
                (root / ".backup/models/tfidf/value").read_text(), "normal"
            )
            self.assertEqual(
                next((root / ".staging").glob("previous-*/value")).read_text(),
                "corrupt",
            )

    def test_comparison_excludes_stale_models_and_separates_policies(self):
        from unittest.mock import patch

        from classification.cli.evaluate import refresh_comparison
        from contracts.classification import LABELS

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, model_id, repeats in (
                ("tfidf", "current", 3),
                ("koelectra_small", "current", 1),
                ("bert_base", "stale", 3),
            ):
                storage.atomic_json(
                    root / "results" / name / "metrics.json",
                    {
                        "model_id": model_id,
                        "settings": {
                            "labels": list(LABELS),
                            "data_split": {"input_fields": ["question"]},
                        },
                        "measurement_policy": {"repeats": repeats},
                        "evaluation_environment": {},
                        "data_hashes": {"test": "same"},
                        "counts": {},
                    },
                )
            with (
                patch.object(
                    storage, "validate_bundle", return_value={"model_id": "current"}
                ),
                patch(
                    "classification.cli.evaluate.reporting.render_comparison",
                    return_value="<html></html>",
                ) as render,
            ):
                refresh_comparison(root)
            self.assertEqual(render.call_count, 2)
            index = (root / "results/comparison.html").read_text()
            self.assertIn("tfidf", index)
            self.assertIn("koelectra_small", index)
            self.assertNotIn("bert_base", index)

    def test_evaluation_prediction_failure_preserves_prior_result(self):
        from unittest.mock import Mock, patch

        from classification.cli.evaluate import evaluate_current
        from classification.types import DatasetSplits
        from contracts.classification import LABELS

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage.atomic_json(
                root / "models/tfidf/training_summary.json",
                {
                    "labels": list(LABELS),
                    "data_split": {"input_fields": ["question"]},
                },
            )
            prior = root / "results/tfidf/metrics.json"
            storage.atomic_json(prior, {"old": "result"})
            before = prior.read_bytes()
            row = {"question_id": "1", "question": "question", "label": LABELS[0]}
            data = DatasetSplits({"validation": [row], "test": [row]}, {}, {})
            with (
                patch.object(
                    storage, "validate_bundle", return_value={"model_id": "id"}
                ),
                patch(
                    "classification.cli.evaluate.dataset.restore_data",
                    return_value=data,
                ),
                patch(
                    "classification.models.presets.load_bundle",
                    return_value=Mock(side_effect=RuntimeError("prediction failed")),
                ),
                self.assertRaisesRegex(RuntimeError, "prediction failed"),
            ):
                evaluate_current("tfidf", artifact_root=root)
            self.assertEqual(prior.read_bytes(), before)
