"""Validate the canonical single-label training dataset."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

COLUMNS = (
    "document_id",
    "title",
    "text",
    "label",
    "split",
    "source_id",
    "source_group_id",
    "kind",
)
LABELS = ("HR", "IT", "FINANCE_PROCUREMENT", "WORKPLACE", "SECURITY_LEGAL", "COMPANY")
SPLITS = ("train", "validation", "test")
KINDS = ("excerpt", "translation", "synthetic")
EXPECTED_SPLIT_COUNTS = {"train": 420, "validation": 90, "test": 90}
EXPECTED_PER_LABEL_SPLIT = {"train": 70, "validation": 15, "test": 15}
DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset.csv"


class DatasetValidationError(ValueError):
    """Raised when a dataset violates the canonical data contract."""


@dataclass(frozen=True)
class DatasetSummary:
    rows: int
    splits: dict[str, int]
    labels: dict[str, int]


def validate_dataset(path: Path) -> DatasetSummary:
    """Validate *path* and return its row, split, and label counts."""
    errors: list[str] = []
    rows: list[dict[str, str]] = []

    try:
        if not path.read_bytes().startswith(b"\xef\xbb\xbf"):
            raise DatasetValidationError("CSV must be encoded as UTF-8 with BOM")
        with path.open(encoding="utf-8-sig", newline="") as dataset_file:
            reader = csv.reader(dataset_file, strict=True)
            header = next(reader, None)
            if header != list(COLUMNS):
                raise DatasetValidationError(
                    f"header must be exactly: {','.join(COLUMNS)}"
                )
            for line_number, values in enumerate(reader, start=2):
                if len(values) != len(COLUMNS):
                    errors.append(
                        f"row {line_number}: expected {len(COLUMNS)} columns, got {len(values)}"
                    )
                    continue
                rows.append(dict(zip(COLUMNS, values, strict=True)))
    except DatasetValidationError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DatasetValidationError(f"cannot read CSV: {exc}") from exc

    if len(rows) != 600:
        errors.append(f"expected 600 rows, got {len(rows)}")

    ids: set[str] = set()
    duplicates: set[tuple[str, str]] = set()
    group_splits: dict[str, set[str]] = defaultdict(set)
    split_counts: Counter[str] = Counter()
    label_split_counts: Counter[tuple[str, str]] = Counter()

    for line_number, row in enumerate(rows, start=2):
        for column, value in row.items():
            if not value.strip():
                errors.append(f"row {line_number}: {column} must not be blank")

        document_id = row["document_id"]
        if document_id in ids:
            errors.append(f"row {line_number}: duplicate document_id {document_id!r}")
        ids.add(document_id)

        label = row["label"]
        if label not in LABELS:
            errors.append(f"row {line_number}: invalid scalar label {label!r}")

        split = row["split"]
        if split not in SPLITS:
            errors.append(f"row {line_number}: invalid split {split!r}")
        else:
            split_counts[split] += 1
            if label in LABELS:
                label_split_counts[(label, split)] += 1

        kind = row["kind"]
        if kind not in KINDS:
            errors.append(f"row {line_number}: invalid kind {kind!r}")
        elif kind == "synthetic" and split != "train":
            errors.append(f"row {line_number}: synthetic rows must be in train")

        group_id = row["source_group_id"]
        if group_id.strip() and split in SPLITS:
            group_splits[group_id].add(split)

        title_text = (" ".join(row["title"].split()), " ".join(row["text"].split()))
        if all(title_text):
            if title_text in duplicates:
                errors.append(
                    f"row {line_number}: duplicate whitespace-normalized title and text"
                )
            duplicates.add(title_text)

    for group_id, splits in group_splits.items():
        if len(splits) > 1:
            errors.append(
                f"source_group_id {group_id!r} appears in multiple splits: {', '.join(sorted(splits))}"
            )

    if dict(split_counts) != EXPECTED_SPLIT_COUNTS:
        actual = ", ".join(f"{split}={split_counts[split]}" for split in SPLITS)
        errors.append(
            f"split counts must be train=420, validation=90, test=90; got {actual}"
        )

    for label in LABELS:
        actual = {split: label_split_counts[(label, split)] for split in SPLITS}
        if actual != EXPECTED_PER_LABEL_SPLIT:
            counts = ", ".join(f"{split}={actual[split]}" for split in SPLITS)
            errors.append(
                f"label/split counts for {label} must be 70/15/15; got {counts}"
            )

    if errors:
        raise DatasetValidationError("\n".join(errors))

    return DatasetSummary(
        rows=len(rows),
        splits={split: split_counts[split] for split in SPLITS},
        labels={
            label: sum(label_split_counts[(label, split)] for split in SPLITS)
            for label in LABELS
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args(argv)

    try:
        summary = validate_dataset(args.path)
    except DatasetValidationError as exc:
        print(f"Dataset validation failed:\n{exc}", file=sys.stderr)
        return 1

    split_summary = ", ".join(f"{split}={summary.splits[split]}" for split in SPLITS)
    label_summary = ", ".join(f"{label}={summary.labels[label]}" for label in LABELS)
    print(
        f"Validated {summary.rows} rows; splits: {split_summary}; labels: {label_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
