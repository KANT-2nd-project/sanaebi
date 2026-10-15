"""Pinned, local-only CPU encoder for KoEn-E5-Tiny."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from app.retrieval.config import (
    MODEL_ID,
    MODEL_REVISION,
    PASSAGE_PREFIX,
    POOLING,
    QUERY_PREFIX,
    VECTOR_DIMENSION,
)
from app.retrieval.types import RetrievalInputTooLong, RetrievalUnavailable

MODEL_MANIFEST_FILENAME = "retrieval-model.json"
MODEL_MANIFEST = {
    "model_id": MODEL_ID,
    "revision": MODEL_REVISION,
    "dimension": VECTOR_DIMENSION,
    "pooling": POOLING,
    "normalization": "l2",
    "query_prefix": QUERY_PREFIX,
    "passage_prefix": PASSAGE_PREFIX,
    "dtype": "float32",
}


class TinyEmbedder:
    """Lazily load the selected model from a verified local artifact directory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._tokenizer = None
        self._model = None
        self._torch = None

    @property
    def tokenizer(self):
        self.warmup()
        return self._tokenizer

    def warmup(self):
        with self._lock:
            if self._model is not None:
                return
            self._validate_manifest()
            try:
                import torch
                from transformers import AutoModel, AutoTokenizer

                torch.set_num_threads(1)
                tokenizer = AutoTokenizer.from_pretrained(
                    str(self.path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                model = AutoModel.from_pretrained(
                    str(self.path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                hidden_size = getattr(model.config, "hidden_size", None)
                if hidden_size != VECTOR_DIMENSION:
                    raise RetrievalUnavailable("임베딩 모델 차원이 계약과 다릅니다.")
                model.to("cpu")
                model.eval()
            except RetrievalUnavailable:
                raise
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                raise RetrievalUnavailable(
                    "로컬 임베딩 모델을 사용할 수 없습니다."
                ) from exc
            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, prefix=QUERY_PREFIX)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, prefix=PASSAGE_PREFIX, already_prefixed=True)

    def _validate_manifest(self):
        manifest_path = self.path / MODEL_MANIFEST_FILENAME
        if not self.path.is_dir() or not manifest_path.is_file():
            raise RetrievalUnavailable("고정된 로컬 임베딩 모델 자료가 없습니다.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RetrievalUnavailable(
                "임베딩 모델 식별 자료를 읽을 수 없습니다."
            ) from exc
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != value for key, value in MODEL_MANIFEST.items()
        ):
            raise RetrievalUnavailable("임베딩 모델 식별 정보가 계약과 다릅니다.")

    def _encode(self, texts: list[str], *, prefix: str, already_prefixed=False):
        if not isinstance(texts, list) or any(
            not isinstance(text, str) for text in texts
        ):
            raise TypeError("임베딩 입력은 문자열 목록이어야 합니다.")
        if not texts:
            return np.empty((0, VECTOR_DIMENSION), dtype=np.float32)

        prepared = [
            text if already_prefixed and text.startswith(prefix) else f"{prefix}{text}"
            for text in texts
        ]
        with self._lock:
            self.warmup()
            for text in prepared:
                try:
                    token_count = len(
                        self._tokenizer(
                            text,
                            add_special_tokens=True,
                            truncation=False,
                        )["input_ids"]
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    raise RetrievalUnavailable(
                        "질문 토큰 길이를 확인할 수 없습니다."
                    ) from exc
                if token_count > 512:
                    raise RetrievalInputTooLong(
                        "검색 입력이 임베딩 모델의 길이 제한을 넘습니다."
                    )
            try:
                encoded = self._tokenizer(
                    prepared,
                    add_special_tokens=True,
                    padding=True,
                    truncation=False,
                    return_tensors="pt",
                )
                encoded = {key: value.to("cpu") for key, value in encoded.items()}
                with self._torch.inference_mode():
                    hidden = self._model(**encoded).last_hidden_state
                    mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                    pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                    vectors = self._torch.nn.functional.normalize(
                        pooled.float(), p=2, dim=1
                    )
                result = vectors.detach().cpu().numpy().astype(np.float32, copy=False)
            except (OSError, RuntimeError, ValueError) as exc:
                raise RetrievalUnavailable("임베딩 계산에 실패했습니다.") from exc
        _validate_vectors(result, expected_rows=len(prepared))
        return result


def _validate_vectors(vectors, *, expected_rows=None):
    array = np.asarray(vectors, dtype=np.float32)
    if (
        array.ndim != 2
        or array.shape[1] != VECTOR_DIMENSION
        or (expected_rows is not None and array.shape[0] != expected_rows)
        or not np.isfinite(array).all()
    ):
        raise RetrievalUnavailable("임베딩 결과의 형식이 올바르지 않습니다.")
    norms = np.linalg.norm(array, axis=1)
    if array.shape[0] and not np.allclose(norms, 1.0, rtol=1e-4, atol=1e-4):
        raise RetrievalUnavailable("임베딩 결과가 정규화되지 않았습니다.")
