"""설치된 학습 명령의 모델 선택·출력 격리·종료 상태를 검사한다."""

import csv
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contracts.classification import LABELS

ROOT = Path(__file__).resolve().parents[1]
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
            self.assertIn("637", preview.stdout)
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
            model = output / "models/tfidf/model.joblib"
            before = model.read_bytes()
            self.assertFalse((output / "results/tfidf/metrics.json").exists())
            second = self.invoke(directory, "train", *args)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("생략", second.stdout)
            self.assertEqual(model.read_bytes(), before)
            evaluation = self.invoke(directory, "eval", *args)
            self.assertEqual(evaluation.returncode, 0, evaluation.stderr)
            self.assertTrue((output / "results/tfidf/metrics.json").exists())
            forced = self.invoke(directory, "train", *args, "--force")
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertEqual(
                (output / ".backup/models/tfidf/model.joblib").read_bytes(), before
            )

    def test_missing_model_guides_training(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.invoke(
                temp, "eval", "koelectra_small", "--artifact-root", temp
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("sanaebi train koelectra_small", result.stderr)
