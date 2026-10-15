import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.documents.repository import DocumentRepository
from scripts.import_registered_documents import (
    import_registered_documents,
)
from scripts.import_registered_documents import (
    main as import_main,
)


class RegisteredDocumentImportTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        self.source_path = root / "legacy.jsonl"
        self.database_path = root / "documents.sqlite3"
        self.backup_dir = root / "backups"

    def write_rows(self, rows):
        self.source_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def counts(self):
        with sqlite3.connect(self.database_path) as connection:
            documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[
                0
            ]
            provenance = connection.execute(
                "SELECT COUNT(*) FROM legacy_document_imports"
            ).fetchone()[0]
        return documents, provenance

    def run_import(self, *, source_id="legacy-app", apply=False):
        return import_registered_documents(
            source_path=self.source_path,
            database_path=self.database_path,
            source_id=source_id,
            apply=apply,
            backup_dir=self.backup_dir,
        )

    def test_default_dry_run_does_not_create_database_or_change_source(self):
        self.write_rows([{"doc": "기존 등록 본문"}])
        original = self.source_path.read_bytes()

        report = self.run_import()

        self.assertFalse(report.applied)
        self.assertEqual(report.imported_count, 1)
        self.assertFalse(self.database_path.exists())
        self.assertFalse(self.backup_dir.exists())
        self.assertEqual(self.source_path.read_bytes(), original)

    def test_cli_requires_an_explicit_source_id(self):
        with self.assertRaises(SystemExit) as result:
            import_main(
                ["--source", str(self.source_path), "--db", str(self.database_path)]
            )

        self.assertEqual(result.exception.code, 2)
        self.assertFalse(self.database_path.exists())

    def test_apply_then_append_and_rerun_imports_only_the_new_line(self):
        self.write_rows([{"doc": "첫 번째 본문"}])
        first = self.run_import(apply=True)
        self.assertEqual(first.imported_count, 1)
        self.assertEqual(self.counts(), (1, 1))

        with self.source_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"doc": "두 번째 본문"}, ensure_ascii=False) + "\n")
        original_after_append = self.source_path.read_bytes()
        second = self.run_import(apply=True)

        self.assertEqual(second.imported_count, 1)
        self.assertEqual(second.skipped_count, 1)
        self.assertEqual(self.counts(), (2, 2))
        self.assertEqual(self.source_path.read_bytes(), original_after_append)
        self.assertEqual(second.source_backup_path.read_bytes(), original_after_append)
        self.assertTrue(second.database_backup_path.is_file())
        with sqlite3.connect(second.database_backup_path) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                1,
            )
        manifest_path = second.source_backup_path.with_suffix(".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["source_sha256"],
            hashlib.sha256(original_after_append).hexdigest(),
        )

    def test_same_source_id_detects_changed_hash_for_an_imported_line(self):
        self.write_rows([{"doc": "원래 본문"}])
        self.run_import(apply=True)
        self.write_rows([{"doc": "수정된 본문"}])
        changed_source = self.source_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "충돌|변경"):
            self.run_import(apply=True)

        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.source_path.read_bytes(), changed_source)

    def test_same_source_id_rejects_truncating_previously_imported_lines(self):
        self.write_rows([{"doc": "첫 행"}, {"doc": "둘째 행"}])
        self.run_import(apply=True)
        self.write_rows([{"doc": "첫 행"}])
        truncated_source = self.source_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "사라졌습니다"):
            self.run_import(apply=True)

        self.assertEqual(self.counts(), (2, 2))
        self.assertEqual(self.source_path.read_bytes(), truncated_source)

    def test_imported_document_keeps_body_and_stays_a_draft(self):
        body = "  첫 줄\n둘째 줄  "
        self.write_rows([{"doc": body}])

        self.run_import(apply=True)

        with sqlite3.connect(self.database_path) as connection:
            document_id = connection.execute(
                "SELECT document_id FROM legacy_document_imports"
            ).fetchone()[0]
        detail = DocumentRepository(self.database_path).get(document_id)
        self.assertEqual(detail["status"], "draft")
        self.assertIsNone(detail["published"])
        self.assertEqual(detail["draft"]["title"], "기존 등록 문서 1")
        self.assertEqual(detail["draft"]["body"], body)

    def test_transaction_failure_rolls_back_every_imported_row(self):
        self.write_rows(
            [
                {"title": "같은 제목", "doc": "같은 본문"},
                {"title": "같은 제목", "doc": "같은 본문"},
            ]
        )
        original = self.source_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "제목과 본문 조합"):
            self.run_import(apply=True)

        self.assertTrue(self.database_path.exists())
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM sqlite_master
                       WHERE type = 'table' AND name LIKE 'legacy_document_import%'"""
                ).fetchone()[0],
                0,
            )
        self.assertEqual(self.source_path.read_bytes(), original)

    def test_failed_import_does_not_delete_another_connection_commit(self):
        self.write_rows(
            [
                {"title": "중복 제목", "doc": "중복 본문"},
                {"title": "중복 제목", "doc": "중복 본문"},
            ]
        )
        original_transaction = DocumentRepository.transaction
        transaction_calls = 0

        def add_concurrent_document_before_import_transaction(
            repository, immediate=True
        ):
            nonlocal transaction_calls
            transaction_calls += 1
            if transaction_calls == 2:
                with original_transaction(repository) as connection:
                    repository.create_in_transaction(
                        connection,
                        {
                            "title": "다른 요청 문서",
                            "body": "다른 요청 본문",
                            "source_label": "동시 요청",
                        },
                    )
            return original_transaction(repository, immediate=immediate)

        with (
            patch.object(
                DocumentRepository,
                "transaction",
                add_concurrent_document_before_import_transaction,
            ),
            self.assertRaisesRegex(ValueError, "제목과 본문 조합"),
        ):
            self.run_import(apply=True)

        self.assertEqual(transaction_calls, 2)
        self.assertTrue(self.database_path.exists())
        with sqlite3.connect(self.database_path) as connection:
            documents = connection.execute(
                """SELECT r.title, r.body FROM documents d
                   JOIN document_revisions r ON r.id = d.draft_revision_id"""
            ).fetchall()
            import_tables = connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type = 'table' AND name LIKE 'legacy_document_import%'"""
            ).fetchall()
        self.assertEqual(documents, [("다른 요청 문서", "다른 요청 본문")])
        self.assertEqual(import_tables, [])

    def test_invalid_later_row_fails_before_creating_database_or_backup(self):
        self.write_rows([{"doc": "유효한 첫 본문"}])
        with self.source_path.open("a", encoding="utf-8") as file:
            file.write('{"doc": "   "}\n')
        original = self.source_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "2행|2번째 줄"):
            self.run_import(apply=True)

        self.assertFalse(self.database_path.exists())
        self.assertFalse(self.backup_dir.exists())
        self.assertEqual(self.source_path.read_bytes(), original)

    def test_source_id_allows_the_same_copy_to_move_without_duplicate_import(self):
        self.write_rows([{"doc": "이동 가능한 원본"}])
        self.run_import(source_id="registered-docs-prod", apply=True)

        moved_source = self.source_path.parent / "moved.jsonl"
        moved_source.write_bytes(self.source_path.read_bytes())
        self.source_path = moved_source
        report = self.run_import(source_id="registered-docs-prod", apply=True)

        self.assertEqual(report.imported_count, 0)
        self.assertEqual(report.skipped_count, 1)
        self.assertEqual(self.counts(), (1, 1))


if __name__ == "__main__":
    unittest.main()
