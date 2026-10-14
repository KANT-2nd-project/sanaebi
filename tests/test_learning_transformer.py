"""네트워크 없이 작은 실제 Transformer로 학습/저장 계약을 검증한다."""

import unittest
from unittest.mock import patch

import test_learning_classification
import torch
from transformers import BertConfig, BertForSequenceClassification, BertTokenizer

from classification import transformer
from classification.evaluate import evaluate_bundle
from contracts.classification import LABELS


class TransformerTests(unittest.TestCase):
    def setUp(self):
        test_learning_classification.LearningEvaluationTests.setUp(self)
        self.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        self.addCleanup(torch.set_num_threads, self.old_threads)
        self.source = self.root / "source"
        self.source.mkdir()
        vocab = self.source / "vocab.txt"
        vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n질문\n", encoding="utf-8")
        tokenizer = BertTokenizer(vocab_file=str(vocab))
        tokenizer.save_pretrained(self.source)
        model = BertForSequenceClassification(
            BertConfig(
                vocab_size=6,
                hidden_size=8,
                num_hidden_layers=1,
                num_attention_heads=2,
                intermediate_size=16,
                num_labels=3,
                id2label=dict(enumerate(LABELS)),
                label2id={label: i for i, label in enumerate(LABELS)},
            )
        )
        model.save_pretrained(self.source)
        self.metadata.update(
            model_name="learning_transformer",
            labels=list(LABELS),
            config={"max_length": 16, "batch_size": 2},
        )
        self.bundle = self.root / "transformer"

    def train(self, **kwargs):
        return transformer.select_model(
            self.rows[:3],
            self.rows[3:6],
            model_name=str(self.source),
            max_length=16,
            batch_size=2,
            **kwargs,
        )

    def test_training_roundtrip_and_explicit_splits(self):
        fitted, selection = self.train(epochs=1)
        self.assertEqual(len(selection["trials"]), 1)
        self.assertTrue(all(p.grad is None for p in fitted.model.parameters()))
        transformer.save_bundle(
            fitted, self.bundle, self.metadata, [r["question"] for r in self.rows[3:6]]
        )
        val, _ = evaluate_bundle(
            self.bundle, self.dataset, output=self.root / "validation"
        )
        test, _ = evaluate_bundle(
            self.bundle, self.dataset, split="test", output=self.root / "test"
        )
        self.assertEqual(val["count"], 3)
        self.assertEqual(test["model_id"], val["model_id"])
        with self.assertRaises(FileExistsError):
            transformer.save_bundle(fitted, self.bundle, self.metadata, ["질문"])

    def test_first_best_snapshot_survives_later_updates_and_candidates(self):
        snapshots = []
        original = transformer.TransformerClassifier.predict

        def capture(fitted, texts):
            self.assertEqual(texts, [r["question"] for r in self.rows[3:6]])
            snapshots.append(
                {k: v.detach().clone() for k, v in fitted.model.state_dict().items()}
            )
            return original(fitted, texts)

        with (
            patch.object(transformer.TransformerClassifier, "predict", capture),
            patch.object(transformer, "f1_score", side_effect=[0.8, 0.8, 0.6, 0.7]),
        ):
            fitted, selection = self.train(epochs=2, learning_rates=(1e-3, 2e-3))
        self.assertEqual(selection["selected"], {"epoch": 1, "learning_rate": 1e-3})
        self.assertTrue(
            any(not torch.equal(snapshots[0][k], snapshots[1][k]) for k in snapshots[0])
        )
        for name, value in fitted.model.state_dict().items():
            self.assertTrue(torch.equal(value, snapshots[0][name]), name)

    def test_failed_reload_does_not_publish_and_existing_output_skips_training(self):
        fitted, _ = self.train(epochs=1)
        with (
            patch.object(transformer, "load_bundle", side_effect=ValueError("broken")),
            self.assertRaises(ValueError),
        ):
            transformer.save_bundle(fitted, self.bundle, self.metadata, ["질문"])
        self.assertFalse(self.bundle.exists())
        with patch.object(transformer, "select_model") as train:
            with self.assertRaises(SystemExit):
                transformer.main(["--output", str(self.root)])
            train.assert_not_called()
