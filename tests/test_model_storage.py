import tempfile
import unittest
from pathlib import Path

from archive.classification_v1 import storage


class ModelStorageTests(unittest.TestCase):
    def test_split_publish_failure_preserves_sibling_and_legacy(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("validation", "test"):
                storage.atomic_json(
                    root / "results/tfidf" / name / "metrics.json", {"old": name}
                )
            storage.atomic_json(root / "results/tfidf/metrics.json", {"legacy": True})
            before = {
                str(p.relative_to(root)): p.read_bytes()
                for p in (root / "results").rglob("*.json")
            }
            staged = storage.stage(root, "test-result")
            storage.atomic_json(staged / "metrics.json", {"new": True})
            replace = storage.os.replace

            def fail_new(source, target):
                if source == staged:
                    raise OSError("disk failure")
                return replace(source, target)

            with (
                patch.object(storage.os, "replace", side_effect=fail_new),
                self.assertRaises(OSError),
            ):
                storage.publish(root, "results", "tfidf/test", staged)
            self.assertEqual(
                before,
                {
                    str(p.relative_to(root)): p.read_bytes()
                    for p in (root / "results").rglob("*.json")
                },
            )

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

    def test_failed_force_save_keeps_model_and_results(self):
        from unittest.mock import Mock, patch

        from archive.classification_v1.cli.train import execute
        from archive.classification_v1.models.tfidf import TfidfConfig
        from archive.classification_v1.types import DatasetSplits

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "models/tfidf"
            bundle.mkdir(parents=True)
            (bundle / "model.joblib").write_bytes(b"old")
            (bundle / "training_summary.json").write_text("{}")
            storage.complete_manifest(
                bundle, "tfidf", model_id="old", training_run_id="old-run"
            )
            result_file = root / "results/tfidf/metrics.json"
            result_file.parent.mkdir(parents=True)
            result_file.write_text("old result")
            before = (bundle / "manifest.json").read_bytes()
            with (
                patch(
                    "archive.classification_v1.cli.train.dataset.prepare_data",
                    return_value=DatasetSplits(
                        {"train": [], "validation": []},
                        {"dataset_sha256": "fixture"},
                        {},
                    ),
                ),
                patch("archive.classification_v1.cli.train.train", return_value=Mock()),
                patch(
                    "archive.classification_v1.cli.train.artifacts.training_summary",
                    return_value={},
                ),
                patch(
                    "archive.classification_v1.cli.train.artifacts.save_training",
                    side_effect=OSError("disk full"),
                ),
                self.assertRaisesRegex(RuntimeError, "disk full"),
            ):
                execute("tfidf", TfidfConfig(), artifact_root=root, force=True)
            self.assertEqual((bundle / "manifest.json").read_bytes(), before)
            self.assertEqual(result_file.read_text(), "old result")
            self.assertEqual(list((root / ".staging").iterdir()), [])

    def test_evaluation_prediction_failure_preserves_prior_result(self):
        from unittest.mock import Mock, patch

        from archive.classification_v1.cli.evaluate import evaluate_current
        from archive.classification_v1.types import DatasetSplits
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
            data = DatasetSplits(
                {"validation": [row], "test": [row]}, {"dataset_sha256": "fixture"}, {}
            )
            with (
                patch.object(
                    storage, "validate_bundle", return_value={"model_id": "id"}
                ),
                patch(
                    "archive.classification_v1.cli.evaluate.dataset.restore_data",
                    return_value=data,
                ),
                patch(
                    "archive.classification_v1.models.presets.load_bundle",
                    return_value=Mock(side_effect=RuntimeError("prediction failed")),
                ),
                self.assertRaisesRegex(RuntimeError, "prediction failed"),
            ):
                evaluate_current("tfidf", artifact_root=root)
            self.assertEqual(prior.read_bytes(), before)

    def test_minimal_manifest_and_legacy_read_do_not_hash_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model.joblib").write_bytes(b"weights")
            storage.atomic_json(root / "training_summary.json", {})
            storage.complete_manifest(
                root, "tfidf", model_id="new-id", training_run_id="run-id"
            )
            manifest = storage.validate_bundle(root, "tfidf")
            self.assertEqual(manifest["schema_version"], 2)
            self.assertNotIn("files", manifest)
            self.assertNotIn("fingerprint", manifest)
            storage.atomic_json(
                root / "manifest.json",
                dict(
                    manifest,
                    schema_version=1,
                    model_id="old-id",
                    files={"model.joblib": "old-hash"},
                ),
            )
            before = (root / "manifest.json").read_bytes()
            self.assertEqual(
                storage.validate_bundle(root, "tfidf")["model_id"], "old-id"
            )
            self.assertEqual(before, (root / "manifest.json").read_bytes())
            (root / "model.joblib").unlink()
            with self.assertRaisesRegex(ValueError, "필수"):
                storage.validate_bundle(root, "tfidf")

    def test_pending_journal_is_preserved_not_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / ".staging/models-tfidf.json"
            storage.atomic_json(journal, {"old": "previous"})
            before = journal.read_bytes()
            with self.assertRaisesRegex(ValueError, "자동 복구·삭제하지 않습니다"):
                storage.check_pending(root, "tfidf")
            self.assertEqual(journal.read_bytes(), before)
            self.assertFalse((root / "models/tfidf").exists())
