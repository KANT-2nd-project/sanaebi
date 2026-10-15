"""1단계: 질문 CSV 읽기. 핵심 구현은 직접 작성한다."""

import csv
import json
from pathlib import Path

from sklearn.model_selection import StratifiedGroupKFold

from classification.persistence import file_sha
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


def prepare_data_from_manifest(path: Path, manifest_path: Path):
    """고정한 문항 순서와 그룹 경계를 복원한다. 자동 재분할하지 않는다."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("지원하지 않는 분할 manifest입니다.")
    if manifest.get("dataset_sha256") != file_sha(path):
        raise ValueError("분할 manifest의 데이터 해시가 일치하지 않습니다.")
    ids = manifest.get("question_ids")
    if not isinstance(ids, dict) or set(ids) != {"train", "validation", "test"}:
        raise ValueError("train/validation/test 분할이 필요합니다.")
    if any(
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value.strip() for value in values)
        for values in ids.values()
    ):
        raise ValueError("분할 문항 ID가 잘못되었습니다.")
    rows = prepare_rows(path)
    by_id = {row["question_id"]: row for row in rows}
    all_ids = [qid for values in ids.values() for qid in values]
    if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(by_id):
        raise ValueError("분할에 중복되거나 누락된 문항이 있습니다.")
    splits = {name: [by_id[qid] for qid in values] for name, values in ids.items()}
    groups = [{r["group_id"] for r in split} for split in splits.values()]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("분할 사이 그룹이 겹칩니다.")
    if any({r["label"] for r in split} != set(LABELS) for split in splits.values()):
        raise ValueError("분할에 빠진 라벨이 있습니다.")
    return splits


def texts_and_labels(
    rows: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    texts = []
    labels = []

    for row in rows:
        texts.append(row["question"])
        labels.append(row["label"])

    return texts, labels
