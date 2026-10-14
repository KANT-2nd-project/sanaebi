"""메모리 안에서 학습·선택·validation 평가를 연결한다. 저장과 실행 환경은 호출자가 맡는다."""

from time import perf_counter

from ..evaluation.metrics import evaluate
from ..types import FitFunction, Question, SelectionResult


def train(
    train_rows: list[Question],
    validation_rows: list[Question],
    fit: FitFunction,
    *,
    started_at=None,
) -> SelectionResult:
    started = perf_counter() if started_at is None else started_at
    fitted = fit(train_rows, validation_rows)
    selection_seconds = perf_counter() - started
    rows = validation_rows
    predictions = fitted.predict_batch([row["question"] for row in rows])
    scores = evaluate(
        [dict(row, text=row["question"]) for row in rows],
        [p.label for p in predictions],
    )
    return SelectionResult(fitted, scores, selection_seconds)
