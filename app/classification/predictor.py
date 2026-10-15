"""새 학습 저장본의 CPU 추론. 학습 모듈과 HTTP에 의존하지 않는다."""

import json
from pathlib import Path
from threading import Lock
from typing import cast

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from contracts.classification import LABELS, ClassificationLabel


class ClassificationUnavailable(Exception):
    """파일 부재·형식 오류 등으로 저장본을 사용할 수 없다."""


class ClassificationInferenceError(Exception):
    """로드된 모델의 추론이 실패했다."""


class TransformerClassifier:
    def __init__(self, model_path: Path):
        self.model_path = Path(model_path)
        self.model_id: str | None = None
        self._loaded = None
        self._lock = Lock()

    def _load(self):
        try:
            for name in ("metadata.json", "config.json", "model.safetensors"):
                if not (self.model_path / name).is_file():
                    raise ValueError("Missing model file")

            metadata = json.loads(
                (self.model_path / "metadata.json").read_text(encoding="utf-8")
            )

            if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
                raise ValueError("Invalid metadata version")

            labels = metadata.get("labels")
            model_id = metadata.get("model_id")
            config = metadata.get("config")

            if (
                not isinstance(labels, list)
                or len(labels) != len(LABELS)
                or any(not isinstance(label, str) for label in labels)
                or set(labels) != set(LABELS)
                or not isinstance(model_id, str)
                or not model_id.strip()
                or not isinstance(config, dict)
            ):
                raise ValueError("Invalid model metadata")

            max_length = config.get("max_length")

            if type(max_length) is not int or max_length <= 0:
                raise ValueError("Invalid maximum length")

            tokenizer = AutoTokenizer.from_pretrained(
                self.model_path, local_files_only=True
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                self.model_path, local_files_only=True, use_safetensors=True
            ).to("cpu")
            expected = dict(enumerate(labels))

            if (
                model.config.num_labels != len(labels)
                or model.config.id2label != expected
                or model.config.label2id != {label: i for i, label in expected.items()}
                or max_length > model.config.max_position_embeddings
            ):
                raise ValueError("Invalid model label mapping or maximum length")

            model.eval()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            raise ClassificationUnavailable("분류 모델을 사용할 수 없습니다.") from exc

        self.model_id = model_id
        self._loaded = tokenizer, model, max_length

    def predict(self, question: str) -> ClassificationLabel:
        # 초기화와 추론을 함께 직렬화한다. 실패한 초기화는 다음 요청에서 재시도한다.
        with self._lock:
            if self._loaded is None:
                self._load()
            tokenizer, model, max_length = self._loaded

            try:
                inputs = tokenizer(
                    question.strip(),
                    truncation=True,
                    max_length=max_length,
                    padding=False,
                    return_token_type_ids=False,
                    return_tensors="pt",
                )
                with torch.inference_mode():
                    logits = model(**inputs).logits
                if logits.shape != (1, len(LABELS)) or not torch.isfinite(logits).all():
                    raise ValueError("Invalid classifier scores")
                label = model.config.id2label[logits.argmax(dim=1).item()]
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                raise ClassificationInferenceError("분류 추론에 실패했습니다.") from exc

            return cast(ClassificationLabel, label)
