"""Explicit, repeatable company-knowledge import/export. Never used at startup."""

import hashlib
import json
import sqlite3
import subprocess
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.documents.repository import SCHEMA_VERSION, DocumentRepository
from app.documents.schemas import CreateDocumentRequest

NAMESPACE = "company-knowledge-v2"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_source(source):
    raw = Path(source).read_bytes()
    rows = []
    ids = set()
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise TypeError(f"{number}: expected JSON object")
        for key in (
            "document_id",
            "title",
            "document",
            "category",
            "version",
            "review_status",
        ):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"{number}: invalid {key}")
        for key in ("source_ids", "policy_decision_ids"):
            if not isinstance(row.get(key), list) or any(
                not isinstance(x, str) or not x.strip() for x in row[key]
            ):
                raise ValueError(f"{number}: invalid {key}")
        if row["document_id"] in ids:
            raise ValueError(f"Duplicate source ID: {row['document_id']}")
        ids.add(row["document_id"])
        CreateDocumentRequest(title=row["title"], body=row["document"])
        rows.append((number, sha(line), line.decode("utf-8"), row))
    if not rows:
        raise ValueError("No company documents")
    return raw, rows


def _apply_rows(repo, con, rows, source_hash, publish):
    repo.initialize(con)
    imported, skipped, mapping = 0, 0, []
    for number, row_hash, original_json, row in rows:
        known = con.execute(
            "SELECT * FROM document_imports WHERE source_namespace=? AND source_document_id=?",
            (NAMESPACE, row["document_id"]),
        ).fetchone()
        if known:
            if known["row_sha256"] != row_hash:
                raise ValueError(f"Changed source row: {row['document_id']}")
            skipped += 1
            mapping.append(
                {
                    "knowledge_id": row["document_id"],
                    "document_id": known["document_id"],
                    "action": "skip",
                }
            )
            continue
        document_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"sanaebi:{NAMESPACE}:{row['document_id']}")
        )
        detail = repo.create_in_transaction(
            con,
            {
                "title": row["title"],
                "body": row["document"],
                "source_label": "이음웍스 이관 원본",
            },
            document_id=document_id,
            metadata=row,
            actor="migration:company-knowledge",
        )
        revision_id = detail["draft"]["id"]
        con.execute(
            "INSERT INTO document_imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                NAMESPACE,
                row["document_id"],
                document_id,
                revision_id,
                number,
                source_hash,
                row_hash,
                original_json,
                datetime.now(UTC).isoformat(),
            ),
        )
        if publish:
            repo.publish_in_transaction(
                con,
                document_id,
                detail["record_version"],
                revision_id,
                actor="migration:company-knowledge",
            )
        mapping.append(
            {
                "knowledge_id": row["document_id"],
                "document_id": document_id,
                "action": "import",
            }
        )
        imported += 1
    return {
        "total_count": len(rows),
        "imported_count": imported,
        "skipped_count": skipped,
        "published_count": imported if publish else 0,
        "mapping": mapping,
    }


def import_knowledge(source, database, *, apply=False, publish=False):
    source, database = Path(source).resolve(), Path(database).resolve()
    raw, rows = read_source(source)
    repo = DocumentRepository(database)
    # Rehearse against a consistent in-memory copy, including constraints and migrations.
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as preview:
        preview.row_factory = sqlite3.Row
        if database.exists():
            with closing(
                sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            ) as existing:
                existing.backup(preview)
        previous_version = preview.execute("PRAGMA user_version").fetchone()[0]
        preview.execute("PRAGMA foreign_keys=ON")
        preview.execute("BEGIN IMMEDIATE")
        report = _apply_rows(repo, preview, rows, sha(raw), publish)
        preview.rollback()
    report.update(
        applied=False,
        database=str(database),
        source=str(source),
        source_sha256=sha(raw),
        schema_before=previous_version,
        schema_after=SCHEMA_VERSION,
    )
    try:
        report["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        report["git_commit"] = None
    if not apply:
        return report
    # Unique backup directory; never overwrite an earlier recovery point.
    backup_dir = database.parent / "backups" / ("knowledge-" + uuid.uuid4().hex)
    backup_dir.mkdir(parents=True)
    (backup_dir / "source.jsonl").write_bytes(raw)
    if database.exists():
        with (
            closing(
                sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            ) as original,
            closing(sqlite3.connect(backup_dir / "database.sqlite3")) as backup,
        ):
            original.backup(backup)
    with repo.transaction() as con:
        # Recheck all rows under the write lock; the preview is not a concurrency lock.
        result = _apply_rows(repo, con, rows, sha(raw), publish)
    report.update(result, applied=True, backup_dir=str(backup_dir))
    (backup_dir / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


def export_knowledge(database, output):
    from app.documents.context import DocumentContextProvider

    output = Path(output)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("Export target or manifest already exists")
    snapshot = DocumentContextProvider(database_path=Path(database)).snapshot()
    rows = []
    for doc in snapshot.documents:
        rows.append(
            {
                "document_id": doc.knowledge_id,
                "title": doc.title,
                "document": doc.body,
                **dict(doc.metadata),
                "version": doc.metadata.get("source_version"),
                "revision_id": doc.revision_id,
                "revision_number": doc.revision,
                "content_hash": doc.content_hash,
            }
        )
    data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "documents": len(rows),
        "snapshot_fingerprint": snapshot.fingerprint,
        "sha256": sha(data.encode()),
        "database": str(Path(database).resolve()),
        "revisions": [
            {
                "document_id": d.knowledge_id,
                "revision_id": d.revision_id,
                "content_hash": d.content_hash,
            }
            for d in snapshot.documents
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        file.write(data)
    try:
        with manifest_path.open("x", encoding="utf-8") as file:
            file.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    except BaseException:
        output.unlink()
        raise
    return manifest
