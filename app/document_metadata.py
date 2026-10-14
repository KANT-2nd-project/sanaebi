"""Versioned document provenance, separate from immutable text revisions."""

import json
import sqlite3

SCHEMA = """
CREATE TABLE document_imports (
    source_namespace TEXT NOT NULL,
    source_document_id TEXT NOT NULL,
    document_id TEXT NOT NULL UNIQUE REFERENCES documents(id),
    imported_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
    source_ordinal INTEGER NOT NULL,
    source_file_sha256 TEXT NOT NULL,
    row_sha256 TEXT NOT NULL,
    original_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (source_namespace, source_document_id)
);
CREATE TABLE document_revision_metadata (
    revision_id TEXT PRIMARY KEY REFERENCES document_revisions(id),
    category TEXT,
    policy_decision_ids_json TEXT NOT NULL,
    source_ids_json TEXT NOT NULL,
    source_version TEXT,
    review_status TEXT NOT NULL
);
CREATE TRIGGER document_metadata_immutable_update
BEFORE UPDATE ON document_revision_metadata BEGIN
    SELECT RAISE(ABORT, 'revision metadata is immutable');
END;
CREATE TRIGGER document_metadata_immutable_delete
BEFORE DELETE ON document_revision_metadata BEGIN
    SELECT RAISE(ABORT, 'revision metadata is immutable');
END;
"""


def execute_schema(connection: sqlite3.Connection, schema: str) -> None:
    # executescript implicitly commits; statements must stay in the caller's transaction.
    statement = ""
    for line in schema.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("Incomplete schema")


def insert_metadata(connection, revision_id, metadata=None):
    data = metadata or {}
    connection.execute(
        "INSERT INTO document_revision_metadata VALUES (?, ?, ?, ?, ?, ?)",
        (
            revision_id,
            data.get("category"),
            json.dumps(data.get("policy_decision_ids", []), ensure_ascii=False),
            json.dumps(data.get("source_ids", []), ensure_ascii=False),
            data.get("source_version", data.get("version")),
            data.get("review_status", "unreviewed"),
        ),
    )


def read_metadata(connection, revision_id):
    row = connection.execute(
        "SELECT * FROM document_revision_metadata WHERE revision_id = ?", (revision_id,)
    ).fetchone()
    if row is None:
        return {
            "category": None,
            "policy_decision_ids": [],
            "source_ids": [],
            "source_version": None,
            "review_status": "unreviewed",
        }
    return {
        "category": row["category"],
        "policy_decision_ids": json.loads(row["policy_decision_ids_json"]),
        "source_ids": json.loads(row["source_ids_json"]),
        "source_version": row["source_version"],
        "review_status": row["review_status"],
    }
