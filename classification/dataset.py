"""요청 처리 분류용 질문의 공통 분할과 평가 데이터 복원."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from sklearn.model_selection import StratifiedGroupKFold

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


# 같은 그룹은 함께 두고, 라벨 비율이 최대한 비슷한 20개 묶음 준비
def make_stratified_folds(rows, labels, groups, seed=RANDOM_SEED):
    splitter = StratifiedGroupKFold(n_splits=20, shuffle=True, random_state=seed)

    folds = []
    for _, indices in splitter.split(rows, labels, groups=groups):
        # indices는 이번 묶음에 들어갈 질문의 위치 번호 목록
        fold = []
        for index in indices:
            fold.append(rows[index])
        folds.append(fold)

    return folds


# 20개 묶음을 학습·검증·테스트로 합치기 (약 70:15:15)
def combine_stratified_folds(folds):
    splits = {"train": [], "validation": [], "test": []}

    for fold in folds[:14]:  # 0~13번: 학습
        splits["train"].extend(fold)

    for fold in folds[14:17]:  # 14~16번: 검증
        splits["validation"].extend(fold)

    for fold in folds[17:]:  # 17~19번: 테스트
        splits["test"].extend(fold)

    return splits


def split_questions(question_rows, seed=RANDOM_SEED):
    rows = sorted(question_rows, key=lambda row: row["question_id"])
    validate_rows(rows)
    # 각 질문과 같은 순서로 정답 라벨 준비
    labels = [row["label"] for row in rows]

    # groups의 같은 위치는 rows의 같은 위치 질문이 속한 그룹
    # 비슷한 상황의 변형 질문이 train과 평가에 동시에 들어가는 것을 방지
    groups = [row["group_id"] for row in rows]

    # 라벨 비율을 고려한 20개 묶음을 만들고 14·3·3묶음으로 합치기
    folds = make_stratified_folds(rows, labels, groups, seed=seed)
    splits = combine_stratified_folds(folds)
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
        "splitter": "StratifiedGroupKFold(n_splits=20, shuffle=True, train=14, validation=3, test=3)",
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
    restored_record = make_split_record(splits, dataset_path, record["seed"])
    # ID로 복원하므로 예전 모델에는 당시 기록된 분할 방법을 유지
    restored_record["splitter"] = record["splitter"]
    if restored_record != record:
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
