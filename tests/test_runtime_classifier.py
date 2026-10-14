"""다운로드 없이 작은 텐서로 로딩·매핑·동시성 계약을 확인한다."""

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import torch

from app.infrastructure.classifier import (
    ClassificationInferenceError,
    ClassificationUnavailable,
    TransformerClassifier,
)
from app.model_settings import PROJECT_ROOT, get_classifier_path
from contracts.classification import LABELS


class RuntimeClassifierTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.labels = list(reversed(LABELS))
        self.metadata = {
            "schema_version": 1,
            "model_id": "fixture-model",
            "labels": self.labels,
            "config": {"max_length": 256},
        }
        self.write_metadata()
        (self.root / "config.json").write_text("{}")
        (self.root / "model.safetensors").touch()
        self.model = Mock()
        self.model.to.return_value = self.model
        self.model.config = SimpleNamespace(
            num_labels=3,
            id2label=dict(enumerate(self.labels)),
            label2id={label: i for i, label in enumerate(self.labels)},
            max_position_embeddings=512,
        )
        self.model.return_value = SimpleNamespace(
            logits=torch.tensor([[9.0, 1.0, 0.0]])
        )
        self.tokenizer = Mock(return_value={"input_ids": torch.tensor([[1, 2]])})
        self.load_model = self.enterContext(
            patch(
                "app.infrastructure.classifier.AutoModelForSequenceClassification.from_pretrained",
                return_value=self.model,
            )
        )
        self.load_tokenizer = self.enterContext(
            patch(
                "app.infrastructure.classifier.AutoTokenizer.from_pretrained",
                return_value=self.tokenizer,
            )
        )

    def write_metadata(self):
        (self.root / "metadata.json").write_text(json.dumps(self.metadata))

    def test_saved_label_order_and_local_loading_shared_across_threads(self):
        classifier = TransformerClassifier(self.root)
        self.load_model.assert_not_called()
        with ThreadPoolExecutor(max_workers=4) as pool:
            labels = list(pool.map(classifier.predict, [" 질문 "] * 8))
        self.assertEqual(labels, [self.labels[0]] * 8)
        self.assertEqual(classifier.model_id, "fixture-model")
        self.load_model.assert_called_once_with(
            self.root, local_files_only=True, use_safetensors=True
        )
        self.load_tokenizer.assert_called_once_with(self.root, local_files_only=True)
        self.model.to.assert_called_once_with("cpu")
        self.model.eval.assert_called_once_with()
        self.assertEqual(self.tokenizer.call_args.args, ("질문",))
        self.assertEqual(self.tokenizer.call_args.kwargs["max_length"], 256)

    def test_missing_files_and_bad_metadata_fail_before_model_load(self):
        for metadata in (
            {},
            [],
            {**self.metadata, "labels": ["BAD"]},
            {**self.metadata, "config": {"max_length": True}},
        ):
            (self.root / "metadata.json").write_text(json.dumps(metadata))
            with self.assertRaises(ClassificationUnavailable):
                TransformerClassifier(self.root).predict("질문")
        self.write_metadata()
        (self.root / "model.safetensors").unlink()
        with self.assertRaises(ClassificationUnavailable):
            TransformerClassifier(self.root).predict("질문")
        self.load_model.assert_not_called()

    def test_mismatched_labels_rejects_loaded_model(self):
        self.model.config.id2label = dict(enumerate(LABELS))
        with self.assertRaises(ClassificationUnavailable):
            TransformerClassifier(self.root).predict("질문")
        self.model.assert_not_called()

    def test_inference_failure_is_distinct_from_load_failure(self):
        self.model.side_effect = RuntimeError("private device detail")
        with self.assertRaises(ClassificationInferenceError):
            TransformerClassifier(self.root).predict("질문")

    def test_nonfinite_logits_rejected(self):
        self.model.return_value.logits = torch.tensor([[float("nan"), 1.0, 2.0]])
        with self.assertRaises(ClassificationInferenceError):
            TransformerClassifier(self.root).predict("질문")

    def test_new_instance_selects_different_path_and_relative_config(self):
        other = self.root / "other"
        other.mkdir()
        for name in ("metadata.json", "config.json", "model.safetensors"):
            (other / name).write_bytes((self.root / name).read_bytes())
        TransformerClassifier(other).predict("질문")
        self.assertEqual(self.load_model.call_args.args, (other,))
        with patch.dict(os.environ, {"SANAEBI_CLASSIFIER_PATH": "artifacts/custom"}):
            self.assertEqual(get_classifier_path(), PROJECT_ROOT / "artifacts/custom")
