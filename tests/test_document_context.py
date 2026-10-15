import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.documents.context import DocumentContextProvider, DocumentStorageError
from app.documents.repository import DocumentRepository


class DocumentContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = DocumentRepository(self.directory / "db.sqlite3")
        self.repo.initialize()

    def create(self, title, effective_from=None, publish=True):
        with self.repo.transaction() as con:
            detail = self.repo.create_in_transaction(
                con,
                {"title": title, "body": " 원문\n ", "effective_from": effective_from},
            )
            if publish:
                detail = self.repo.publish_in_transaction(
                    con, detail["id"], 1, detail["draft"]["id"]
                )
        return detail

    def test_only_eligible_published_revisions_and_snapshot_is_stable(self):
        self.create("초안", publish=False)
        self.create("미래", effective_from="2099-01-01")
        stopped = self.create("중단")
        with self.repo.transaction() as con:
            self.repo.withdraw_in_transaction(con, stopped["id"], 2)
        active = self.create("유효", effective_from="2026-10-14")
        provider = DocumentContextProvider(repository=self.repo)
        snapshot = provider.snapshot(today=date(2026, 10, 14))
        self.assertEqual([d.title for d in snapshot.documents], ["유효"])
        self.assertEqual(provider.snapshot(today=date(2026, 10, 13)).documents, ())
        with self.repo.transaction() as con:
            changed = self.repo.update_draft_in_transaction(
                con, active["id"], 2, {"title": "수정", "body": "새 본문"}
            )
        self.assertEqual(
            provider.snapshot(today=date(2026, 10, 14)).fingerprint,
            snapshot.fingerprint,
        )
        with self.repo.transaction() as con:
            self.repo.publish_in_transaction(
                con, active["id"], 3, changed["draft"]["id"]
            )
        self.assertNotEqual(provider.snapshot().fingerprint, snapshot.fingerprint)
        self.assertEqual(snapshot.documents[0].body, " 원문\n ")
        with self.assertRaises(TypeError):
            snapshot.documents[0].metadata["review_status"] = "approved"

    def test_missing_corrupt_and_old_schema_fail_without_creating_or_fallback(self):
        path = self.directory / "missing.sqlite3"
        with self.assertRaises(DocumentStorageError):
            DocumentContextProvider(database_path=path).snapshot()
        self.assertFalse(path.exists())
        path.write_bytes(b"corrupt")
        with self.assertRaises(DocumentStorageError):
            DocumentContextProvider(database_path=path).snapshot()
        with self.repo.transaction() as con:
            con.execute("PRAGMA user_version=1")
        with self.assertRaises(DocumentStorageError):
            DocumentContextProvider(repository=self.repo).snapshot()
