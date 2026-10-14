"""계층 의존 방향과 workflow의 실행 경계를 검사한다."""

import ast
import contextlib
import importlib.util
import io
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch

from archive.classification_v1 import artifacts
from archive.classification_v1.cli import train as train_cli
from archive.classification_v1.evaluation import reporting
from archive.classification_v1.models import tfidf, transformer
from archive.classification_v1.types import (
    DatasetSplits,
    FittedModel,
    MeasurementPolicy,
    Prediction,
)
from archive.classification_v1.workflows.evaluate import evaluate_questions
from archive.classification_v1.workflows.train import train
from contracts.classification import LABELS

ROOT = Path(__file__).resolve().parents[1]


def example_splits():
    rows = {
        split: [
            {
                "question_id": f"{split}-{i}",
                "question": f"{label} fixture",
                "label": label,
            }
            for i, label in enumerate(LABELS)
        ]
        for split in ("train", "validation", "test")
    }
    return DatasetSplits(
        rows,
        {"seed": 42, "input_fields": ["question"], "dataset_sha256": "fixture"},
        {},
    )


class DependencyTests(unittest.TestCase):
    def test_lower_layers_do_not_import_execution_or_other_model_implementations(self):
        root = ROOT / "archive/classification_v1"
        forbidden_commands = {"subprocess", "argparse"}
        for path in root.rglob("*.py"):
            relative = path.relative_to(root)
            parts = relative.parts
            if parts[0] in {"cli", "experiments", "legacy"} or path.stem in {
                "storage",
                "tracking",
                "presets",
            }:
                continue
            module = ".".join(
                ("archive.classification_v1", *relative.with_suffix("").parts)
            )
            package = module if path.stem == "__init__" else module.rsplit(".", 1)[0]
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = (
                        importlib.util.resolve_name(
                            "." * node.level + (node.module or ""), package
                        )
                        if node.level
                        else node.module or ""
                    )
                    targets = [base] + [f"{base}.{alias.name}" for alias in node.names]
                else:
                    continue
                for target in targets:
                    with self.subTest(file=str(relative), dependency=target):
                        self.assertNotIn(target.split(".")[0], forbidden_commands)
                        self.assertFalse(
                            target.startswith("archive.classification_v1.cli")
                        )
                        self.assertFalse(
                            target.startswith("archive.classification_v1.experiments")
                        )
                        self.assertFalse(
                            target.startswith("archive.classification_v1.legacy")
                        )
                        if parts[0] == "workflows":
                            for prefix in (
                                "archive.classification_v1.models",
                                "archive.classification_v1.artifacts",
                                "archive.classification_v1.evaluation.reporting",
                                "archive.classification_v1.dataset",
                            ):
                                self.assertFalse(target.startswith(prefix))
                        if parts[0] == "models":
                            for prefix in (
                                "archive.classification_v1.workflows",
                                "archive.classification_v1.evaluation.reporting",
                                "archive.classification_v1.artifacts",
                                "archive.classification_v1.dataset",
                            ):
                                self.assertFalse(target.startswith(prefix))
                            if target.startswith("archive.classification_v1.models."):
                                owner = target.removeprefix(
                                    "archive.classification_v1.models."
                                ).split(".")[0]
                                self.assertIn(
                                    owner,
                                    {path.stem, "jev_prompt"}
                                    if path.stem == "jev"
                                    else {path.stem},
                                )
                        if parts[0] == "evaluation" or path.stem == "types":
                            for prefix in (
                                "archive.classification_v1.models",
                                "archive.classification_v1.workflows",
                                "archive.classification_v1.dataset",
                            ):
                                self.assertFalse(target.startswith(prefix))

    def test_superseded_internal_modules_are_removed(self):
        for name in (
            "evaluation",
            "reporting",
            "document_split",
            "model_report",
            "test_jev",
            "train_bert_base",
            "train_koelectra_base",
            "train_koelectra_small",
            "train_roberta_base",
            "train_roberta_small",
            "train_tfidf",
            "train_classification_example",
            "training",
            "tfidf_training",
            "inference",
            "metrics",
            "benchmark",
            "paths",
            "data",
            "question_split",
            "jev_client",
            "jev_evaluation",
            "jev_prompt",
        ):
            self.assertFalse(
                (ROOT / "archive/classification_v1" / f"{name}.py").exists()
            )


class WorkflowTests(unittest.TestCase):
    def test_training_returns_result_without_saving_or_starting_commands(self):
        data = example_splits()
        save = Mock(side_effect=AssertionError("저장 금지"))
        fitted = FittedModel(
            lambda text: Prediction(text.split()[0]),
            save,
            {},
            lambda texts: [Prediction(text.split()[0]) for text in texts],
        )
        fit = Mock(return_value=fitted)
        with (
            patch.object(Path, "open", side_effect=AssertionError("파일 접근 금지")),
            patch.object(
                Path, "write_text", side_effect=AssertionError("파일 쓰기 금지")
            ),
            patch("subprocess.run", side_effect=AssertionError("자식 실행 금지")),
            patch.object(
                reporting, "render_report", side_effect=AssertionError("표현 금지")
            ),
        ):
            result = train(data.rows["train"], data.rows["validation"], fit)
        fit.assert_called_once_with(data.rows["train"], data.rows["validation"])
        save.assert_not_called()
        self.assertEqual(result.validation_scores["macro_f1"], 1.0)

    def test_real_small_tfidf_fit_has_no_output_files_until_save_is_called(self):
        data = example_splits()
        with (
            tempfile.TemporaryDirectory() as temp,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with (
                patch.object(
                    Path, "mkdir", side_effect=AssertionError("디렉터리 생성 금지")
                ),
                patch("joblib.dump", side_effect=AssertionError("저장 금지")),
            ):
                result = train(
                    data.rows["train"],
                    data.rows["validation"],
                    partial(tfidf.fit, config=tfidf.TfidfConfig((0.1,))),
                )
            self.assertFalse(list(Path(temp).iterdir()))
            output = Path(temp) / "model.joblib"
            result.fitted.save(output)
            self.assertTrue(output.is_file())
            self.assertEqual(tfidf.load(output)("CLARIFY fixture").label, "CLARIFY")

    def test_same_evaluation_workflow_accepts_local_and_api_predictions(self):
        data = example_splits()
        local = Mock(side_effect=lambda text: Prediction(text.split()[0]))
        api = Mock(
            side_effect=lambda text: Prediction(
                text.split()[0], 0.8, {text.split()[0]: 0.8}, "fake-jev", 10
            )
        )
        with (
            patch.object(Path, "open", side_effect=AssertionError("파일 접근 금지")),
            patch("subprocess.run", side_effect=AssertionError("실행 금지")),
        ):
            local_result = evaluate_questions(
                data.rows, local, MeasurementPolicy("repeated", 3, 3, 4)
            )
            api_result = evaluate_questions(
                data.rows, api, MeasurementPolicy("request")
            )
        self.assertEqual(local_result.scores, api_result.scores)
        self.assertEqual(local.call_count, 3 + 3 + 3 * 3)
        self.assertEqual(api.call_count, 3)
        self.assertEqual(local_result.timing["samples"], 9)
        self.assertEqual(api_result.timing["samples"], 3)
        self.assertEqual(api_result.input_tokens, 30)
        self.assertEqual(api_result.resolved_models, ["fake-jev"])
        self.assertEqual(len(api_result.predictions), 3)
        self.assertEqual(
            [c.args[0] for c in api.call_args_list],
            [r["question"] for split in ("validation",) for r in data.rows[split]],
        )

    def test_request_timing_rejects_repeated_calls(self):
        with self.assertRaises(ValueError):
            MeasurementPolicy("request", warmup=3, repeats=3)

    def test_predictor_failure_stops_without_retries(self):
        predict = Mock(side_effect=RuntimeError("prediction failed"))
        with self.assertRaisesRegex(RuntimeError, "prediction failed"):
            evaluate_questions(
                example_splits().rows, predict, MeasurementPolicy("request")
            )
        self.assertEqual(predict.call_count, 1)

    def test_storage_failure_does_not_launch_followup_evaluation(self):
        data = example_splits()
        fitted = FittedModel(Mock(), Mock(side_effect=OSError("disk full")), {}, Mock())
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(train_cli.dataset, "prepare_data", return_value=data),
            patch.object(train_cli, "print_preview"),
            patch.object(
                train_cli,
                "train",
                return_value=Mock(fitted=fitted, selection_seconds=1),
            ),
            patch.object(artifacts, "save_json") as save_json,
            patch("archive.classification_v1.cli.evaluate.evaluate_current") as report,
            self.assertRaisesRegex(RuntimeError, "disk full"),
        ):
            train_cli.run_training(tfidf.TfidfConfig(), ["--artifact-root", temp])
        save_json.assert_not_called()
        report.assert_not_called()

    def test_evaluation_failure_preserves_saved_model_and_summary(self):
        from archive.classification_v1.cli.evaluate import evaluate_current

        data = example_splits()
        with (
            tempfile.TemporaryDirectory() as temp,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(temp)
            with patch.object(train_cli.dataset, "prepare_data", return_value=data):
                train_cli.run_training(
                    tfidf.TfidfConfig((0.1,)), ["--artifact-root", temp]
                )
            model = root / "models/tfidf/model.joblib"
            before = model.read_bytes()
            with (
                patch(
                    "archive.classification_v1.cli.evaluate.dataset.restore_data",
                    side_effect=ValueError("evaluation failed"),
                ),
                self.assertRaisesRegex(ValueError, "evaluation failed"),
            ):
                evaluate_current("tfidf", artifact_root=root)
            self.assertEqual(model.read_bytes(), before)
            self.assertTrue((root / "models/tfidf/training_summary.json").exists())

    def test_transformer_fit_exposes_batch_prediction_and_explicit_save(self):
        data = example_splits()
        model, tokenizer = Mock(), Mock()
        model.config.id2label = {0: "CLARIFY", 1: "SEARCH_KNOWLEDGE", 2: "UNSUPPORTED"}
        best = transformer.BestCheckpoint(0.9, 256, 2e-5, 2, {})
        config = transformer.TransformerConfig("fake", "fake", revision="fixed-sha")
        with (
            patch(
                "transformers.AutoTokenizer.from_pretrained", return_value=tokenizer
            ) as tokenizer_load,
            patch.object(
                transformer, "select_transformer", return_value=(model, best, [])
            ),
            patch.object(transformer, "make_loader", return_value=[]) as loader,
            patch.object(transformer, "predict_ids", return_value=[0, 2]),
        ):
            fitted = transformer.fit(
                data.rows["train"], data.rows["validation"], config, device="cpu"
            )
            tokenizer_load.assert_called_once_with("fake", revision="fixed-sha")
            self.assertEqual(fitted.settings["revision"], "fixed-sha")
            model.save_pretrained.assert_not_called()
            tokenizer.save_pretrained.assert_not_called()
            self.assertEqual(
                [p.label for p in fitted.predict_batch(["a", "b"])],
                ["CLARIFY", "UNSUPPORTED"],
            )
            self.assertEqual(loader.call_args.args[3:5], (256, 4))
            with tempfile.TemporaryDirectory() as temp:
                fitted.save(Path(temp))
                model.save_pretrained.assert_called_once_with(
                    Path(temp), safe_serialization=True
                )
                tokenizer.save_pretrained.assert_called_once_with(Path(temp))


if __name__ == "__main__":
    unittest.main()
