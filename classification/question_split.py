"""요청 처리 분류용 질문의 공통 분할과 평가 데이터 복원."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from sklearn.model_selection import GroupShuffleSplit

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "dataset.csv"
RANDOM_SEED = 20261013
LABELS = ["SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"]


def question_input(row):
    # ID·그룹·출처·검수 상태·정답은 모델 입력에 포함하지 않음
    return row["question"]


def validate_rows(rows):
    ids = [row["question_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("중복된 question_id가 있습니다.")
    if any(not row["group_id"].strip() for row in rows):
        raise ValueError("group_id는 비어 있을 수 없습니다.")
    if any(not question_input(row).strip() for row in rows):
        raise ValueError("질문은 비어 있을 수 없습니다.")
    if any(row["label"] not in LABELS for row in rows):
        raise ValueError("질문 라벨이 현재 요청 처리 3개 카테고리와 맞지 않습니다.")


def split_questions(question_rows, seed=RANDOM_SEED):
    rows = sorted(question_rows, key=lambda row: row["question_id"])
    validate_rows(rows)
    groups = [row["group_id"] for row in rows]

    # 전체 그룹의 약 15%를 테스트로 분리
    test_splitter = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=seed)
    remaining_indices, test_indices = next(test_splitter.split(rows, groups=groups))
    remaining_rows = [rows[index] for index in remaining_indices]
    remaining_groups = [row["group_id"] for row in remaining_rows]

    # 남은 85%에서 약 15/85를 검증으로 분리 (전체 기준 약 15%)
    validation_splitter = GroupShuffleSplit(
        n_splits=1, test_size=0.15 / 0.85, random_state=seed
    )
    train_indices, validation_indices = next(
        validation_splitter.split(remaining_rows, groups=remaining_groups)
    )
    splits = {
        "train": [remaining_rows[index] for index in train_indices],
        "validation": [remaining_rows[index] for index in validation_indices],
        "test": [rows[index] for index in test_indices],
    }
    for name, data in splits.items():
        data.sort(key=lambda row: row["question_id"])
        if {row["label"] for row in data} != set(LABELS):
            raise ValueError(f"{name} 분할에는 3개 라벨이 모두 필요합니다.")
    return splits


def split_input_hashes(splits):
    return {
        name: hashlib.sha256(
            json.dumps(
                [
                    (row["question_id"], question_input(row), row["label"])
                    for row in rows
                ],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        for name, rows in splits.items()
    }


def make_split_record(splits, dataset_path=DATASET_PATH, seed=RANDOM_SEED):
    # 별도 split_manifest 파일 대신 모델의 training_summary에 포함
    record = {
        "dataset": "data/dataset.csv",
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "seed": seed,
        "labels": LABELS,
        "input_fields": ["question"],
        "splitter": "GroupShuffleSplit(test=0.15, validation=0.15/0.85)",
        "splits": {},
    }
    for name, rows in splits.items():
        counts = Counter(row["label"] for row in rows)
        record["splits"][name] = {
            "count": len(rows),
            "label_counts": {label: counts[label] for label in LABELS},
            "source_counts": dict(Counter(row["source"] for row in rows)),
            "question_ids": [row["question_id"] for row in rows],
            "group_ids": sorted({row["group_id"] for row in rows}),
        }
    return record


def read_recorded_splits(record, dataset_path=DATASET_PATH):
    # 평가할 때 재분할하지 않고 저장된 질문 ID로 학습 당시의 분할 복원
    if (
        hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        != record["dataset_sha256"]
    ):
        raise ValueError(
            "학습 당시와 dataset.csv가 다릅니다. 같은 데이터로 평가하세요."
        )
    with dataset_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    validate_rows(rows)
    by_id = {row["question_id"]: row for row in rows}
    splits = {}
    for name in ["train", "validation", "test"]:
        ids = record["splits"][name]["question_ids"]
        if not ids or any(question_id not in by_id for question_id in ids):
            raise ValueError(f"{name}에 기록된 질문 ID가 CSV와 맞지 않습니다.")
        splits[name] = [by_id[question_id] for question_id in ids]
    all_ids = [row["question_id"] for data in splits.values() for row in data]
    if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(by_id):
        raise ValueError("분할 기록에 중복되거나 빠진 질문이 있습니다.")
    groups = [{row["group_id"] for row in data} for data in splits.values()]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("같은 group_id가 여러 분할에 들어 있습니다.")
    if make_split_record(splits, dataset_path, record["seed"]) != record:
        raise ValueError("분할 수량·라벨·설정이 저장된 기록과 맞지 않습니다.")
    return splits
