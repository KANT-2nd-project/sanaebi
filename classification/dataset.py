"""요청 처리 분류용 질문의 공통 분할과 평가 데이터 복원."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from sklearn.model_selection import GroupShuffleSplit

from contracts.classification import LABELS as CLASSIFICATION_LABELS

from .types import DEFAULT_SEED, DatasetSplits

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "dataset.csv"
# 입력 순서·데이터·알고리즘도 같을 때 고정 시드로 같은 분할을 재현
RANDOM_SEED = DEFAULT_SEED
# 기존 학습·보고서의 리스트 계약을 유지하고 값·순서는 공통 계약에서 가져온다.
LABELS = list(CLASSIFICATION_LABELS)


def question_input(row):
    # ID·그룹·출처·검수 상태·정답은 모델 입력에 포함하지 않음
    return row["question"]


# 학습 전에 중복 ID·빈 질문·빈 그룹·잘못된 라벨을 확인
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
    # groups의 같은 위치는 rows의 같은 위치 질문이 속한 그룹
    # 비슷한 상황의 변형 질문이 train과 평가에 동시에 들어가는 것을 방지
    groups = [row["group_id"] for row in rows]

    # 전체 그룹의 약 15%를 테스트로 분리
    test_splitter = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=seed)
    # split은 행 자체가 아닌 행의 위치 번호(indices)를 반환
    # n_splits=1이므로 next로 첫 분할을 꺼내고 위치 번호로 원래 행을 선택
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
    # train·validation의 위치 번호는 remaining_rows 기준, test는 전체 rows 기준
    # 그룹 수를 기준으로 나누므로 실제 행 수는 정확히 70:15:15가 아닐 수 있음
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


# 각 분할의 ID·입력·정답을 SHA-256 식별값으로 바꿔 모델 간 평가 데이터 비교
# 가중치나 분류 점수가 아니라 사용한 데이터가 같은지 확인하는 용도
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
        # Counter는 각 라벨이 몇 번 등장했는지 세어 주는 도구
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
    # ID를 키로 삼아 저장 기록의 질문을 바로 찾아오기 위한 사전
    by_id = {row["question_id"]: row for row in rows}
    splits = {}
    for name in ["train", "validation", "test"]:
        ids = record["splits"][name]["question_ids"]
        if not ids or any(question_id not in by_id for question_id in ids):
            raise ValueError(f"{name}에 기록된 질문 ID가 CSV와 맞지 않습니다.")
        splits[name] = [by_id[question_id] for question_id in ids]
    # 복원한 세 분할을 합쳐 중복·누락이 없는지 확인
    all_ids = [row["question_id"] for data in splits.values() for row in data]
    if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(by_id):
        raise ValueError("분할 기록에 중복되거나 빠진 질문이 있습니다.")
    groups = [{row["group_id"] for row in data} for data in splits.values()]
    # 집합의 &는 공통 원소: train/검증, train/test, 검증/test의 그룹 겹침 확인
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("같은 group_id가 여러 분할에 들어 있습니다.")
    if make_split_record(splits, dataset_path, record["seed"]) != record:
        raise ValueError("분할 수량·라벨·설정이 저장된 기록과 맞지 않습니다.")
    return splits


def prepare_data(dataset_path=DATASET_PATH, seed=RANDOM_SEED):
    with dataset_path.open(encoding="utf-8-sig", newline="") as file:
        rows = sorted(csv.DictReader(file), key=lambda row: row["question_id"])
    splits = split_questions(rows, seed=seed)
    return DatasetSplits(
        splits,
        make_split_record(splits, dataset_path, seed=seed),
        split_input_hashes(splits),
    )


def texts_and_labels(rows):
    return [question_input(row) for row in rows], [row["label"] for row in rows]


def texts_and_ids(rows):
    texts, labels = texts_and_labels(rows)
    return texts, [LABELS.index(label) for label in labels]


def restore_data(record, dataset_path=DATASET_PATH):
    rows = read_recorded_splits(record, dataset_path)
    return DatasetSplits(rows, record, split_input_hashes(rows))
