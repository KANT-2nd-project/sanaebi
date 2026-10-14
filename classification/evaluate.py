"""저장된 학습용 모델을 지정한 분할에서만 평가한다. 학습하지 않는다."""

import argparse
from pathlib import Path

import joblib
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

from classification.dataset import DATASET_PATH, prepare_rows
from classification.persistence import (
    file_sha,
    read_metadata,
    save_evaluation,
    split_id,
)
from contracts.classification import LABELS


def restore_rows(metadata, dataset_path, split):
    if split not in {"validation", "test"}:
        raise ValueError("평가 분할은 validation 또는 test입니다.")

    if metadata.get("schema_version") != 1 or metadata.get("model_name") not in {
        "learning_tfidf",
        "learning_transformer",
    }:
        raise ValueError("지원하는 학습용 모델 기록이 아닙니다.")

    if not isinstance(metadata.get("model_id"), str) or not metadata["model_id"]:
        raise ValueError("model_id가 없습니다.")

    if set(metadata.get("labels", [])) != set(LABELS) or len(metadata["labels"]) != len(
        LABELS
    ):
        raise ValueError("모델 라벨이 현재 계약과 다릅니다.")

    if file_sha(dataset_path) != metadata.get("dataset_sha256"):
        raise ValueError("학습 당시 데이터와 다릅니다.")

    ids = metadata.get("question_ids")

    if not isinstance(ids, dict) or set(ids) != {"train", "validation", "test"}:
        raise ValueError("분할 기록이 잘못되었습니다.")

    if any(
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) for value in values)
        for values in ids.values()
    ):
        raise ValueError("분할 문항 ID가 잘못되었습니다.")

    if split_id(ids) != metadata.get("split_id"):
        raise ValueError("분할 식별값이 기록과 다릅니다.")

    rows = prepare_rows(dataset_path)
    by_id = {row["question_id"]: row for row in rows}
    all_ids = [qid for values in ids.values() for qid in values]

    if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(by_id):
        raise ValueError("분할에 중복되거나 누락된 문항이 있습니다.")

    groups = [{by_id[qid]["group_id"] for qid in values} for values in ids.values()]

    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("분할 사이 그룹이 겹칩니다.")

    for values in ids.values():
        if {by_id[qid]["label"] for qid in values} != set(LABELS):
            raise ValueError("분할에 빠진 라벨이 있습니다.")

    return [by_id[qid] for qid in ids[split]]


def evaluate_bundle(bundle, dataset_path=DATASET_PATH, split="validation", output=None):
    if output is not None and Path(output).exists():
        raise FileExistsError(f"기존 결과를 보존합니다: {output}")

    metadata = read_metadata(bundle)
    rows = restore_rows(metadata, dataset_path, split)

    if metadata["model_name"] == "learning_transformer":
        from classification.transformer import load_bundle

        model = load_bundle(bundle, metadata)
    else:
        model = joblib.load(Path(bundle) / "model.joblib")

    if list(model.classes_) != metadata["labels"]:
        raise ValueError("저장 모델의 라벨 순서와 메타데이터가 다릅니다.")

    predictions = model.predict([row["question"] for row in rows]).tolist()

    if len(predictions) != len(rows) or not set(predictions) <= set(LABELS):
        raise ValueError("모델 예측의 개수 또는 라벨이 잘못되었습니다.")

    actual = [row["label"] for row in rows]

    metrics = {
        "model_id": metadata["model_id"],
        "dataset_sha256": metadata["dataset_sha256"],
        "split_id": metadata["split_id"],
        "split": split,
        "count": len(rows),
        "accuracy": float(accuracy_score(actual, predictions)),
        "macro_f1": float(
            f1_score(
                actual, predictions, labels=LABELS, average="macro", zero_division=0
            )
        ),
        "labels": list(LABELS),
        "confusion_matrix": confusion_matrix(
            actual, predictions, labels=LABELS
        ).tolist(),
        "classification_report": classification_report(
            actual, predictions, labels=LABELS, output_dict=True, zero_division=0
        ),
        "test_exposure": "이미 열람한 합성 개발 평가 자료",
    }

    records = [
        {
            "question_id": row["question_id"],
            "question": row["question"],
            "actual": row["label"],
            "predicted": predicted,
        }
        for row, predicted in zip(rows, predictions)
    ]

    if output is not None:
        save_evaluation(output, metrics, records)

    print(
        f"{split}: {len(rows)}건, accuracy={metrics['accuracy']:.6f}, Macro-F1={metrics['macro_f1']:.6f}"
    )

    return metrics, records


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="저장된 학습용 모델 평가. 기본 validation, test는 명시적으로만 예측."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument(
        "--output", type=Path, help="새 결과 폴더. 생략하면 저장하지 않음"
    )
    args = parser.parse_args(argv)
    evaluate_bundle(args.bundle, args.dataset, args.split, args.output)


if __name__ == "__main__":
    main()
