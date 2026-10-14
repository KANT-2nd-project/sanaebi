import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.document_repository import DocumentRepository


class SqliteKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db = self.directory / "documents.sqlite3"
        self.repo = DocumentRepository(self.db)

    def test_schema_v2_and_original_document_survive_reinitialization(self):
        self.repo.initialize()
        with self.repo.transaction() as con:
            detail = self.repo.create_in_transaction(
                con, {"title": "제목", "body": " 원문\n "}
            )
        self.repo.initialize()
        self.assertEqual(self.repo.get(detail["id"])["draft"]["body"], " 원문\n ")
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)

    def source(self):
        source = self.directory / "source.jsonl"
        source.write_text(
            json.dumps(
                {
                    "document_id": "ieum-001",
                    "title": "제목",
                    "document": " 원문\n ",
                    "category": "policy",
                    "version": "2.0",
                    "review_status": "ai_reviewed",
                    "source_ids": ["H01"],
                    "policy_decision_ids": ["D01"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return source

    def test_import_is_dry_by_default_and_repeat_does_not_republish(self):
        from app.services.document_context import DocumentContextProvider
        from app.services.knowledge_transfer import export_knowledge, import_knowledge

        source = self.source()
        self.assertEqual(import_knowledge(source, self.db)["imported_count"], 1)
        self.assertFalse(self.db.exists())
        result = import_knowledge(source, self.db, apply=True, publish=True)
        document_id = result["mapping"][0]["document_id"]
        snap = DocumentContextProvider(repository=self.repo).snapshot()
        self.assertEqual(snap.documents[0].knowledge_id, "ieum-001")
        self.assertEqual(snap.documents[0].body, " 원문\n ")
        self.assertEqual(snap.documents[0].metadata["review_status"], "ai_reviewed")
        output = self.directory / "export.jsonl"
        export_knowledge(self.db, output)
        self.assertEqual(json.loads(output.read_text())["document_id"], "ieum-001")
        with self.repo.transaction() as con:
            self.repo.withdraw_in_transaction(con, document_id, 2)
        repeated = import_knowledge(source, self.db, apply=True, publish=True)
        self.assertEqual(repeated["skipped_count"], 1)
        self.assertEqual(
            DocumentContextProvider(repository=self.repo).snapshot().documents, ()
        )
        self.assertEqual(len(snap.documents), 1)

    def test_modified_source_rejects_entire_import_and_preserves_original(self):
        from app.services.knowledge_transfer import import_knowledge

        source = self.source()
        result = import_knowledge(source, self.db, apply=True, publish=True)
        source.write_text(source.read_text().replace("원문", "변경"))
        with self.assertRaisesRegex(ValueError, "Changed source"):
            import_knowledge(source, self.db, apply=True)
        self.assertEqual(
            self.repo.get(result["mapping"][0]["document_id"])["draft"]["body"],
            " 원문\n ",
        )

    def test_v1_upgrade_keeps_published_revisions(self):
        self.repo.initialize()
        with self.repo.transaction() as con:
            doc = self.repo.create_in_transaction(
                con, {"title": "기존", "body": "본문"}
            )
            self.repo.publish_in_transaction(con, doc["id"], 1, doc["draft"]["id"])
            con.execute("DROP TABLE document_revision_metadata")
            con.execute("DROP TABLE document_imports")
            con.execute("PRAGMA user_version=1")
        self.repo.initialize()
        detail = self.repo.get(doc["id"])
        self.assertEqual(detail["published"]["id"], doc["draft"]["id"])
        self.assertEqual(detail["published"]["metadata"]["review_status"], "unreviewed")

    def test_edit_invalidates_review_without_changing_published_metadata(self):
        from app.services.knowledge_transfer import import_knowledge

        result = import_knowledge(self.source(), self.db, apply=True, publish=True)
        key = result["mapping"][0]["document_id"]
        with self.repo.transaction() as con:
            changed = self.repo.update_draft_in_transaction(
                con, key, 2, {"title": "제목", "body": "수정"}
            )
        self.assertEqual(changed["draft"]["metadata"]["review_status"], "unreviewed")
        self.assertEqual(
            changed["published"]["metadata"]["review_status"], "ai_reviewed"
        )
        self.assertEqual(changed["draft"]["metadata"]["source_ids"], ["H01"])

    def test_apply_failure_rolls_back_schema_and_rows(self):
        from unittest.mock import patch

        from app.services.knowledge_transfer import import_knowledge

        original = DocumentRepository.publish_in_transaction
        count = [0]

        def fail_actual(repo, *args, **kwargs):
            count[0] += 1
            if count[0] == 2:
                raise RuntimeError("injected failure after insert")
            return original(repo, *args, **kwargs)

        with (
            patch.object(DocumentRepository, "publish_in_transaction", fail_actual),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            import_knowledge(self.source(), self.db, apply=True, publish=True)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(
                con.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0],
                0,
            )

    def test_backup_can_restore_previous_documents(self):
        from app.services.knowledge_transfer import import_knowledge

        self.repo.initialize()
        with self.repo.transaction() as con:
            existing = self.repo.create_in_transaction(
                con, {"title": "사용자 자료", "body": "보존"}
            )
        result = import_knowledge(self.source(), self.db, apply=True, publish=True)
        backup = DocumentRepository(Path(result["backup_dir"]) / "database.sqlite3")
        self.assertEqual(backup.list()["total"], 1)
        self.assertEqual(backup.get(existing["id"])["draft"]["body"], "보존")
        self.assertEqual(self.repo.list()["total"], 2)

    def test_export_is_byte_reproducible_and_does_not_overwrite(self):
        from app.services.knowledge_transfer import export_knowledge, import_knowledge

        import_knowledge(self.source(), self.db, apply=True, publish=True)
        first, second = self.directory / "a.jsonl", self.directory / "b.jsonl"
        one = export_knowledge(self.db, first)
        two = export_knowledge(self.db, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(one["snapshot_fingerprint"], two["snapshot_fingerprint"])
        with self.assertRaises(FileExistsError):
            export_knowledge(self.db, first)

    def test_existing_user_document_conflict_is_not_overwritten(self):
        from app.document_repository import DuplicateDocumentError
        from app.services.knowledge_transfer import import_knowledge

        self.repo.initialize()
        with self.repo.transaction() as con:
            existing = self.repo.create_in_transaction(
                con, {"title": "제목", "body": " 원문\n "}
            )
        with self.assertRaises(DuplicateDocumentError):
            import_knowledge(self.source(), self.db, apply=True, publish=True)
        self.assertEqual(self.repo.list()["total"], 1)
        self.assertIsNone(self.repo.get(existing["id"])["provenance"])

    def test_future_schema_rejected(self):
        self.repo.initialize()
        with self.repo.transaction() as con:
            con.execute("PRAGMA user_version=999")
        with self.assertRaisesRegex(RuntimeError, "Unsupported"):
            self.repo.initialize()
