"""실험 결과의 저장 계약. 구체 모델을 선택하거나 학습하지 않는다."""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contracts.classification import LABELS

from .types import DatasetSplits, EvaluationResult, TrainingResult

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "model"
RESULT_DIR = ROOT / "result"


def report_dir(kind, result_dir=RESULT_DIR):
    return result_dir / ("tf-idf" if kind == "tfidf_lr" else kind)


def save_json(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def model_size_mib(path):
    files = list(path.rglob("*")) if path.is_dir() else [path]
    return (
        sum(
            p.stat().st_size
            for p in files
            if p.is_file() and p.name != "training_summary.json"
        )
        / 1024**2
    )


def training_summary(
    result: TrainingResult, dataset: DatasetSplits, *, include_test=False
):
    summary = dict(
        result.fitted.settings,
        data_split=dataset.record,
        selection_seconds=result.selection_seconds,
    )
    if include_test:
        summary.update(
            test_accuracy=result.test_scores["accuracy"],
            test_macro_f1=result.test_scores["macro_f1"],
            test_confusion_matrix=result.test_scores["confusion_matrix"],
        )
    return summary


def save_training(result, summary, model_path, summary_path):
    # 저장 실패 시 후속 성공 기록이나 평가를 실행하지 않는다.
    result.fitted.save(model_path)
    save_json(summary_path, summary)


def evaluation_report(
    result: EvaluationResult,
    dataset: DatasetSplits,
    *,
    title,
    settings,
    model_size=None,
    load_seconds=None,
    rss=None,
    api=False,
    train_count=None,
):
    counts = {name: len(rows) for name, rows in dataset.rows.items()}
    if train_count is not None:
        counts["train"] = train_count
    benchmark = {"load_seconds": load_seconds, **result.timing, "process_rss_mib": rss}
    if api:
        benchmark["mode"] = "api"
    return {
        "title": title,
        "created_at": datetime.now(timezone(timedelta(hours=9))).strftime(
            "%Y-%m-%d %H:%M KST"
        ),
        "counts": counts,
        "data_hashes": dataset.hashes,
        "settings": settings,
        "validation": result.scores["validation"],
        "test": result.scores["test"],
        "model_size_mib": model_size,
        "benchmark": benchmark,
    }


def save_probability_csv(output_dir, predictions):
    fields = ["split", "question_id", "input_text", "actual", "predicted", "confidence"]
    with (output_dir / "prediction_probabilities.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=fields + [f"{label}_percent" for label in LABELS]
        )
        writer.writeheader()
        for prediction in predictions:
            row = {key: prediction.get(key, "") for key in fields}
            for label in LABELS:
                probability = (prediction.get("probabilities") or {}).get(label)
                row[f"{label}_percent"] = (
                    round(probability * 100, 2) if probability is not None else ""
                )
            writer.writerow(row)


def save_evaluation(
    kind, report, result, result_dir=RESULT_DIR, *, save_predictions=False
):
    output = report_dir(kind, result_dir)
    save_json(output / "metrics.json", report)
    if save_predictions:
        save_json(output / "predictions.json", result.predictions)
        save_probability_csv(output, result.predictions)


def is_current_report(report):
    settings = report.get("settings", {})
    record = settings.get("data_split") or {}
    return settings.get("labels") == list(LABELS) and record.get("input_fields") == [
        "question"
    ]


def save_html(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_reports(result_dir):
    return {
        path.parent.name: read_json(path)
        for path in sorted(result_dir.glob("*/metrics.json"))
    }
