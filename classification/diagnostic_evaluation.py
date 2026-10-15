"""고정 외부 질문의 런타임 분류 예측과 오류를 보존한다. 학습하지 않는다."""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from sklearn.metrics import classification_report, confusion_matrix, f1_score

from classification.persistence import file_sha, read_metadata, save_evaluation
from contracts.classification import LABELS


def load_cases(path):
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("비어 있지 않은 질문 목록이 필요합니다.")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or any(
            not isinstance(case.get(key), str) or not case[key].strip()
            for key in ("id", "group_id", "question", "source")
        ):
            raise ValueError("질문 ID·그룹·본문·출처가 필요합니다.")
        if case["id"] in seen or case.get("expected_label") not in LABELS:
            raise ValueError("중복 ID 또는 잘못된 라벨입니다.")
        if type(case.get("pure_lookup_execution")) is not bool:
            raise ValueError("순수 조회·실행 여부를 명시해야 합니다.")
        if case["pure_lookup_execution"] and case["expected_label"] != "UNSUPPORTED":
            raise ValueError("순수 조회·실행의 기대 라벨은 UNSUPPORTED입니다.")
        seen.add(case["id"])
    return cases


def score_records(records):
    actual = [r["expected_label"] for r in records]
    predicted = [r["predicted_label"] for r in records]
    report = classification_report(
        actual, predicted, labels=LABELS, output_dict=True, zero_division=0
    )
    return {
        "count": len(records),
        "correct": sum(a == p for a, p in zip(actual, predicted)),
        "macro_f1": float(
            f1_score(actual, predicted, labels=LABELS, average="macro", zero_division=0)
        ),
        "labels": list(LABELS),
        "confusion_matrix": confusion_matrix(actual, predicted, labels=LABELS).tolist(),
        "classification_report": report,
        "search_to_unsupported": sum(
            a == "SEARCH_KNOWLEDGE" and p == "UNSUPPORTED"
            for a, p in zip(actual, predicted)
        ),
        "clarify_correct": sum(a == p == "CLARIFY" for a, p in zip(actual, predicted)),
        "pure_lookup_execution_to_search": sum(
            r["pure_lookup_execution"] and r["predicted_label"] == "SEARCH_KNOWLEDGE"
            for r in records
        ),
        "expected_counts": dict(Counter(actual)),
    }


def evaluate_cases(bundle, cases_path, output):
    # Validate data and output before loading expensive weights.
    if Path(output).exists():
        raise FileExistsError(f"기존 결과를 보존합니다: {output}")
    cases = load_cases(cases_path)
    sha = file_sha(cases_path)
    metadata = read_metadata(bundle)
    from app.classification.predictor import TransformerClassifier

    model = TransformerClassifier(bundle)
    records = []
    for case in cases:
        started = time.perf_counter()
        predicted = model.predict(case["question"])
        records.append(
            {
                **case,
                "predicted_label": predicted,
                "correct": predicted == case["expected_label"],
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
    if file_sha(cases_path) != sha:
        raise ValueError("실행 중 평가 자료가 변경되었습니다.")
    metrics = {
        **score_records(records),
        "model_id": model.model_id,
        "model_metadata_sha256": file_sha(Path(bundle) / "metadata.json"),
        "training_dataset_sha256": metadata["dataset_sha256"],
        "cases_sha256": sha,
        "timing_note": "CPU runtime predict; first item includes model loading",
    }
    save_evaluation(output, metrics, records)
    return metrics, records


def promotion_checks(
    baseline_validation, candidate_validation, regression, fresh, criteria
):
    """사전 고정 기준. 결과를 본 뒤 임계값을 수정하지 않는다."""
    return {
        "validation_macro_f1": candidate_validation["macro_f1"]
        >= baseline_validation["macro_f1"] - criteria["validation_macro_f1_max_drop"],
        "regression_correct": regression["correct"]
        >= criteria["regression_min_correct"],
        "regression_search_rejection": regression["search_to_unsupported"]
        <= criteria["regression_max_search_to_unsupported"],
        "regression_clarify": regression["clarify_correct"]
        >= criteria["regression_min_clarify_correct"],
        "fresh_correct": fresh["correct"] >= criteria["fresh_min_correct"],
        "fresh_recall": all(
            fresh["classification_report"][label]["recall"]
            >= criteria["fresh_min_per_label_recall"]
            for label in LABELS
        ),
        "no_unsafe_search": regression["pure_lookup_execution_to_search"]
        + fresh["pure_lookup_execution_to_search"]
        <= criteria["pure_lookup_execution_max_search"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    metrics, _ = evaluate_cases(args.bundle, args.cases, args.output)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
