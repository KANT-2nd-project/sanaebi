"""Pinned, local-only CPU encoders for Tiny and KURE retrieval profiles."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from app.retrieval.config import (
    DEFAULT_SPEC,
    KURE_MODEL_ID,
    KURE_SPEC,
    MODEL_ID,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    SERVER_SPEC,
    VECTOR_DIMENSION,
    RetrievalSpec,
)
from app.retrieval.types import RetrievalInputTooLong, RetrievalUnavailable

MODEL_MANIFEST_FILENAME = "retrieval-model.json"


def model_manifest(spec: RetrievalSpec = DEFAULT_SPEC) -> dict:
    """Return the exact local sidecar contract for a retrieval model profile."""
    manifest = {
        "model_id": spec.model_id,
        "revision": spec.model_revision,
        "dimension": spec.dimension,
        "pooling": spec.pooling,
        "normalization": spec.normalization,
        "query_prefix": spec.query_prefix,
        "passage_prefix": spec.passage_prefix,
        "dtype": spec.dtype,
    }
    if spec.model_id == KURE_MODEL_ID:
        manifest.update(
            {
                "max_length": spec.max_document_tokens,
                "query_max_length": spec.max_query_tokens,
                "splitter": {
                    "model_id": spec.splitter_model_id,
                    "revision": spec.splitter_model_revision,
                    "directory": spec.splitter_directory,
                },
            }
        )
    return manifest


MODEL_MANIFEST = model_manifest(DEFAULT_SPEC)


class TinyEmbedder:
    """Lazily load the selected model from a verified local artifact directory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.spec = DEFAULT_SPEC
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
                if hidden_size != DEFAULT_SPEC.dimension:
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
            return np.empty((0, DEFAULT_SPEC.dimension), dtype=np.float32)

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
        _validate_vectors(
            result, expected_rows=len(prepared), dimension=DEFAULT_SPEC.dimension
        )
        return result


class KureEmbedder:
    """Pinned KURE-v1 CLS encoder with the frozen Tiny document splitter."""

    def __init__(
        self,
        path: str | Path,
        splitter_path: str | Path | None = None,
        *,
        spec: RetrievalSpec = KURE_SPEC,
    ):
        self.path = Path(path)
        if not _same_model_contract(spec, KURE_SPEC):
            raise RetrievalUnavailable("KURE 모델 spec이 지원 계약과 다릅니다.")
        self.spec = spec
        self.splitter_path = (
            Path(splitter_path)
            if splitter_path is not None
            else self.path / spec.splitter_directory
        )
        self._lock = threading.RLock()
        self._tokenizer = None
        self._splitter_tokenizer = None
        self._model = None
        self._torch = None

    @property
    def tokenizer(self):
        self.warmup()
        return self._tokenizer

    @property
    def splitter_tokenizer(self):
        self.warmup()
        return self._splitter_tokenizer

    def warmup(self):
        with self._lock:
            if self._model is not None:
                return
            self._validate_manifest()
            self._validate_pooling_config()
            try:
                import torch
                from transformers import AutoModel, AutoTokenizer

                torch.set_num_threads(2)
                tokenizer = AutoTokenizer.from_pretrained(
                    str(self.path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                splitter_tokenizer = AutoTokenizer.from_pretrained(
                    str(self.splitter_path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                model = AutoModel.from_pretrained(
                    str(self.path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                hidden_size = getattr(model.config, "hidden_size", None)
                if hidden_size != KURE_SPEC.dimension:
                    raise RetrievalUnavailable("임베딩 모델 차원이 계약과 다릅니다.")
                model.float()
                model.to("cpu")
                model.eval()
            except RetrievalUnavailable:
                raise
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                raise RetrievalUnavailable(
                    "로컬 KURE 임베딩 모델을 사용할 수 없습니다."
                ) from exc
            self._torch = torch
            self._tokenizer = tokenizer
            self._splitter_tokenizer = splitter_tokenizer
            self._model = model

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, maximum=self.spec.max_query_tokens, label="질문")

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, maximum=self.spec.max_document_tokens, label="문서")

    def _validate_manifest(self):
        manifest_path = self.path / MODEL_MANIFEST_FILENAME
        required_files = (
            "config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        )
        if (
            not self.path.is_dir()
            or not manifest_path.is_file()
            or not self.splitter_path.is_dir()
            or any(not (self.splitter_path / name).is_file() for name in required_files)
        ):
            raise RetrievalUnavailable(
                "고정된 KURE 또는 분할 tokenizer 자료가 없습니다."
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RetrievalUnavailable(
                "KURE 모델 식별 자료를 읽을 수 없습니다."
            ) from exc
        if manifest != model_manifest(self.spec):
            raise RetrievalUnavailable("KURE 모델 식별 정보가 계약과 다릅니다.")

    def _validate_pooling_config(self):
        path = self.path / "1_Pooling" / "config.json"
        try:
            pooling = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RetrievalUnavailable("KURE pooling 설정을 읽을 수 없습니다.") from exc
        if (
            not isinstance(pooling, dict)
            or pooling.get("pooling_mode_cls_token") is not True
            or pooling.get("pooling_mode_mean_tokens") is not False
        ):
            raise RetrievalUnavailable("KURE pooling 설정이 CLS 계약과 다릅니다.")

    def _encode(self, texts: list[str], *, maximum: int, label: str):
        if not isinstance(texts, list) or any(
            not isinstance(text, str) for text in texts
        ):
            raise TypeError("임베딩 입력은 문자열 목록이어야 합니다.")
        if not texts:
            return np.empty((0, KURE_SPEC.dimension), dtype=np.float32)

        with self._lock:
            self.warmup()
            for text in texts:
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
                        f"{label} 토큰 길이를 확인할 수 없습니다."
                    ) from exc
                if token_count > maximum:
                    raise RetrievalInputTooLong(
                        f"{label} 임베딩 입력이 모델 길이 제한을 넘습니다."
                    )
            try:
                encoded = self._tokenizer(
                    texts,
                    add_special_tokens=True,
                    padding=True,
                    truncation=False,
                    return_tensors="pt",
                )
                encoded = {key: value.to("cpu") for key, value in encoded.items()}
                with self._torch.inference_mode():
                    hidden = self._model(**encoded).last_hidden_state
                    cls = hidden[:, 0]
                    vectors = self._torch.nn.functional.normalize(
                        cls.float(), p=2, dim=1
                    )
                result = vectors.detach().cpu().numpy().astype(np.float32, copy=False)
            except (OSError, RuntimeError, ValueError) as exc:
                raise RetrievalUnavailable("KURE 임베딩 계산에 실패했습니다.") from exc
        _validate_vectors(
            result, expected_rows=len(texts), dimension=self.spec.dimension
        )
        return result


def create_embedder(
    path: str | Path,
    *,
    spec: RetrievalSpec = SERVER_SPEC,
    splitter_path: str | Path | None = None,
):
    """Construct the local encoder required by an explicit retrieval spec."""
    if spec.model_id == KURE_MODEL_ID:
        if not _same_model_contract(spec, KURE_SPEC):
            raise RetrievalUnavailable("KURE 모델 spec이 지원 계약과 다릅니다.")
        return KureEmbedder(path, splitter_path=splitter_path, spec=spec)
    if spec.model_id == MODEL_ID and _same_model_contract(spec, DEFAULT_SPEC):
        if splitter_path is not None:
            raise ValueError("the Tiny profile does not accept a splitter path")
        return TinyEmbedder(path)
    raise RetrievalUnavailable("요청한 임베딩 모델 spec을 지원하지 않습니다.")


def _same_model_contract(left: RetrievalSpec, right: RetrievalSpec) -> bool:
    fields = (
        "model_id",
        "model_revision",
        "dimension",
        "dtype",
        "pooling",
        "normalization",
        "query_prefix",
        "passage_prefix",
        "max_query_tokens",
        "max_document_tokens",
        "splitter_model_id",
        "splitter_model_revision",
        "splitter_directory",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _validate_vectors(vectors, *, expected_rows=None, dimension=VECTOR_DIMENSION):
    array = np.asarray(vectors, dtype=np.float32)
    if (
        array.ndim != 2
        or array.shape[1] != dimension
        or (expected_rows is not None and array.shape[0] != expected_rows)
        or not np.isfinite(array).all()
    ):
        raise RetrievalUnavailable("임베딩 결과의 형식이 올바르지 않습니다.")
    norms = np.linalg.norm(array, axis=1)
    if array.shape[0] and not np.allclose(norms, 1.0, rtol=1e-4, atol=1e-4):
        raise RetrievalUnavailable("임베딩 결과가 정규화되지 않았습니다.")
