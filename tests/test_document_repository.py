"""SQLite behavior for managed documents uses only temporary databases."""

import tempfile
import unittest
from pathlib import Path

from app.document_repository import DocumentRepository


class DocumentRepositoryTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db_path = Path(directory) / "documents.sqlite3"
        self.repository = DocumentRepository(self.db_path)
        self.repository.initialize()

    def test_create_in_transaction_persists_a_draft_without_listing_body(self):
        fields = {
            "title": "휴가 안내",
            "body": "첫 줄\n둘째 줄",
            "source_label": "",
            "source_url": None,
            "owner_department": None,
            "effective_from": None,
        }

        with self.repository.transaction() as connection:
            created = self.repository.create_in_transaction(connection, fields)

        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["draft"]["body"], fields["body"])
        self.assertIsNone(created["published"])
        self.assertEqual(self.repository.get(created["id"]), created)

        listing = self.repository.list()
        self.assertEqual(listing["total"], 1)
        summary = listing["items"][0]
        self.assertEqual(summary["id"], created["id"])
        self.assertNotIn("body", summary["draft"])

    def test_create_in_transaction_rolls_back_with_the_callers_transaction(self):
        with (
            self.assertRaisesRegex(RuntimeError, "abort"),
            self.repository.transaction() as connection,
        ):
            created = self.repository.create_in_transaction(
                connection,
                {
                    "title": "되돌릴 초안",
                    "body": "저장되면 안 되는 본문",
                },
            )
            raise RuntimeError("abort")

        self.assertIsNone(self.repository.get(created["id"]))
        self.assertEqual(self.repository.list()["total"], 0)

    def test_database_reopen_preserves_document_and_revisions_are_immutable(self):
        with self.repository.transaction() as connection:
            created = self.repository.create_in_transaction(
                connection,
                {"title": "보존 문서", "body": "원문\n그대로"},
            )

        reopened = DocumentRepository(self.db_path)
        reopened.initialize()
        self.assertEqual(reopened.get(created["id"]), created)

        with (
            self.assertRaisesRegex(Exception, "immutable"),
            reopened.transaction() as connection,
        ):
            connection.execute(
                "UPDATE document_revisions SET body = ? WHERE id = ?",
                ("변경된 원문", created["draft"]["id"]),
            )

        self.assertEqual(reopened.get(created["id"])["draft"]["body"], "원문\n그대로")

    def test_duplicate_title_and_body_normalization_returns_existing_id(self):
        with self.repository.transaction() as connection:
            created = self.repository.create_in_transaction(
                connection,
                {"title": " 휴가   안내 ", "body": "신청 절차\n확인"},
            )

        with (
            self.assertRaisesRegex(Exception, "normalized title and body") as raised,
            self.repository.transaction() as connection,
        ):
            self.repository.create_in_transaction(
                connection,
                {"title": "휴가 안내", "body": "신청 절차 확인"},
            )
        self.assertEqual(raised.exception.existing_id, created["id"])
        self.assertEqual(self.repository.list()["total"], 1)


if __name__ == "__main__":
    unittest.main()
