import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.document_repository import DocumentRepository
from app.services.document_context import DocumentContextProvider


class PublishedSnapshotStub:
    def __init__(self, documents=()):
        self.documents = list(documents)
        self.today = None

    def published_snapshot(self, today=None):
        self.today = today
        return self.documents


class DocumentContextTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.baseline_path = Path(directory) / "baseline.jsonl"

    def write_rows(self, rows):
        self.baseline_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_merges_baseline_and_published_documents_as_typed_snapshot(self):
        self.write_rows(
            [
                {
                    "document_id": "baseline-1",
                    "version": "2.0",
                    "title": "기본 문서",
                    "document": "기본 본문",
                }
            ]
        )
        published = {
            "id": "8f0b1dec-2081-43d4-8aa9-b604a0367df0",
            "published": {
                "revision_number": 3,
                "title": "등록 문서",
                "body": "게시 본문",
                "source_url": "https://example.test/policy",
            },
        }
        repository = PublishedSnapshotStub([published])
        today = date(2026, 10, 14)

        snapshot = DocumentContextProvider(
            baseline_path=self.baseline_path, repository=repository
        ).snapshot(today=today)

        self.assertEqual(repository.today, today)
        self.assertEqual(snapshot.duplicate_count, 0)
        self.assertEqual(len(snapshot.documents), 2)
        baseline, registered = snapshot.documents
        self.assertEqual(baseline.source_kind, "baseline")
        self.assertEqual(baseline.document_id, "baseline-1")
        self.assertEqual(baseline.title, "기본 문서")
        self.assertEqual(baseline.body, "기본 본문")
        self.assertTrue(baseline.revision.startswith("2.0:"))
        self.assertEqual(registered.source_kind, "registered")
        self.assertEqual(registered.document_id, published["id"])
        self.assertEqual(registered.revision, "3")
        self.assertEqual(registered.source_reference, "https://example.test/policy")

    def test_idless_rows_use_content_hash_and_exact_duplicates_are_counted(self):
        row = {"title": "제목", "document": "본문"}
        self.write_rows([row, row])

        snapshot = DocumentContextProvider(
            baseline_path=self.baseline_path,
            repository=PublishedSnapshotStub(),
        ).snapshot()

        expected_id = hashlib.sha256("제목본문".encode()).hexdigest()
        self.assertEqual(snapshot.duplicate_count, 1)
        self.assertEqual(len(snapshot.documents), 1)
        self.assertEqual(snapshot.documents[0].document_id, expected_id)
        self.assertEqual(
            snapshot.documents[0].revision,
            hashlib.sha256("본문".encode()).hexdigest(),
        )

    def test_repeated_id_with_different_content_is_an_error(self):
        self.write_rows(
            [
                {"document_id": "same", "title": "제목", "document": "본문 1"},
                {"document_id": "same", "title": "제목", "document": "본문 2"},
            ]
        )

        with self.assertRaisesRegex(ValueError, "중복.*ID|ID.*중복"):
            DocumentContextProvider(
                baseline_path=self.baseline_path,
                repository=PublishedSnapshotStub(),
            ).snapshot()

    def test_real_repository_snapshot_uses_published_revision_and_filters_state(self):
        document_id = "same-id-in-both-sources"
        self.write_rows(
            [
                {
                    "document_id": document_id,
                    "title": "Baseline 이름",
                    "document": "Baseline 본문",
                }
            ]
        )
        repository = DocumentRepository(self.baseline_path.parent / "runtime.sqlite3")
        repository.initialize()

        def create_and_publish(title, body, **metadata):
            fields = {
                "title": title,
                "body": body,
                "source_label": "테스트",
                "source_url": None,
                "owner_department": None,
                "effective_from": None,
            } | metadata
            with repository.transaction() as connection:
                detail = repository.create_in_transaction(connection, fields)
            with repository.transaction() as connection:
                return repository.publish_in_transaction(
                    connection,
                    detail["id"],
                    detail["record_version"],
                    detail["draft"]["id"],
                )

        create_and_publish(
            "현재 게시본",
            "현재 본문",
            source_url="https://example.test/current",
        )
        create_and_publish("미래 시행본", "아직 적용 전", effective_from="2026-10-15")
        withdrawn = create_and_publish("중단 문서", "답변에서 제외")
        with repository.transaction() as connection:
            repository.withdraw_in_transaction(
                connection, withdrawn["id"], withdrawn["record_version"]
            )

        revised = create_and_publish("개정 예정 문서", "현재 게시된 내용")
        with repository.transaction() as connection:
            repository.update_draft_in_transaction(
                connection,
                revised["id"],
                revised["record_version"],
                {
                    "title": "편집 중인 초안",
                    "body": "아직 게시하지 않은 내용",
                    "source_label": "테스트",
                    "source_url": None,
                    "owner_department": None,
                    "effective_from": None,
                },
            )

        snapshot = DocumentContextProvider(
            baseline_path=self.baseline_path, repository=repository
        ).snapshot(today=date(2026, 10, 14))

        self.assertEqual(len(snapshot.documents), 3)
        self.assertEqual(snapshot.documents[0].source_kind, "baseline")
        self.assertEqual(snapshot.documents[0].document_id, document_id)
        current = {item.title: item for item in snapshot.documents[1:]}
        self.assertEqual(set(current), {"현재 게시본", "개정 예정 문서"})
        self.assertEqual(current["현재 게시본"].body, "현재 본문")
        self.assertEqual(
            current["현재 게시본"].source_reference,
            "https://example.test/current",
        )
        self.assertEqual(current["개정 예정 문서"].body, "현재 게시된 내용")
        self.assertEqual(current["개정 예정 문서"].revision, "1")

    def test_missing_or_corrupt_baseline_is_not_silently_ignored(self):
        provider = DocumentContextProvider(
            baseline_path=self.baseline_path,
            repository=PublishedSnapshotStub(),
        )
        with self.assertRaises(FileNotFoundError):
            provider.snapshot()

        self.baseline_path.write_text('{"title": "broken"\n', encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            provider.snapshot()


if __name__ == "__main__":
    unittest.main()
