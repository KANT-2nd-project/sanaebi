"""문서 분류 모델들이 함께 사용할 학습·검증·테스트 분할."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from sklearn.model_selection import StratifiedGroupKFold

RANDOM_SEED = 42
LABELS = ["HR", "IT", "FINANCE_PROCUREMENT", "WORKPLACE", "SECURITY_LEGAL", "COMPANY"]


def document_input(row):
    # 학습과 보고서 평가에서 제목·본문을 항상 같은 방식으로 연결
    return f"{row['title'].strip()}\n{row['text'].strip()}"


def split_input_hashes(splits):
    # 문서 ID·실제 모델 입력·정답이 같으면 모든 모델에서 같은 식별값 생성
    return {
        name: hashlib.sha256(
            json.dumps(
                [
                    (row["document_id"], document_input(row), row["label"])
                    for row in rows
                ],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        for name, rows in splits.items()
    }


def split_documents(document_rows, seed=RANDOM_SEED):
    # 입력 CSV의 순서와 관계없이 항상 문서 ID 순으로 준비
    rows = sorted(document_rows, key=lambda row: row["document_id"])
    ids = [row["document_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("중복된 document_id가 있습니다.")
    if any(not row["source_group_id"].strip() for row in rows):
        raise ValueError("source_group_id는 비어 있을 수 없습니다.")
    if any(row["label"] not in LABELS for row in rows):
        raise ValueError("문서 라벨이 현재 6개 카테고리와 맞지 않습니다.")

    # 합성 문서(kind가 synthetic인 문서)가 속한 그룹 ID 모으기
    synthetic_groups = {
        row["source_group_id"] for row in rows if row["kind"] == "synthetic"
    }

    # 반드시 학습에 넣을 문서: 합성 문서가 속한 그룹의 모든 문서
    # 같은 그룹에 원문이 있어도 함께 학습에 넣어 그룹이 나뉘지 않게 함
    fixed_train = [row for row in rows if row["source_group_id"] in synthetic_groups]

    # 나머지 문서: 합성 문서가 속한 그룹을 제외한 문서
    # 이 목록을 아래에서 학습·검증·테스트로 나눔
    original_rows = [
        row for row in rows if row["source_group_id"] not in synthetic_groups
    ]
    groups = [row["source_group_id"] for row in original_rows]
    if len(set(groups)) < 4:
        raise ValueError("원문 자료는 최소 4개의 source_group_id가 필요합니다.")

    # 원문 자료를 그룹 단위로 4등분하면서 라벨 비율도 최대한 유지
    splitter = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=seed)

    folds = [
        [original_rows[index] for index in indices]
        for _, indices in splitter.split(
            original_rows, [row["label"] for row in original_rows], groups
        )
    ]

    # 원문 2개 묶음은 학습, 나머지는 검증과 테스트에 하나씩 사용
    splits = {
        "train": fixed_train + folds[2] + folds[3],
        "validation": folds[0],
        "test": folds[1],
    }
    for name, split_rows in splits.items():
        if not split_rows:
            raise ValueError(f"{name} 분할이 비어 있습니다.")
        split_rows.sort(key=lambda row: row["document_id"])
    return splits


def make_split_record(splits, dataset_path, seed=RANDOM_SEED):
    # 원본 CSV 식별자와 설정을 남겨 어떤 데이터로 분할했는지 확인
    record = {
        "dataset": "data/archive/document-topics-v0.2/dataset.csv",
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "seed": seed,
        "labels": LABELS,
        "input_fields": ["title", "text"],
        "input_separator": "\n",
        "splitter": "StratifiedGroupKFold(n_splits=4, shuffle=True)",
        "splits": {},
    }
    for name, rows in splits.items():
        label_counts = Counter(row["label"] for row in rows)
        record["splits"][name] = {
            "count": len(rows),
            "label_counts": {label: label_counts[label] for label in LABELS},
            "kind_counts": dict(Counter(row["kind"] for row in rows)),
            "document_ids": [row["document_id"] for row in rows],
            "source_group_ids": sorted({row["source_group_id"] for row in rows}),
        }
    return record


def read_recorded_splits(record, dataset_path=None):
    # 새로 랜덤 분할하지 않고, 모델에 기록된 문서 ID로 원래 분할 복원
    if dataset_path is None:
        dataset_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "archive"
            / "document-topics-v0.2"
            / "dataset.csv"
        )
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if digest != record["dataset_sha256"]:
        raise ValueError(
            "학습 당시와 dataset.csv가 다릅니다. 같은 데이터로 평가하세요."
        )
    with dataset_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    by_id = {row["document_id"]: row for row in rows}
    splits = {}
    for name in ["train", "validation", "test"]:
        ids = record["splits"][name]["document_ids"]
        if not ids or any(document_id not in by_id for document_id in ids):
            raise ValueError(f"{name}에 기록된 문서 ID가 CSV와 맞지 않습니다.")
        splits[name] = [by_id[document_id] for document_id in ids]
    ids = [row["document_id"] for split in splits.values() for row in split]
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ValueError("분할 기록에 중복되거나 빠진 문서가 있습니다.")
    expected_record = make_split_record(splits, dataset_path, record["seed"])
    if record.get("dataset") == "data/dataset.csv":
        # 이전 모델 기록의 데이터 식별자는 보존하면서 나머지 필드는 그대로 검증
        expected_record["dataset"] = "data/dataset.csv"
    if expected_record != record:
        raise ValueError("분할 수량·라벨·설정이 저장된 기록과 맞지 않습니다.")
    groups = [{row["source_group_id"] for row in split} for split in splits.values()]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("같은 source_group_id가 여러 분할에 들어 있습니다.")
    if any(
        row["kind"] == "synthetic"
        for name in ["validation", "test"]
        for row in splits[name]
    ):
        raise ValueError("합성 문서는 검증·테스트에 포함할 수 없습니다.")
    return splits
