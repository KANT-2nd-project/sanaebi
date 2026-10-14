"""1단계: 질문 CSV 읽기. 핵심 구현은 직접 작성한다."""

import csv
from pathlib import Path

from sklearn.model_selection import StratifiedGroupKFold

from contracts.classification import LABELS

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "dataset.csv"


def load_rows(path: Path = DATASET_PATH) -> list[dict[str, str]]:
    with open(file=path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    return rows


def validate_rows(rows: list[dict[str, str]]) -> None:
    ids = [row["question_id"] for row in rows]

    if len(ids) != len(set(ids)):
        raise ValueError("중복된 question_id가 있습니다.")

    for row in rows:
        if not row["question"] or not row["question"].strip():
            raise ValueError("질문은 비어 있을 수 없습니다.")

        if not row["group_id"] or not row["group_id"].strip():
            raise ValueError("group_id는 비어 있을 수 없습니다.")

        if row["label"] not in LABELS:
            raise ValueError("label이 지원되지 않습니다.")


def make_folds(
    rows: list[dict[str, str]],
    seed: int = 20261013,
) -> list[list[dict[str, str]]]:
    labels = [row["label"] for row in rows]
    groups = [row["group_id"] for row in rows]

    splitter = StratifiedGroupKFold(
        n_splits=20,
        shuffle=True,
        random_state=seed,
    )

    folds = []

    for _, fold_indices in splitter.split(rows, labels, groups=groups):  # type: ignore
        fold = []
        for i in fold_indices:
            fold.append(rows[i])

        folds.append(fold)

    return folds


def prepare_rows(path: Path = DATASET_PATH) -> list[dict[str, str]]:
    rows = load_rows(path)
    validate_rows(rows)
    return sorted(rows, key=lambda row: row["question_id"])


def combine_folds(folds: list[list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
    splits = {"train": [], "validation": [], "test": []}

    for fold in folds[:14]:
        splits["train"].extend(fold)

    for fold in folds[14:17]:
        splits["validation"].extend(fold)

    for fold in folds[17:]:
        splits["test"].extend(fold)

    return splits


def prepare_data(
    path: Path = DATASET_PATH, seed: int = 20261013
) -> dict[str, list[dict[str, str]]]:
    rows = prepare_rows(path)
    folds = make_folds(rows, seed)
    return combine_folds(folds)


def texts_and_labels(
    rows: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    texts = []
    labels = []

    for row in rows:
        texts.append(row["question"])
        labels.append(row["label"])

    return texts, labels
