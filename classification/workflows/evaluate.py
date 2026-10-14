"""주어진 질문과 예측 함수로 평가한다. 모델 종류·인증·경로·HTML은 알지 못한다."""

from time import perf_counter

from threadpoolctl import threadpool_limits

from ..evaluation import evaluate, summarize_durations
from ..types import EvaluationResult, MeasurementPolicy, Predictor


def evaluate_questions(
    rows_by_split, predict: Predictor, policy=None
) -> EvaluationResult:
    policy = MeasurementPolicy() if policy is None else policy
    if not rows_by_split.get("validation") or not rows_by_split.get("test"):
        raise ValueError("검증·테스트 질문은 비어 있을 수 없습니다.")
    scores, records, durations, versions, tokens = {}, [], [], set(), []
    with threadpool_limits(limits=policy.cpu_threads):
        for split in ("validation", "test"):
            rows = rows_by_split[split]
            labels = []
            for row in rows:
                started = perf_counter()
                prediction = predict(row["question"])
                elapsed_ms = (perf_counter() - started) * 1000
                labels.append(prediction.label)
                if policy.mode == "request" and split == "test":
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
                predict(rows_by_split["test"][0]["question"])
            for _ in range(policy.repeats):
                for row in rows_by_split["test"]:
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
