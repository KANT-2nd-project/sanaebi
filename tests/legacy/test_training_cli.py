"""설치된 학습 명령의 모델 선택·출력 격리·종료 상태를 검사한다."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contracts.classification import LABELS

COMMAND = Path(sys.executable).parent / (
    "sanaebi.exe" if os.name == "nt" else "sanaebi"
)


class TrainingCommandTests(unittest.TestCase):
    def invoke(self, directory, *args):
        # 외부 작업 폴더에서 실행해 editable 설치와 기본 데이터 경로도 확인한다.
        env = dict(
            os.environ,
            TYPESAFE_API_KEY="",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
        )
        return subprocess.run(
            [str(COMMAND), *map(str, args)],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_preview_and_invalid_model_do_not_create_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runs"
            preview = self.invoke(
                directory,
                "train",
                "koelectra_small",
                "--preview-questions",
                "--artifact-root",
                output,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("632", preview.stdout)
            self.assertFalse(output.exists())
            invalid = self.invoke(
                directory, "train", "unknown", "--artifact-root", output
            )
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("invalid choice", invalid.stderr)
            self.assertFalse(output.exists())

    def test_train_skip_eval_force_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "questions.csv"
            with dataset.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "question_id",
                        "question",
                        "label",
                        "group_id",
                        "source",
                    ],
                )
                writer.writeheader()
                for group in range(20):
                    for index, label in enumerate(LABELS):
                        writer.writerow(
                            {
                                "question_id": f"fixture-{group}-{index}",
                                "question": f"{label} fixture {group}",
                                "label": label,
                                "group_id": str(group),
                                "source": "unit-test",
                            }
                        )
            output = root / "artifacts"
            args = ["tfidf", "--dataset", dataset, "--artifact-root", output]
            first = self.invoke(directory, "train", *args)
            self.assertEqual(first.returncode, 0, first.stderr)
            summary = json.loads(
                (output / "models/tfidf/training_summary.json").read_text()
            )
            self.assertIn("validation_scores", summary)
            self.assertFalse(any(k.startswith("test_") for k in summary))
            model = output / "models/tfidf/model.joblib"
            before = model.read_bytes()
            self.assertFalse(
                (output / "results/tfidf/validation/metrics.json").exists()
            )
            second = self.invoke(directory, "train", *args)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("생략", second.stdout)
            self.assertEqual(model.read_bytes(), before)
            legacy = output / "results/tfidf/metrics.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text('{"historical": true}')
            evaluation = self.invoke(directory, "eval", *args)
            self.assertEqual(evaluation.returncode, 0, evaluation.stderr)
            self.assertTrue((output / "results/tfidf/validation/metrics.json").exists())
            validation_path = output / "results/tfidf/validation/metrics.json"
            validation_bytes = validation_path.read_bytes()
            validation = json.loads(validation_bytes)
            self.assertEqual(validation["evaluated_split"], "validation")
            self.assertNotIn("test", validation)
            self.assertFalse((output / "results/tfidf/test").exists())
            explicit_test = self.invoke(directory, "eval", *args, "--split", "test")
            self.assertEqual(explicit_test.returncode, 0, explicit_test.stderr)
            test_report = json.loads(
                (output / "results/tfidf/test/metrics.json").read_text()
            )
            self.assertEqual(test_report["model_id"], validation["model_id"])
            self.assertNotIn("validation", test_report)
            self.assertEqual(validation_bytes, validation_path.read_bytes())
            self.assertEqual(legacy.read_text(), '{"historical": true}')
            self.assertEqual(model.read_bytes(), before)
            invalid = self.invoke(directory, "eval", *args, "--split", "both")
            self.assertEqual(invalid.returncode, 2)
            forced = self.invoke(directory, "train", *args, "--force")
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertEqual(
                (output / ".backup/models/tfidf/model.joblib").read_bytes(), before
            )

            from archive.classification_v1.tracking import client_for

            client = client_for(output)
            experiment = client.get_experiment_by_name("classification")
            runs = client.search_runs([experiment.experiment_id])
            self.assertEqual(
                len(runs), 4
            )  # initial train, validation, test, forced train
            self.assertTrue(all(r.info.status == "FINISHED" for r in runs))
            self.assertFalse(any(output.rglob("*.html")))
            current = json.loads((output / "models/tfidf/manifest.json").read_text())
            self.assertNotEqual(current["model_id"], validation["model_id"])
            # A v1 bundle remains readable without rewriting it or changing its model ID.
            current["schema_version"] = 1
            current["files"] = {"model.joblib": "legacy-hash-not-recomputed"}
            manifest_path = output / "models/tfidf/manifest.json"
            manifest_path.write_text(json.dumps(current))
            before_manifest = manifest_path.read_bytes()
            old_eval = self.invoke(directory, "eval", *args)
            self.assertEqual(old_eval.returncode, 0, old_eval.stderr)
            self.assertEqual(manifest_path.read_bytes(), before_manifest)
            self.assertEqual(
                json.loads(validation_path.read_text())["model_id"], current["model_id"]
            )

    def test_missing_model_guides_training(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.invoke(
                temp, "eval", "koelectra_small", "--artifact-root", temp
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("sanaebi train koelectra_small", result.stderr)
