"""Validate the canonical single-label training dataset."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

COLUMNS = (
    "document_id",
    "title",
    "text",
    "label",
    "source_id",
    "source_group_id",
    "kind",
)
LABELS = ("HR", "IT", "FINANCE_PROCUREMENT", "WORKPLACE", "SECURITY_LEGAL", "COMPANY")
KINDS = ("excerpt", "translation", "synthetic")
DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset.csv"


class DatasetValidationError(ValueError):
    """Raised when a dataset violates the canonical data contract."""


@dataclass(frozen=True)
class DatasetSummary:
    rows: int
    labels: dict[str, int]


def validate_dataset(path: Path) -> DatasetSummary:
    """Validate *path* and return its row and label counts."""
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
    label_counts: Counter[str] = Counter()

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
        else:
            label_counts[label] += 1

        kind = row["kind"]
        if kind not in KINDS:
            errors.append(f"row {line_number}: invalid kind {kind!r}")

        title_text = (" ".join(row["title"].split()), " ".join(row["text"].split()))
        if all(title_text):
            if title_text in duplicates:
                errors.append(
                    f"row {line_number}: duplicate whitespace-normalized title and text"
                )
            duplicates.add(title_text)

    for label in LABELS:
        if label_counts[label] != 100:
            errors.append(
                f"label count for {label} must be 100, got {label_counts[label]}"
            )

    if errors:
        raise DatasetValidationError("\n".join(errors))

    return DatasetSummary(
        rows=len(rows),
        labels={label: label_counts[label] for label in LABELS},
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

    label_summary = ", ".join(f"{label}={summary.labels[label]}" for label in LABELS)
    print(f"Validated {summary.rows} rows; labels: {label_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
