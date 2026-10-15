"""Explicit reset of a disposable demo DB; never invoked by server startup."""

import fcntl
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.documents.repository import SCHEMA_VERSION, DocumentRepository
from app.documents.transfer import _apply_rows, read_source, sha

# Only these owned tables are cleared. Keep schema, unrelated tables and key TTLs.
TABLES = (
    "document_events",
    "document_imports",
    "document_revision_metadata",
    "documents",
    "document_revisions",
)
RESET_METHOD_PATH = "demo-reset:invalidated"


@contextmanager
def reset_lock(database):
    # Do not unlink: another process may already have opened this inode.
    with Path(str(database) + ".reset.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A demo reset is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _check_database(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise ValueError("Unsupported demo database schema; migrate separately")
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Database integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Database foreign key check failed")


def _backup(database, destination):
    with (
        closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(destination)) as target,
    ):
        source.backup(target)
        _check_database(target)


def _replace(connection, seed):
    versions = dict(connection.execute("SELECT id, record_version FROM documents"))
    # The reset is the sole privileged exception to immutable revision deletion.
    # Transactional DDL restores these triggers even if anything below fails.
    triggers = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
        "AND name IN ('document_revisions_are_immutable_delete', "
        "'document_metadata_immutable_delete')"
    ).fetchall()
    if len(triggers) != 2:
        raise ValueError("Required immutability triggers missing")
    connection.execute("PRAGMA defer_foreign_keys=ON")
    for name, _ in triggers:
        connection.execute(f'DROP TRIGGER "{name}"')
    existing_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for name in ("legacy_document_imports", "legacy_document_import_runs"):
        if name in existing_tables:
            connection.execute(f'DELETE FROM "{name}"')
    for name in TABLES:
        connection.execute(f'DELETE FROM "{name}"')
    for name in TABLES:
        rows = seed.execute(f'SELECT * FROM "{name}"').fetchall()
        if rows:
            placeholders = ",".join("?" for _ in rows[0])
            connection.executemany(
                f'INSERT INTO "{name}" VALUES ({placeholders})', rows
            )
    for document_id, previous_version in versions.items():
        connection.execute(
            "UPDATE documents SET record_version = MAX(record_version, ?) WHERE id = ?",
            (previous_version + 1, document_id),
        )
    connection.execute(
        "UPDATE idempotency_keys SET method_path=?, response_status=409, response_body='{}'",
        (RESET_METHOD_PATH,),
    )
    for _, sql in triggers:
        connection.execute(sql)
    _verify_restored(connection, seed)


def _verify_restored(connection, seed):
    # Exact copies of revisions, metadata and provenance imply the same published
    # snapshot, including full original body, source ordering and review state.
    for name in TABLES:
        columns = [row[1] for row in seed.execute(f'PRAGMA table_info("{name}")')]
        if name == "documents":
            columns.remove("record_version")
        projection = ",".join(f'"{name}"' for name in columns)
        query = f'SELECT {projection} FROM "{name}" ORDER BY 1'
        if [tuple(row) for row in connection.execute(query)] != [
            tuple(row) for row in seed.execute(query)
        ]:
            raise ValueError("Restored document snapshot differs from baseline")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Restored database foreign key check failed")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("Restored database integrity check failed")


def reset_demo_documents(source, database, *, apply=False):
    source, database = Path(source).resolve(), Path(database).resolve()
    raw, rows = read_source(source)
    report = {
        "applied": False,
        "status": "validated",
        "started_at": datetime.now(UTC).isoformat(),
        "source": str(source),
        "source_sha256": sha(raw),
        "database": str(database),
        "restored_count": len(rows),
        "backup_dir": None,
    }
    # Build the complete baseline in memory before taking any runtime lock.
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as seed:
        seed.row_factory = sqlite3.Row
        seed.execute("PRAGMA foreign_keys=ON")
        seed.execute("BEGIN")
        _apply_rows(DocumentRepository(database), seed, rows, sha(raw), True)
        seed.commit()
        if not database.is_file():
            raise FileNotFoundError(
                "Demo database must already exist; initialize separately"
            )
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        ) as current:
            _check_database(current)
            with closing(sqlite3.connect(":memory:", isolation_level=None)) as preview:
                current.backup(preview)
                preview.execute("PRAGMA foreign_keys=ON")
                preview.execute("BEGIN IMMEDIATE")
                _replace(preview, seed)
                preview.rollback()
        if not apply:
            return report
        with reset_lock(database):
            backup_dir = (
                database.parent / "backups" / ("demo-reset-" + uuid.uuid4().hex)
            )
            backup_dir.mkdir(parents=True, mode=0o700)
            report["backup_dir"] = str(backup_dir)
            manifest = backup_dir / "manifest.json"
            try:
                with closing(
                    sqlite3.connect(database, isolation_level=None, timeout=5)
                ) as live:
                    live.execute("PRAGMA foreign_keys=ON")
                    live.execute("BEGIN IMMEDIATE")
                    try:
                        _check_database(live)
                        _backup(database, backup_dir / "database.sqlite3")
                        (backup_dir / "source.jsonl").write_bytes(raw)
                        report["status"] = "prepared"
                        manifest.write_text(
                            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                        )
                        _replace(live, seed)
                        live.commit()
                        report.update(applied=True, status="success")
                    except BaseException:
                        live.rollback()
                        raise
            except BaseException as exc:
                report.update(status="failed", error_type=type(exc).__name__)
                raise
            finally:
                report["finished_at"] = datetime.now(UTC).isoformat()
                # A prepared manifest after a process crash is intentionally not a
                # success claim. Inspect the live DB before retrying/recovering.
                manifest.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                )
    return report
