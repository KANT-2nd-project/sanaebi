"""분리된 실험 코드의 동작 검사. 사전학습 모델·실제 API·기존 결과를 쓰지 않는다."""

import contextlib
import csv
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import torch
from sklearn.feature_extraction.text import TfidfVectorizer

from archive.classification_v1 import artifacts, dataset
from archive.classification_v1.cli.evaluate import evaluate_saved_model
from archive.classification_v1.cli.train import run_training
from archive.classification_v1.dataset import LABELS, read_recorded_splits
from archive.classification_v1.evaluation import reporting
from archive.classification_v1.evaluation.metrics import evaluate
from archive.classification_v1.models import jev as jev_client
from archive.classification_v1.models import tfidf
from archive.classification_v1.models import transformer as inference
from archive.classification_v1.models import transformer as training
from archive.classification_v1.models.tfidf import TfidfConfig, select_tfidf

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = [
    p.stem for p in (ROOT / "archive/classification_v1/experiments").glob("train_*.py")
]


class TrainingTests(unittest.TestCase):
    def test_best_checkpoint_is_independent_and_keeps_first_tie(self):
        model = torch.nn.Linear(1, 1, bias=False)
        with torch.no_grad():
            model.weight.fill_(2)
        best = training.BestCheckpoint()
        best.consider(model, score=0.8, max_length=8, learning_rate=0.01, epoch=1)
        with torch.no_grad():
            model.weight.fill_(9)
        best.consider(model, score=0.8, max_length=16, learning_rate=0.02, epoch=2)
        best.consider(model, score=0.7, max_length=16, learning_rate=0.02, epoch=3)
        best.restore(model)
        self.assertEqual(model.weight.item(), 2)
        self.assertFalse(model.training)
        self.assertEqual(
            (best.max_length, best.learning_rate, best.epoch), (8, 0.01, 1)
        )

    def test_selection_uses_validation_and_preserves_candidate_seed_order(self):
        config = training.TransformerConfig(
            "fake", "fake", (8, 16), (0.01, 0.02), epochs=2, revision="fixed-sha"
        )
        rows = [{"question": label, "label": label} for label in LABELS]
        # test를 제공하지 않아도 선택 가능해야 한다.
        splits = {"train": rows, "validation": rows}
        models, seeds = [], []
        steps = 0

        def load_model(*args, **kwargs):
            self.assertEqual(kwargs["revision"], "fixed-sha")
            model = torch.nn.Linear(1, 1, bias=False)
            models.append(model)
            return model

        def train(model, *args):
            nonlocal steps
            steps += 1
            with torch.no_grad():
                model.weight.fill_(steps)
            return 10.0 - steps  # loss가 계속 좋아져도 첫 최고 검증 후보를 유지

        good, bad = [0, 1, 2], [0, 0, 0]
        with (
            patch(
                "transformers.AutoModelForSequenceClassification.from_pretrained",
                side_effect=load_model,
            ),
            patch.object(training, "make_loader", return_value=[]) as loader,
            patch.object(training, "train_epoch", side_effect=train),
            patch.object(
                training,
                "predict_ids",
                side_effect=[bad, good, good, bad, bad, good, bad, bad],
            ),
            patch("torch.manual_seed", side_effect=lambda seed: seeds.append(seed)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            model, best, trials = training.select_transformer(
                config, object(), splits, "cpu"
            )
        self.assertEqual(seeds, [config.seed] * 4)
        self.assertEqual(
            [(t["max_length"], t["learning_rate"], t["epoch"]) for t in trials],
            [
                (length, rate, epoch)
                for length in (8, 16)
                for rate in (0.01, 0.02)
                for epoch in (1, 2)
            ],
        )
        self.assertEqual(
            [call.args[3] for call in loader.call_args_list], [8, 8, 16, 16]
        )
        self.assertIs(model, models[-1])
        self.assertEqual(model.weight.item(), 2)
        self.assertEqual(best.epoch, 2)
        self.assertEqual(best.max_length, 8)
        self.assertEqual(best.learning_rate, 0.01)

    def test_train_epoch_weights_batch_loss_by_sample_count_and_updates_weights(self):
        class TinyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.tensor(1.0))

            def forward(self, input_ids, attention_mask, labels):
                return SimpleNamespace(loss=self.weight * input_ids.float().mean())

        model = TinyModel()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        # 첫 배치 loss=1, 두 번째 loss=0.9*3=2.7. 평균=(1*2+2.7)/3.
        batches = [
            (torch.tensor([[1], [1]]), torch.ones(2, 1), torch.tensor([0, 1])),
            (torch.tensor([[3]]), torch.ones(1, 1), torch.tensor([2])),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            loss = training.train_epoch(model, batches, optimizer, "cpu")
        self.assertAlmostEqual(loss, 4.7 / 3, places=6)
        self.assertAlmostEqual(model.weight.item(), 0.6, places=6)

    def test_loader_tokenizes_without_global_padding_and_collates_labels(self):
        class Tokenizer:
            def __call__(self, texts, **kwargs):
                self.options = kwargs
                return {"input_ids": [[7, 8], [9]], "attention_mask": [[1, 1], [1]]}

            def pad(self, rows, **kwargs):
                length = max(len(row["input_ids"]) for row in rows)
                return {
                    "input_ids": torch.tensor(
                        [
                            row["input_ids"] + [0] * (length - len(row["input_ids"]))
                            for row in rows
                        ]
                    ),
                    "attention_mask": torch.tensor(
                        [
                            row["attention_mask"]
                            + [0] * (length - len(row["attention_mask"]))
                            for row in rows
                        ]
                    ),
                    "label": torch.tensor([row["label"] for row in rows]),
                }

        tokenizer = Tokenizer()
        loader = training.make_loader(tokenizer, ["긴 질문", "짧음"], [2, 0], 8, 2)
        ids, masks, labels = next(iter(loader))
        self.assertEqual(ids.tolist(), [[7, 8], [9, 0]])
        self.assertEqual(masks.tolist(), [[1, 1], [1, 0]])
        self.assertEqual(labels.tolist(), [2, 0])
        self.assertEqual(
            tokenizer.options,
            {
                "padding": False,
                "truncation": True,
                "max_length": 8,
                "return_token_type_ids": False,
            },
        )

    def test_prediction_does_not_pass_labels_or_enable_gradients(self):
        def forward(**kwargs):
            self.assertNotIn("labels", kwargs)
            self.assertFalse(torch.is_grad_enabled())
            return SimpleNamespace(
                logits=torch.tensor([[0.0, 3.0, 1.0], [4.0, 1.0, 2.0]])
            )

        model = Mock(side_effect=forward)
        batch = (torch.ones(2, 2), torch.ones(2, 2), torch.tensor([0, 0]))
        self.assertEqual(training.predict_ids(model, [batch], "cpu"), [1, 0])
        model.eval.assert_called_once()

    def test_tfidf_fits_only_training_texts(self):
        train = [
            {"question": text, "label": label}
            for label, text in zip(
                LABELS, ["annual leave policy", "which thing please", "book my holiday"]
            )
        ]
        validation = [
            {"question": "zz " + r["question"], "label": r["label"]} for r in train
        ]
        original = TfidfVectorizer.fit_transform
        fitted_texts = []

        def fit(vectorizer, texts, y=None):
            fitted_texts.append(list(texts))
            return original(vectorizer, texts, y)

        with (
            patch.object(TfidfVectorizer, "fit_transform", fit),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            model, c, score, trials = select_tfidf(
                train, validation, TfidfConfig((0.1, 0.5))
            )
        self.assertEqual(fitted_texts, [[r["question"] for r in train]])
        self.assertNotIn("zz", model.steps[0][1].vocabulary_)
        self.assertEqual(score, 1.0)
        self.assertEqual(c, 0.1)  # 동점이면 먼저 평가한 후보
        self.assertEqual([t["C"] for t in trials], [0.1, 0.5])
        model.predict(["unseen zz question"])
        self.assertEqual(len(fitted_texts), 1)

    def test_small_tfidf_training_saves_and_evaluates_in_custom_paths(self):
        from archive.classification_v1.cli.train import run_training as train_tfidf

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
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
                                "question_id": f"fixture-{group:02}-{index}",
                                "question": f"{label} fixture {group}",
                                "label": label,
                                "group_id": str(group),
                                "source": "unit-test",
                            }
                        )
            with contextlib.redirect_stdout(io.StringIO()):
                summary = train_tfidf(
                    TfidfConfig((0.1,)),
                    [
                        "--dataset",
                        str(dataset),
                        "--artifact-root",
                        str(root / "artifacts"),
                    ],
                )
            from archive.classification_v1.cli.evaluate import evaluate_current

            evaluate_current(
                "tfidf", artifact_root=root / "artifacts", dataset_path=dataset
            )
            self.assertTrue((root / "artifacts/models/tfidf/model.joblib").is_file())
            report = json.loads(
                (root / "artifacts/results/tfidf/validation/metrics.json").read_text()
            )
            self.assertEqual(report["settings"], summary)
            self.assertEqual(sum(report["counts"].values()), 60)
            self.assertEqual(
                report["benchmark"]["samples"], report["counts"]["validation"] * 3
            )
            self.assertFalse(
                (root / "artifacts/results/tfidf/validation/report.html").exists()
            )
            self.assertFalse((root / "artifacts/results/comparison.html").exists())

    def test_example_configuration_fails_before_data_or_download(self):
        from archive.classification_v1.experiments.train_example import CONFIG

        with (
            patch.object(
                dataset, "prepare_data", side_effect=AssertionError("읽기 금지")
            ),
            self.assertRaisesRegex(ValueError, "실제 값"),
        ):
            run_training(CONFIG, [])


class InferenceTests(unittest.TestCase):
    def test_saved_label_mapping_and_preprocessing_are_used(self):
        model = Mock(
            return_value=SimpleNamespace(logits=torch.tensor([[0.0, 5.0, 1.0]]))
        )
        # 공통 LABELS의 index 1과 다른 저장 매핑: 라벨 순서로 덮어쓰면 실패한다.
        model.config.id2label = {0: "CLARIFY", 1: "UNSUPPORTED", 2: "SEARCH_KNOWLEDGE"}
        tokenizer = Mock(
            return_value={
                "input_ids": torch.ones(1, 2),
                "attention_mask": torch.ones(1, 2),
            }
        )
        predict = inference.transformer_predictor(
            model, tokenizer, {"max_length": 384, "padding": "longest_in_batch"}
        )
        self.assertEqual(predict(" 질문 ").label, "UNSUPPORTED")
        self.assertEqual(tokenizer.call_args.args, (" 질문 ",))
        self.assertEqual(
            tokenizer.call_args.kwargs,
            {
                "padding": False,
                "truncation": True,
                "max_length": 384,
                "return_tensors": "pt",
            },
        )
        model.config.id2label[1] = "LABEL_1"
        with self.assertRaises(ValueError):
            predict("질문")
        predict = inference.transformer_predictor(model, tokenizer, {})
        with self.assertRaises(ValueError):
            predict("질문")
        self.assertEqual(tokenizer.call_args.kwargs["max_length"], 192)
        self.assertEqual(tokenizer.call_args.kwargs["padding"], "max_length")

    def test_transformer_loader_uses_local_files_and_cpu(self):
        with (
            patch("transformers.AutoTokenizer.from_pretrained") as tokenizer,
            patch(
                "transformers.AutoModelForSequenceClassification.from_pretrained"
            ) as model,
            patch("torch.set_num_threads") as threads,
        ):
            path = Path("unused-fixture")
            predictor = inference.load(path, {"max_length": 256})
            self.assertTrue(callable(predictor))
            tokenizer.assert_called_once_with(path, local_files_only=True)
            model.assert_called_once_with(path, local_files_only=True)
            model.return_value.to.assert_called_once_with("cpu")
            threads.assert_called_once_with(4)

    def test_sklearn_prediction_is_a_label_not_an_index(self):
        model = Mock()
        model.predict.return_value = ["CLARIFY"]
        predict = tfidf.sklearn_predictor(model)
        self.assertEqual(predict("질문").label, "CLARIFY")
        model.predict.assert_called_once_with(["질문"])
        model.predict.return_value = [1]
        with self.assertRaises(ValueError):
            predict("질문")


class ReportAndClientTests(unittest.TestCase):
    def test_recorded_metrics_and_html_survive_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            result_dir = Path(temp)
            for path in sorted(
                (ROOT / "archive/classification_v1/result").glob("*/metrics.json")
            ):
                original_metrics = path.read_bytes()
                original_html = path.with_name("report.html").read_bytes()
                report = json.loads(original_metrics)
                splits = read_recorded_splits(report["settings"]["data_split"])
                for split in ("validation", "test"):
                    # 저장된 정답과 오답 목록에서 예측을 복원하여 지표를 재계산한다.
                    errors = {entry[0]: entry[3] for entry in report[split]["errors"]}
                    rows = [dict(row, text=row["question"]) for row in splits[split]]
                    predictions = [
                        errors.get(row["question_id"], row["label"]) for row in rows
                    ]
                    self.assertEqual(evaluate(rows, predictions), report[split])
                target = result_dir / path.parent.name
                target.mkdir()
                shutil.copyfile(path, target / "metrics.json")
                output = reporting.render_report(report)
                self.assertIn("모델과 평가의 정체", output)
                self.assertIn("미기록", output)
                self.assertEqual(path.read_bytes(), original_metrics)
                self.assertEqual(
                    path.with_name("report.html").read_bytes(), original_html
                )
            comparison = reporting.render_comparison(artifacts.read_reports(result_dir))
            self.assertIn("검증 F1", comparison)
            self.assertNotIn("테스트 F1", comparison)
            with (
                patch(
                    "archive.classification_v1.models.transformer.load",
                    side_effect=AssertionError("모델 호출 금지"),
                ),
                patch(
                    "archive.classification_v1.models.jev.urlopen",
                    side_effect=AssertionError("API 호출 금지"),
                ),
            ):
                evaluate_saved_model("jev", result_dir=result_dir)

    def test_jev_prompt_matches_new_run_and_updates_archived_examples(self):
        from archive.classification_v1.models import jev_prompt

        saved = json.loads(
            (ROOT / "archive/classification_v1/result/jev/metrics.json").read_text()
        )["settings"]
        self.assertEqual(jev_prompt.INSTRUCTIONS, saved["instructions"])
        for label, criteria in jev_prompt.CATEGORIES.items():
            self.assertEqual(
                {key: value for key, value in criteria.items() if key != "examples"},
                {
                    key: value
                    for key, value in saved["criteria"][label].items()
                    if key != "examples"
                },
            )
        self.assertEqual(jev_prompt.CATEGORIES, saved["criteria"])
        self.assertEqual(jev_prompt.EXAMPLE_QUESTION_IDS, saved["prompt_example_ids"])
        archived = json.loads(
            (
                ROOT
                / "archive/classification_v1/archive/results/before-stratified-2026-10-14/jev/metrics.json"
            ).read_text()
        )["settings"]
        self.assertNotEqual(
            jev_prompt.EXAMPLE_QUESTION_IDS, archived["prompt_example_ids"]
        )
        self.assertEqual(jev_prompt.PROMPT_REVIEW_SCOPE, saved["prompt_review_scope"])
        self.assertEqual(jev_prompt.MODEL_NAME, saved["requested_model"])

    def test_jev_failures_are_exceptions_not_process_exit(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}),
            self.assertRaises(jev_client.JevRequestError),
        ):
            jev_client.request_classification("질문")
        for error in [
            TimeoutError(),
            URLError("offline"),
            HTTPError("https://example.invalid", 403, "denied", {}, None),
        ]:
            with (
                self.subTest(error=type(error).__name__),
                patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake"}),
                patch.object(jev_client, "urlopen", side_effect=error) as request,
            ):
                with self.assertRaises(jev_client.JevRequestError):
                    jev_client.request_classification("질문")
                self.assertEqual(request.call_count, 1)


class EntrypointTests(unittest.TestCase):
    def test_import_has_no_experiment_side_effects(self):
        # reload는 클래스 identity를 바꾸므로 다른 테스트와 프로세스를 분리한다.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from test_classification_refactor import EntrypointTests; "
                    "EntrypointTests()._check_import_side_effects()"
                ),
            ],
            cwd=ROOT,
            env=dict(
                os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "tests"), str(ROOT)])
            ),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def _check_import_side_effects(self):
        # 의존 라이브러리 초기화와 실험 모듈 import를 분리해 검사한다.
        import joblib
        import transformers

        # lazy export를 파일 접근 차단 전에 해석한다.
        auto_tokenizer = transformers.AutoTokenizer
        auto_model = transformers.AutoModelForSequenceClassification
        modules = [
            ".".join(p.relative_to(ROOT).with_suffix("").parts)
            for p in (ROOT / "archive/classification_v1").rglob("*.py")
            if p.stem not in {"__init__", "document_split"}
        ]
        for name in modules:
            importlib.import_module(name)
        with (
            patch.object(Path, "open", side_effect=AssertionError("파일 접근 금지")),
            patch.object(
                Path, "read_text", side_effect=AssertionError("파일 읽기 금지")
            ),
            patch.object(
                Path, "write_text", side_effect=AssertionError("파일 쓰기 금지")
            ),
            patch.object(
                auto_tokenizer,
                "from_pretrained",
                side_effect=AssertionError("다운로드 금지"),
            ),
            patch.object(
                auto_model,
                "from_pretrained",
                side_effect=AssertionError("모델 로딩 금지"),
            ),
            patch.object(joblib, "dump", side_effect=AssertionError("모델 저장 금지")),
            patch("urllib.request.urlopen", side_effect=AssertionError("API 금지")),
            patch("subprocess.run", side_effect=AssertionError("자식 실행 금지")),
        ):
            for name in modules:
                importlib.reload(sys.modules[name])

    def test_all_preview_commands_work_without_network_or_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            # 자식 프로세스에서도 실제 연결 시도를 즉시 실패시킨다.
            (temp_path / "sitecustomize.py").write_text(
                "import socket\ndef deny(*args, **kwargs):\n    raise AssertionError('network forbidden')\nsocket.socket.connect = deny\nsocket.create_connection = deny\n"
            )
            env = dict(
                os.environ,
                PYTHONPATH=os.pathsep.join([temp, str(ROOT)]),
                TYPESAFE_API_KEY="",
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
            )
            for name in [*ENTRYPOINTS, "evaluate_jev"]:
                for invocation in (
                    [
                        str(
                            ROOT
                            / "archive/classification_v1/experiments"
                            / f"{name}.py"
                        )
                    ],
                    ["-m", f"archive.classification_v1.experiments.{name}"],
                ):
                    with self.subTest(command=invocation):
                        run = subprocess.run(
                            [sys.executable, *invocation, "--preview-questions"],
                            cwd=temp,
                            env=env,
                            capture_output=True,
                            text=True,
                            timeout=30,
                            check=False,
                        )
                        self.assertEqual(run.returncode, 0, run.stderr)
                        for count in ("632", "133", "135"):
                            self.assertIn(count, run.stdout)
            for name in ("train_koelectra_base", "train_tfidf", "evaluate_jev"):
                run = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        f"archive.classification_v1.experiments.{name}",
                        "--preview-documents",
                    ],
                    cwd=temp,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
            self.assertFalse((temp_path / "model").exists())
            self.assertFalse((temp_path / "result").exists())


if __name__ == "__main__":
    unittest.main()
