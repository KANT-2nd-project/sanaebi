"""실험 단계의 입력·출력 계약. 파일 접근과 모델 라이브러리에 의존하지 않는다."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from contracts.classification import LABELS, ClassificationLabel

DEFAULT_SEED = 20261013

Question = dict[str, str]


def validate_label(value: object) -> ClassificationLabel:
    if not isinstance(value, str) or value not in LABELS:
        raise ValueError(f"허용되지 않은 분류 라벨: {value!r}")
    return cast(ClassificationLabel, value)


@dataclass(frozen=True)
class Prediction:
    label: ClassificationLabel
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    model: str | None = None
    input_tokens: int | None = None

    def __post_init__(self):
        validate_label(self.label)


Predictor = Callable[[str], Prediction]


@dataclass(frozen=True)
class DatasetSplits:
    rows: dict[str, list[Question]]
    record: dict
    hashes: dict[str, str]


@dataclass(frozen=True)
class FittedModel:
    """선택된 모델과 기록. save는 명시적으로 호출하기 전에는 실행되지 않는다."""

    predict: Predictor
    save: Callable[[Path], None]
    settings: dict
    # 선택된 모델의 배치 추론. validation 평가와 명시적 평가에서 사용한다.
    predict_batch: Callable[[list[str]], list[Prediction]]


FitFunction = Callable[[list[Question], list[Question]], FittedModel]


@dataclass(frozen=True)
class SelectionResult:
    fitted: FittedModel
    validation_scores: dict
    selection_seconds: float


@dataclass(frozen=True)
class MeasurementPolicy:
    mode: Literal["none", "repeated", "request"] = "none"
    warmup: int = 0
    repeats: int = 0
    cpu_threads: int | None = None

    def __post_init__(self):
        if self.mode not in {"none", "repeated", "request"}:
            raise ValueError("알 수 없는 측정 정책입니다.")
        if self.mode != "repeated" and (self.warmup or self.repeats):
            raise ValueError("요청 시간 측정에는 추가 예측을 실행하지 않습니다.")
        if (
            self.warmup < 0
            or self.repeats < 0
            or (self.mode == "repeated" and self.repeats < 1)
        ):
            raise ValueError("측정 횟수가 올바르지 않습니다.")


@dataclass(frozen=True)
class EvaluationResult:
    scores: dict[str, dict]
    predictions: list[dict]
    timing: dict
    cpu_threads: int | None = None
    resolved_models: list[str] = field(default_factory=list)
    input_tokens: int | None = None
