"""Validate the canonical request-routing dataset and its review audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# 파일 경로로 실행하는 기존 검증 명령을 유지한다.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts.classification import LABELS

COLUMNS = (
    "question_id",
    "question",
    "label",
    "group_id",
    "source",
    "review_status",
)
REVIEW_COLUMNS = (
    "question_id",
    "question_sha256",
    "writer",
    "reviewer_1",
    "reviewer_1_label",
    "reviewer_1_reason",
    "reviewer_1_flags",
    "reviewer_2",
    "reviewer_2_label",
    "reviewer_2_reason",
    "reviewer_2_flags",
    "decision",
    "decision_reason",
    "final_label",
    "scenario",
    "subtype",
    "personal_context",
    "mixed",
    "revision_history",
)
EXPECTED_ROWS = 900
EXPECTED_ROWS_PER_LABEL = 300
MIN_GROUPS = 180
MAX_GROUP_SIZE = 5
DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset.csv"


class DatasetValidationError(ValueError):
    """Raised when a dataset or its audit violates the data contract."""


@dataclass(frozen=True)
class DatasetSummary:
    rows: int
    labels: dict[str, int]
    groups: int
    review_rows: int


def _read_csv(
    path: Path,
    columns: tuple[str, ...],
    *,
    require_bom: bool = False,
) -> list[dict[str, str]]:
    try:
        if require_bom and not path.read_bytes().startswith(b"\xef\xbb\xbf"):
            raise DatasetValidationError("dataset CSV must be UTF-8 with BOM")

        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.reader(csv_file, strict=True)
            header = next(reader, None)
            if header != list(columns):
                raise DatasetValidationError(
                    f"{path.name} header must be exactly: {','.join(columns)}"
                )

            rows = []
            for line_number, values in enumerate(reader, start=2):
                if len(values) != len(columns):
                    raise DatasetValidationError(
                        f"{path.name} row {line_number}: expected {len(columns)} "
                        f"columns, got {len(values)}"
                    )
                rows.append(dict(zip(columns, values, strict=True)))
            return rows
    except DatasetValidationError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DatasetValidationError(f"cannot read {path.name}: {exc}") from exc


def _normalized_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).casefold()
    return re.sub(r"[\W_]+", "", normalized)


def _validate_dataset_rows(rows: list[dict[str, str]]) -> DatasetSummary:
    errors: list[str] = []
    ids: set[str] = set()
    questions: set[str] = set()
    label_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()

    if len(rows) != EXPECTED_ROWS:
        errors.append(f"expected {EXPECTED_ROWS} rows, got {len(rows)}")

    for line_number, row in enumerate(rows, start=2):
        for column, value in row.items():
            if not value.strip():
                errors.append(f"row {line_number}: {column} must not be blank")

        question_id = row["question_id"].strip()
        if question_id in ids:
            errors.append(f"row {line_number}: duplicate question_id {question_id!r}")
        ids.add(question_id)

        label = row["label"]
        if label not in LABELS:
            errors.append(f"row {line_number}: invalid label {label!r}")
        else:
            label_counts[label] += 1

        if row["review_status"] != "ai_reviewed":
            errors.append(
                f"row {line_number}: review_status must be 'ai_reviewed', "
                f"got {row['review_status']!r}"
            )

        normalized_question = _normalized_question(row["question"])
        if normalized_question in questions:
            errors.append(f"row {line_number}: duplicate normalized question")
        questions.add(normalized_question)

        group_counts[row["group_id"].strip()] += 1

    for label in LABELS:
        if label_counts[label] != EXPECTED_ROWS_PER_LABEL:
            errors.append(
                f"label count for {label} must be {EXPECTED_ROWS_PER_LABEL}, "
                f"got {label_counts[label]}"
            )

    if len(group_counts) < MIN_GROUPS:
        errors.append(f"expected at least {MIN_GROUPS} groups, got {len(group_counts)}")
    for group_id, count in group_counts.items():
        if count > MAX_GROUP_SIZE:
            errors.append(
                f"group {group_id!r} has {count} rows; maximum is {MAX_GROUP_SIZE}"
            )

    if errors:
        raise DatasetValidationError("\n".join(errors))

    return DatasetSummary(
        rows=len(rows),
        labels={label: label_counts[label] for label in LABELS},
        groups=len(group_counts),
        review_rows=0,
    )


def _validate_review_rows(
    dataset_rows: list[dict[str, str]],
    review_rows: list[dict[str, str]],
) -> None:
    errors: list[str] = []
    dataset_by_id = {row["question_id"].strip(): row for row in dataset_rows}
    review_ids: set[str] = set()

    if len(review_rows) != EXPECTED_ROWS:
        errors.append(
            f"review audit expected {EXPECTED_ROWS} rows, got {len(review_rows)}"
        )

    for line_number, review in enumerate(review_rows, start=2):
        question_id = review["question_id"].strip()
        if question_id in review_ids:
            errors.append(
                f"review row {line_number}: duplicate question_id {question_id!r}"
            )
        review_ids.add(question_id)

        dataset_row = dataset_by_id.get(question_id)
        if dataset_row is None:
            errors.append(
                f"review row {line_number}: unknown question_id {question_id!r}"
            )
            continue

        expected_hash = hashlib.sha256(
            dataset_row["question"].encode("utf-8")
        ).hexdigest()
        if review["question_sha256"] != expected_hash:
            errors.append(f"review row {line_number}: question_sha256 mismatch")

        for column in (
            "reviewer_1",
            "reviewer_2",
            "reviewer_1_reason",
            "reviewer_2_reason",
        ):
            if not review[column].strip():
                errors.append(f"review row {line_number}: {column} must not be blank")

        for column in ("reviewer_1_label", "reviewer_2_label", "final_label"):
            if review[column] not in LABELS:
                errors.append(
                    f"review row {line_number}: invalid {column} {review[column]!r}"
                )

        if review["final_label"] != dataset_row["label"]:
            errors.append(
                f"review row {line_number}: final_label does not match dataset label"
            )

    missing_ids = set(dataset_by_id) - review_ids
    if missing_ids:
        errors.append(
            f"review audit is missing {len(missing_ids)} dataset question_id(s)"
        )

    if errors:
        raise DatasetValidationError("\n".join(errors))


def validate_dataset(
    path: Path,
    review_path: Path | None = None,
) -> DatasetSummary:
    """Validate *path* and its sibling or explicitly supplied review audit."""
    rows = _read_csv(path, COLUMNS, require_bom=True)
    summary = _validate_dataset_rows(rows)

    audit_path = (
        review_path if review_path is not None else path.with_name("dataset-review.csv")
    )
    review_rows = _read_csv(audit_path, REVIEW_COLUMNS)
    _validate_review_rows(rows, review_rows)

    return DatasetSummary(
        rows=summary.rows,
        labels=summary.labels,
        groups=summary.groups,
        review_rows=len(review_rows),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--review", type=Path, help="path to the matching review audit CSV"
    )
    args = parser.parse_args(argv)

    try:
        summary = validate_dataset(args.path, args.review)
    except DatasetValidationError as exc:
        print(f"Dataset validation failed:\n{exc}", file=sys.stderr)
        return 1

    label_summary = ", ".join(f"{label}={summary.labels[label]}" for label in LABELS)
    print(
        f"Validated {summary.rows} rows; labels: {label_summary}; "
        f"groups={summary.groups}; review rows={summary.review_rows}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
