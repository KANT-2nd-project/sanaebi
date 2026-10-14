"""메모리 안에서 학습·선택·test 평가를 연결한다. 저장과 실행 환경은 호출자가 맡는다."""

from time import perf_counter

from ..evaluation.metrics import evaluate
from ..types import DatasetSplits, FitFunction, TrainingResult


def train(
    dataset: DatasetSplits, fit: FitFunction, *, started_at=None
) -> TrainingResult:
    started = perf_counter() if started_at is None else started_at
    fitted = fit(dataset.rows["train"], dataset.rows["validation"])
    selection_seconds = perf_counter() - started
    rows = dataset.rows["test"]
    predictions = fitted.predict_batch([row["question"] for row in rows])
    scores = evaluate(
        [dict(row, text=row["question"]) for row in rows],
        [p.label for p in predictions],
    )
    return TrainingResult(fitted, scores, selection_seconds)
