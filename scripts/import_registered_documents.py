"""Import legacy /regist-docs JSONL rows into the managed document database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "app" / "documents.jsonl"
DEFAULT_DATABASE = Path(
    os.getenv("SANAEBI_DOCUMENT_DB", str(PROJECT_ROOT / "var" / "documents.sqlite3"))
)
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "var" / "backups" / "document-imports"


class ImportConflictError(ValueError):
    """An already imported physical line no longer matches its recorded hash."""


@dataclass(frozen=True)
class LegacyDocument:
    line_number: int
    row_sha256: str
    title: str
    body: str


@dataclass(frozen=True)
class ImportReport:
    source_id: str
    source_sha256: str
    total_count: int
    imported_count: int
    skipped_count: int
    applied: bool
    source_backup_path: Path | None = None
    database_backup_path: Path | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _remove_line_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\n", b"\r")):
        return line[:-1]
    return line


def _parse_source(source_bytes: bytes) -> list[LegacyDocument]:
    documents: list[LegacyDocument] = []
    for line_number, physical_line in enumerate(
        source_bytes.splitlines(keepends=True), 1
    ):
        row_bytes = _remove_line_ending(physical_line)
        if not row_bytes.strip():
            continue

        try:
            row_text = row_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"{line_number}행: UTF-8 인코딩 오류") from error
        try:
            row = json.loads(row_text)
        except json.JSONDecodeError as error:
            raise ValueError(f"{line_number}행: JSON 형식 오류") from error
        if not isinstance(row, dict):
            raise TypeError(f"{line_number}행: JSON 객체여야 합니다.")

        body = row.get("doc")
        if not isinstance(body, str):
            raise TypeError(f"{line_number}행: doc 본문은 문자열이어야 합니다.")
        if not body.strip():
            raise ValueError(f"{line_number}행: 본문은 비어 있을 수 없습니다.")

        title = row.get("title")
        if title is None or (isinstance(title, str) and not title.strip()):
            title = f"기존 등록 문서 {line_number}"
        elif not isinstance(title, str):
            raise ValueError(f"{line_number}행: title은 문자열이어야 합니다.")

        documents.append(
            LegacyDocument(
                line_number=line_number,
                row_sha256=_sha256(row_bytes),
                title=title,
                body=body,
            )
        )
    return documents


def _provenance_rows(database_path: Path, source_id: str) -> dict[int, str]:
    if not database_path.exists():
        return {}

    uri = f"{database_path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        table = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type = 'table' AND name = 'legacy_document_imports'"""
        ).fetchone()
        if table is None:
            return {}
        rows = connection.execute(
            """SELECT line_number, row_sha256 FROM legacy_document_imports
               WHERE source_id = ?""",
            (source_id,),
        ).fetchall()
    return {int(line_number): row_sha256 for line_number, row_sha256 in rows}


def _classify_rows(
    source_id: str,
    documents: list[LegacyDocument],
    existing: dict[int, str],
) -> tuple[list[LegacyDocument], int]:
    new_documents: list[LegacyDocument] = []
    skipped_count = 0
    current_lines = {document.line_number for document in documents}
    missing_lines = sorted(set(existing) - current_lines)
    if missing_lines:
        line_number = missing_lines[0]
        raise ImportConflictError(
            f"{line_number}행: source_id {source_id!r}의 기존 행이 원본에서 사라졌습니다."
        )

    for document in documents:
        imported_hash = existing.get(document.line_number)
        if imported_hash is None:
            new_documents.append(document)
        elif imported_hash == document.row_sha256:
            skipped_count += 1
        else:
            raise ImportConflictError(
                f"{document.line_number}행: source_id {source_id!r}의 기존 행이 변경되었습니다."
            )
    return new_documents, skipped_count


def _backup_prefix(source_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", source_id).strip("-._")[:40]
    slug = slug or "source"
    return f"{slug}-{hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:8]}"


def _write_bytes_atomically(path: Path, data: bytes) -> None:
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary_path.open("xb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _backup_database(database_path: Path, backup_path: Path) -> None:
    temporary_path = backup_path.with_name(
        f".{backup_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with (
            closing(sqlite3.connect(str(database_path))) as source,
            closing(sqlite3.connect(str(temporary_path))) as destination,
        ):
            source.backup(destination)
        os.replace(temporary_path, backup_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _make_backups(
    *,
    source_path: Path,
    source_bytes: bytes,
    source_sha256: str,
    source_id: str,
    database_path: Path,
    backup_dir: Path,
) -> tuple[Path, Path | None]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    prefix = f"{_backup_prefix(source_id)}-{stamp}-{uuid.uuid4().hex[:8]}"
    source_backup_path = backup_dir / f"{prefix}.jsonl"
    database_backup_path = (
        backup_dir / f"{prefix}.sqlite3" if database_path.exists() else None
    )

    _write_bytes_atomically(source_backup_path, source_bytes)
    if database_backup_path is not None:
        _backup_database(database_path, database_backup_path)

    manifest = {
        "source_id": source_id,
        "source_path": str(source_path.resolve()),
        "source_backup": source_backup_path.name,
        "source_sha256": source_sha256,
        "database_backup": (
            database_backup_path.name if database_backup_path is not None else None
        ),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    manifest_path = backup_dir / f"{prefix}.manifest.json"
    _write_bytes_atomically(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return source_backup_path, database_backup_path


def _create_provenance_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS legacy_document_imports (
               source_id TEXT NOT NULL,
               line_number INTEGER NOT NULL CHECK (line_number >= 1),
               row_sha256 TEXT NOT NULL,
               document_id TEXT NOT NULL REFERENCES documents(id),
               imported_at TEXT NOT NULL,
               PRIMARY KEY (source_id, line_number)
           )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS legacy_document_import_runs (
               id TEXT PRIMARY KEY,
               source_id TEXT NOT NULL,
               source_path TEXT NOT NULL,
               source_sha256 TEXT NOT NULL,
               total_count INTEGER NOT NULL,
               imported_count INTEGER NOT NULL,
               skipped_count INTEGER NOT NULL,
               created_at TEXT NOT NULL
           )"""
    )


def import_registered_documents(
    *,
    source_path: str | Path = DEFAULT_SOURCE,
    database_path: str | Path = DEFAULT_DATABASE,
    source_id: str,
    apply: bool = False,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
) -> ImportReport:
    """Dry-run by default; with apply, import all new rows in one transaction."""
    source_path = Path(source_path)
    database_path = Path(database_path)
    backup_dir = Path(backup_dir)
    if not source_id.strip():
        raise ValueError("source_id는 비어 있을 수 없습니다.")

    source_bytes = source_path.read_bytes()
    source_sha256 = _sha256(source_bytes)
    documents = _parse_source(source_bytes)
    existing = _provenance_rows(database_path, source_id)
    new_documents, skipped_count = _classify_rows(source_id, documents, existing)
    if not documents:
        return ImportReport(source_id, source_sha256, 0, 0, 0, apply)
    if not apply:
        return ImportReport(
            source_id,
            source_sha256,
            len(documents),
            len(new_documents),
            skipped_count,
            False,
        )

    source_backup_path, database_backup_path = _make_backups(
        source_path=source_path,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        source_id=source_id,
        database_path=database_path,
        backup_dir=backup_dir,
    )
    if _sha256(source_path.read_bytes()) != source_sha256:
        raise RuntimeError("이관 중 원본 파일이 변경되어 적용을 중단했습니다.")

    from app.document_repository import DocumentRepository, DuplicateDocumentError

    repository = DocumentRepository(database_path)
    imported_at = datetime.now(UTC).isoformat(timespec="microseconds")
    imported_count = 0
    try:
        repository.initialize()
        with repository.transaction() as connection:
            _create_provenance_tables(connection)
            existing_in_transaction = {
                int(line_number): row_sha256
                for line_number, row_sha256 in connection.execute(
                    """SELECT line_number, row_sha256 FROM legacy_document_imports
                       WHERE source_id = ?""",
                    (source_id,),
                ).fetchall()
            }
            new_documents, skipped_count = _classify_rows(
                source_id, documents, existing_in_transaction
            )

            for document in new_documents:
                detail = repository.create_in_transaction(
                    connection,
                    {
                        "title": document.title,
                        "body": document.body,
                        "source_label": "legacy import",
                        "source_url": None,
                        "owner_department": None,
                        "effective_from": None,
                    },
                )
                connection.execute(
                    """INSERT INTO legacy_document_imports
                       (source_id, line_number, row_sha256, document_id, imported_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        source_id,
                        document.line_number,
                        document.row_sha256,
                        detail["id"],
                        imported_at,
                    ),
                )
                imported_count += 1

            connection.execute(
                """INSERT INTO legacy_document_import_runs
                   (id, source_id, source_path, source_sha256, total_count,
                    imported_count, skipped_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    source_id,
                    str(source_path.resolve()),
                    source_sha256,
                    len(documents),
                    imported_count,
                    skipped_count,
                    imported_at,
                ),
            )
    except DuplicateDocumentError as error:
        raise ImportConflictError(
            "이관 대상에 이미 등록된 제목과 본문 조합이 있습니다."
        ) from error

    return ImportReport(
        source_id,
        source_sha256,
        len(documents),
        imported_count,
        skipped_count,
        True,
        source_backup_path,
        database_backup_path,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="기본 dry-run을 대신해 SQLite에 초안과 provenance를 저장합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        report = import_registered_documents(
            source_path=args.source,
            database_path=args.db,
            source_id=args.source_id,
            apply=args.apply,
            backup_dir=args.backup_dir,
        )
    except (OSError, sqlite3.Error, TypeError, ValueError, RuntimeError) as error:
        parser.error(str(error))

    mode = "apply" if report.applied else "dry-run"
    print(
        f"{mode}: source_id={report.source_id} rows={report.total_count} "
        f"import={report.imported_count} skip={report.skipped_count} "
        f"source_sha256={report.source_sha256}"
    )
    if report.source_backup_path is not None:
        print(f"source_backup={report.source_backup_path}")
    if report.database_backup_path is not None:
        print(f"database_backup={report.database_backup_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
