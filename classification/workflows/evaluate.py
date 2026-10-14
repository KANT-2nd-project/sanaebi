"""주어진 질문과 예측 함수로 평가한다. 모델 종류·인증·경로·HTML은 알지 못한다."""

from time import perf_counter

from threadpoolctl import threadpool_limits

from ..evaluation.metrics import evaluate, summarize_durations
from ..types import EvaluationResult, MeasurementPolicy, Predictor


def evaluate_questions(
    rows_by_split, predict: Predictor, policy=None, *, split="validation"
) -> EvaluationResult:
    """명시한 한 분할만 채점하고 같은 분할에서 속도를 측정한다."""
    if split not in {"validation", "test"}:
        raise ValueError("평가 분할은 validation 또는 test여야 합니다.")
    return _evaluate(rows_by_split, predict, policy, (split,), split)


def evaluate_legacy_questions(
    rows_by_split, predict: Predictor, policy=None
) -> EvaluationResult:
    """구형 로컬/Jev 실험의 두 분할·test 시간 측정 계약만 보존한다."""
    return _evaluate(rows_by_split, predict, policy, ("validation", "test"), "test")


def _evaluate(rows_by_split, predict, policy, splits, measured_split):
    policy = MeasurementPolicy() if policy is None else policy
    if any(not rows_by_split.get(name) for name in splits):
        raise ValueError("평가 질문은 비어 있을 수 없습니다.")
    scores, records, durations, versions, tokens = {}, [], [], set(), []
    with threadpool_limits(limits=policy.cpu_threads):
        for split in splits:
            rows = rows_by_split[split]
            labels = []
            for row in rows:
                started = perf_counter()
                prediction = predict(row["question"])
                elapsed_ms = (perf_counter() - started) * 1000
                labels.append(prediction.label)
                if policy.mode == "request" and split == measured_split:
                    durations.append(elapsed_ms)
                if prediction.model:
                    versions.add(prediction.model)
                tokens.append(prediction.input_tokens)
                records.append(
                    {
                        "split": split,
                        "question_id": row["question_id"],
                        "input_text": row["question"],
                        "actual": row["label"],
                        "predicted": prediction.label,
                        "confidence": prediction.confidence,
                        "probabilities": prediction.probabilities,
                        "model": prediction.model,
                        "elapsed_ms": elapsed_ms,
                    }
                )
            scores[split] = evaluate(
                [dict(row, text=row["question"]) for row in rows], labels
            )
        if policy.mode == "repeated":
            for _ in range(policy.warmup):
                predict(rows_by_split[measured_split][0]["question"])
            for _ in range(policy.repeats):
                for row in rows_by_split[measured_split]:
                    started = perf_counter()
                    predict(row["question"])
                    durations.append((perf_counter() - started) * 1000)
    return EvaluationResult(
        scores,
        records,
        summarize_durations(durations),
        policy.cpu_threads,
        sorted(versions),
        sum(tokens) if all(isinstance(t, int) for t in tokens) else None,
    )
