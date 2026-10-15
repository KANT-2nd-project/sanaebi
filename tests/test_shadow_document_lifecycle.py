"""The shadow route must observe published revisions, not drafts or stale bodies."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.documents.context import DocumentContextProvider
from app.documents.repository import DocumentRepository
from app.questions.service import handle_question


class ShadowDocumentLifecycleTests(unittest.TestCase):
    def test_publish_revise_withdraw_and_snapshot_once(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = DocumentRepository(Path(directory) / "isolated.sqlite3")
            repo.initialize()
            provider = DocumentContextProvider(repository=repo)
            reader = Mock(side_effect=provider.snapshot)
            observed = []

            def answer(question, snapshot):
                observed.append(snapshot)
                # A fresh write transaction can start here: no read transaction
                # may remain held across a remote answer call.
                with repo.transaction():
                    pass
                return snapshot.documents[0].body

            def ask():
                before = reader.call_count
                result = handle_question(
                    "새 제도 알려줘",
                    classify=lambda _: "UNSUPPORTED",
                    read_documents=reader,
                    answer=answer,
                    routing_mode="shadow",
                )
                self.assertEqual(reader.call_count, before + 1)
                return result.text

            self.assertIn("문서가 없어", ask())
            self.assertEqual(observed, [])
            with repo.transaction() as con:
                detail = repo.create_in_transaction(
                    con, {"title": "새 제도", "body": "월 1회 신청합니다."}
                )
                repo.publish_in_transaction(con, detail["id"], 1, detail["draft"]["id"])
            self.assertEqual(ask(), "월 1회 신청합니다.")
            with repo.transaction() as con:
                edited = repo.update_draft_in_transaction(
                    con,
                    detail["id"],
                    2,
                    {"title": "새 제도", "body": "분기 1회 신청합니다."},
                )
            self.assertEqual(ask(), "월 1회 신청합니다.")
            with repo.transaction() as con:
                repo.publish_in_transaction(con, detail["id"], 3, edited["draft"]["id"])
            self.assertEqual(ask(), "분기 1회 신청합니다.")
            self.assertEqual(observed[0].documents[0].body, "월 1회 신청합니다.")
            with repo.transaction() as con:
                repo.withdraw_in_transaction(con, detail["id"], 4)
            count = len(observed)
            self.assertIn("문서가 없어", ask())
            self.assertEqual(len(observed), count)
