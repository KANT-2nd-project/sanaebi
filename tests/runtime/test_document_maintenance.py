import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.documents import service
from app.documents.repository import DocumentRepository
from app.documents.reset import reset_demo_documents
from app.settings import DEFAULT_DOCUMENTS_PATH


class DocumentMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = DocumentRepository(self.root / "documents.sqlite3")
        self.repo.initialize()

    def run_action(self, action, key=None, preview=None):
        preview = preview or service.preview_maintenance(
            self.repo, action, DEFAULT_DOCUMENTS_PATH
        )
        return service.maintain_documents(
            self.repo,
            action,
            preview["expected_state"],
            key or str(uuid.uuid4()),
            DEFAULT_DOCUMENTS_PATH,
        )

    def test_clear_no_backup_and_replay_after_new_document(self):
        service.create_document(
            self.repo, {"title": "초안", "body": "내용"}, str(uuid.uuid4())
        )
        preview = service.preview_maintenance(self.repo, "clear", self.root / "missing")
        key = str(uuid.uuid4())
        first = self.run_action("clear", key, preview)
        self.assertEqual(first["deleted_count"], 1)
        self.assertEqual(self.repo.list()["total"], 0)
        self.assertFalse((self.root / "backups").exists())
        service.create_document(
            self.repo, {"title": "후속", "body": "보존"}, str(uuid.uuid4())
        )
        self.assertEqual(self.run_action("clear", key, preview), first)
        self.assertEqual(self.repo.list()["total"], 1)

    def test_clear_restore_rejects_pre_clear_version_and_cli_uses_floor(self):
        self.run_action("restore")
        original = self.repo.list()["items"][0]
        self.run_action("clear")
        reset_demo_documents(DEFAULT_DOCUMENTS_PATH, self.repo.path, apply=True)
        restored = self.repo.get(original["id"])
        self.assertGreater(restored["record_version"], original["record_version"])
        with self.assertRaises(service.DocumentServiceError) as error:
            service.update_document(
                self.repo,
                original["id"],
                {"expected_version": original["record_version"], "body": "오래된 변경"},
                str(uuid.uuid4()),
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_changed_preview_rejected(self):
        preview = service.preview_maintenance(
            self.repo, "clear", DEFAULT_DOCUMENTS_PATH
        )
        service.create_document(
            self.repo, {"title": "새 문서", "body": "보존"}, str(uuid.uuid4())
        )
        with self.assertRaises(service.DocumentServiceError) as error:
            self.run_action("clear", preview=preview)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.repo.list()["total"], 1)

    def test_restore_backup_failure_preserves_documents(self):
        service.create_document(
            self.repo, {"title": "보존", "body": "내용"}, str(uuid.uuid4())
        )
        with (
            patch("app.documents.reset._backup", side_effect=OSError("private/path")),
            self.assertRaises(service.DocumentServiceError) as error,
        ):
            self.run_action("restore")
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(self.repo.list()["total"], 1)

    def test_empty_clear_changes_token_and_keeps_unrelated_table(self):
        with self.repo.transaction() as con:
            con.execute("CREATE TABLE unrelated (value TEXT)")
            con.execute("INSERT INTO unrelated VALUES ('keep')")
        preview = service.preview_maintenance(
            self.repo, "clear", DEFAULT_DOCUMENTS_PATH
        )
        self.run_action("clear", preview=preview)
        self.assertNotEqual(
            preview["expected_state"],
            service.preview_maintenance(self.repo, "clear", DEFAULT_DOCUMENTS_PATH)[
                "expected_state"
            ],
        )
        with self.repo.transaction(immediate=False) as con:
            self.assertEqual(
                con.execute("SELECT value FROM unrelated").fetchone()[0], "keep"
            )

    def test_changed_source_rejected_and_failed_validation_no_backup(self):
        source = self.root / "baseline.jsonl"
        source.write_bytes(DEFAULT_DOCUMENTS_PATH.read_bytes())
        preview = service.preview_maintenance(self.repo, "restore", source)
        source.write_bytes(source.read_bytes() + b"\n")
        with self.assertRaises(service.DocumentServiceError) as error:
            service.maintain_documents(
                self.repo,
                "restore",
                preview["expected_state"],
                str(uuid.uuid4()),
                source,
            )
        self.assertEqual(error.exception.status_code, 409)
        source.write_text("invalid")
        with self.assertRaises(service.DocumentServiceError):
            service.preview_maintenance(self.repo, "restore", source)
        self.assertFalse((self.root / "backups").exists())

    def test_rollback_preserves_data_keys_and_immutable_triggers(self):
        key = str(uuid.uuid4())
        fields = {"title": "보존", "body": "내용"}
        _, before = service.create_document(self.repo, fields, key)
        with (
            patch(
                "app.documents.reset._verify_restored", side_effect=ValueError("failed")
            ),
            self.assertRaises(service.DocumentServiceError),
        ):
            self.run_action("clear")
        self.assertEqual(service.create_document(self.repo, fields, key)[1], before)
        self.assertEqual(self.repo.get(before["id"]), before)
        import sqlite3

        with self.repo.transaction() as con, self.assertRaises(sqlite3.IntegrityError):
            con.execute("DELETE FROM document_revisions")

    def test_duplicate_key_after_restore_does_not_require_baseline(self):
        key = str(uuid.uuid4())
        preview = service.preview_maintenance(
            self.repo, "restore", DEFAULT_DOCUMENTS_PATH
        )
        result = self.run_action("restore", key, preview)
        self.assertEqual(
            service.maintain_documents(
                self.repo,
                "restore",
                preview["expected_state"],
                key,
                self.root / "missing",
            ),
            result,
        )
        self.assertEqual(len(list((self.root / "backups").iterdir())), 1)
        backup = next((self.root / "backups").iterdir())
        self.assertTrue((backup / "database.sqlite3").is_file())

    def test_v2_migration_preserves_data(self):
        _, before = service.create_document(
            self.repo, {"title": "이전 문서", "body": "원문"}, str(uuid.uuid4())
        )
        with self.repo.transaction() as con:
            con.execute("DROP TABLE document_maintenance_state")
            con.execute("PRAGMA user_version=2")
        self.repo.initialize()
        self.assertEqual(self.repo.get(before["id"]), before)
        self.run_action("clear")
        self.assertEqual(self.repo.list()["total"], 0)

    def test_reset_lock_and_simultaneous_actions(self):
        from concurrent.futures import ThreadPoolExecutor

        from app.documents.reset import reset_lock

        preview = service.preview_maintenance(
            self.repo, "clear", DEFAULT_DOCUMENTS_PATH
        )
        with (
            reset_lock(self.repo.path),
            self.assertRaises(service.DocumentServiceError) as error,
        ):
            self.run_action("clear", preview=preview)
        self.assertEqual(error.exception.code, "maintenance_busy")

        def execute(_):
            try:
                return self.run_action("clear", preview=preview)
            except service.DocumentServiceError as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, range(2)))
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertIn(409, results)

    def test_clear_all_document_history_preserves_baseline_and_existing_backups(self):
        baseline = DEFAULT_DOCUMENTS_PATH.read_bytes()
        self.run_action("restore")
        original = self.repo.list()["items"][0]
        _, edited = service.update_document(
            self.repo,
            original["id"],
            {"expected_version": original["record_version"], "body": "수정 초안"},
            str(uuid.uuid4()),
        )
        service.withdraw_document(
            self.repo, original["id"], edited["record_version"], str(uuid.uuid4())
        )
        key = str(uuid.uuid4())
        fields = {"title": "추가 초안", "body": "내용"}
        service.create_document(self.repo, fields, key)
        backups = {
            p: p.read_bytes() for p in (self.root / "backups").rglob("*") if p.is_file()
        }
        self.run_action("clear")
        from app.documents.reset import TABLES

        with self.repo.transaction(immediate=False) as con:
            for table in TABLES:
                self.assertEqual(
                    con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 0
                )
        self.assertEqual(DEFAULT_DOCUMENTS_PATH.read_bytes(), baseline)
        self.assertEqual(
            backups,
            {
                p: p.read_bytes()
                for p in (self.root / "backups").rglob("*")
                if p.is_file()
            },
        )
        with self.assertRaises(service.DocumentServiceError) as error:
            service.create_document(self.repo, fields, key)
        self.assertEqual(error.exception.status_code, 409)

    def test_failure_after_commit_replays_saved_result(self):
        original_write = Path.write_text

        def fail_final_manifest(path, text, *args, **kwargs):
            if path.name == "manifest.json" and '"success"' in text:
                raise OSError("manifest failed")
            return original_write(path, text, *args, **kwargs)

        key = str(uuid.uuid4())
        preview = service.preview_maintenance(
            self.repo, "restore", DEFAULT_DOCUMENTS_PATH
        )
        with (
            patch.object(Path, "write_text", fail_final_manifest),
            self.assertRaises(service.DocumentServiceError),
        ):
            self.run_action("restore", key, preview)
        count = self.repo.list()["total"]
        self.assertGreater(count, 0)
        self.assertEqual(
            self.run_action("restore", key, preview)["restored_count"], count
        )
        self.assertEqual(len(list((self.root / "backups").iterdir())), 1)

    def test_clear_then_normal_import_cannot_revive_old_version(self):
        from app.documents.transfer import import_knowledge

        self.run_action("restore")
        original = self.repo.list()["items"][0]
        self.run_action("clear")
        import_knowledge(
            DEFAULT_DOCUMENTS_PATH, self.repo.path, apply=True, publish=True
        )
        restored = self.repo.get(original["id"])
        self.assertGreater(restored["record_version"], original["record_version"])
