"""Storage primitives for atomic whole-document maintenance; no HTTP policy."""

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime

from app.documents import reset
from app.documents.repository import DocumentRepository
from app.documents.transfer import _apply_rows, read_source, sha


@contextmanager
def prepared_baseline(repository, action, source):
    raw, rows = read_source(source) if action == "restore" else (b"", [])
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as seed:
        seed.row_factory = sqlite3.Row
        seed.execute("PRAGMA foreign_keys=ON")
        seed.execute("BEGIN")
        repository.initialize(seed)
        if rows:
            _apply_rows(repository, seed, rows, sha(raw), True)
        seed.commit()
        yield seed, raw, len(rows)


def state_token(connection, action, raw):
    state = [
        tuple(row)
        for row in connection.execute(
            "SELECT id, record_version, draft_revision_id, published_revision_id FROM documents ORDER BY id"
        )
    ]
    floor = connection.execute(
        "SELECT version_floor FROM document_maintenance_state WHERE id=1"
    ).fetchone()[0]
    return hashlib.sha256(
        json.dumps([action, floor, state, sha(raw)]).encode()
    ).hexdigest()


@contextmanager
def replacement_backup(repository: DocumentRepository, action, raw):
    manifest = None
    report = {"status": "prepared", "started_at": datetime.now(UTC).isoformat()}
    if action == "restore":
        backup = repository.path.parent / "backups" / ("demo-reset-" + uuid.uuid4().hex)
        backup.mkdir(parents=True, mode=0o700)
        reset._backup(repository.path.resolve(), backup / "database.sqlite3")
        (backup / "source.jsonl").write_bytes(raw)
        report["source_sha256"] = sha(raw)
        manifest = backup / "manifest.json"
        manifest.write_text(json.dumps(report) + "\n")
    try:
        yield
    except BaseException:
        report["status"] = "failed"
        raise
    else:
        report["status"] = "success"
    finally:
        if manifest:
            report["finished_at"] = datetime.now(UTC).isoformat()
            manifest.write_text(json.dumps(report) + "\n")
