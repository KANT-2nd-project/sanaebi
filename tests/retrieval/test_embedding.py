import json
from types import SimpleNamespace
from unittest.mock import patch

import torch
import transformers

from app.retrieval.embedding import (
    MODEL_MANIFEST,
    MODEL_MANIFEST_FILENAME,
    TinyEmbedder,
)
from app.retrieval.types import RetrievalInputTooLong, RetrievalUnavailable
from tests.retrieval.helpers import RetrievalTestCase


class FakeTokenizer:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        texts,
        *,
        add_special_tokens=False,
        padding=False,
        truncation=False,
        return_tensors=None,
        **_,
    ):
        self.calls.append(texts)
        if isinstance(texts, str):
            ids = list(range(1, len(texts.split()) + 1))
            if add_special_tokens:
                ids = [101, *ids, 102]
            return {"input_ids": ids}
        rows = []
        for text in texts:
            ids = list(range(1, len(text.split()) + 1))
            if add_special_tokens:
                ids = [101, *ids, 102]
            rows.append(ids)
        width = max(map(len, rows))
        padded = [row + [0] * (width - len(row)) for row in rows]
        mask = [[1] * len(row) + [0] * (width - len(row)) for row in rows]
        return {
            "input_ids": torch.tensor(padded, dtype=torch.long),
            "attention_mask": torch.tensor(mask, dtype=torch.long),
        }


class FakeModel:
    def __init__(self):
        self.config = SimpleNamespace(hidden_size=384)
        self.is_eval = False
        self.device = None
        self.inference_calls = 0

    def to(self, device):
        self.device = device
        return self

    def eval(self):
        self.is_eval = True
        return self

    def __call__(self, input_ids, attention_mask):
        assert torch.is_inference_mode_enabled()
        self.inference_calls += 1
        output = torch.ones((*input_ids.shape, 384), dtype=torch.float32)
        return SimpleNamespace(last_hidden_state=output)


def prepare_model_dir(path):
    path.mkdir()
    (path / MODEL_MANIFEST_FILENAME).write_text(
        json.dumps(MODEL_MANIFEST), encoding="utf-8"
    )
    return path


def install_fakes(test_case):
    tokenizer = FakeTokenizer()
    model = FakeModel()
    tokenizer_calls = []
    model_calls = []

    def load_tokenizer(path, **kwargs):
        tokenizer_calls.append((path, kwargs))
        return tokenizer

    def load_model(path, **kwargs):
        model_calls.append((path, kwargs))
        return model

    tokenizer_patch = patch.object(
        transformers.AutoTokenizer, "from_pretrained", load_tokenizer
    )
    model_patch = patch.object(transformers.AutoModel, "from_pretrained", load_model)
    tokenizer_patch.start()
    model_patch.start()
    test_case.addCleanup(tokenizer_patch.stop)
    test_case.addCleanup(model_patch.stop)
    return tokenizer, model, tokenizer_calls, model_calls


class EmbeddingTests(RetrievalTestCase):
    def test_local_encoder_uses_fixed_manifest_cpu_eval_and_l2(self):
        model_dir = prepare_model_dir(self.tmp_path / "model")
        tokenizer, model, tokenizer_calls, model_calls = install_fakes(self)
        embedder = TinyEmbedder(model_dir)

        query = embedder.encode_queries(["휴가 신청 방법"])
        documents = embedder.encode_documents(["passage: 휴가 신청 방법"])

        self.assertEqual(query.shape, documents.shape)
        self.assertEqual(query.shape, (1, 384))
        self.assertAlmostEqual(
            float(torch.linalg.vector_norm(torch.from_numpy(query[0]))),
            1.0,
            places=5,
        )
        self.assertEqual(model.device, "cpu")
        self.assertIs(model.is_eval, True)
        self.assertEqual(model.inference_calls, 2)
        self.assertEqual(len(tokenizer_calls), 1)
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(
            tokenizer_calls[0][1],
            {"local_files_only": True, "trust_remote_code": False},
        )
        self.assertEqual(
            model_calls[0][1],
            {"local_files_only": True, "trust_remote_code": False},
        )
        self.assertTrue(
            any(
                isinstance(call, str) and call == "query: 휴가 신청 방법"
                for call in tokenizer.calls
            )
        )
        self.assertTrue(
            any(
                isinstance(call, list) and call == ["passage: 휴가 신청 방법"]
                for call in tokenizer.calls
            )
        )

    def test_encoder_rejects_wrong_manifest_before_loading(self):
        model_dir = prepare_model_dir(self.tmp_path / "model")
        (model_dir / MODEL_MANIFEST_FILENAME).write_text(
            json.dumps({**MODEL_MANIFEST, "revision": "wrong"}), encoding="utf-8"
        )
        _, _, tokenizer_calls, model_calls = install_fakes(self)

        with self.assertRaises(RetrievalUnavailable):
            TinyEmbedder(model_dir).warmup()

        self.assertEqual(tokenizer_calls, [])
        self.assertEqual(model_calls, [])

    def test_encoder_rejects_overlong_prefixed_question_without_inference(self):
        model_dir = prepare_model_dir(self.tmp_path / "model")
        _, model, _, _ = install_fakes(self)
        embedder = TinyEmbedder(model_dir)

        with self.assertRaises(RetrievalInputTooLong):
            embedder.encode_queries([" ".join("x" for _ in range(512))])

        self.assertEqual(model.inference_calls, 0)
