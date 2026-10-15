import fcntl
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import patch

from app.documents import service
from app.documents.repository import DocumentRepository
from app.documents.reset import reset_demo_documents
from app.documents.transfer import import_knowledge


class DemoDocumentResetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / "seed.jsonl"
        self.source.write_text(
            json.dumps(
                {
                    "document_id": "seed-1",
                    "title": "기준",
                    "document": "원문",
                    "category": "정책",
                    "version": "1",
                    "review_status": "reviewed",
                    "source_ids": ["source-1"],
                    "policy_decision_ids": ["policy-1"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        self.db = self.root / "documents.sqlite3"
        import_knowledge(self.source, self.db, apply=True, publish=True)
        self.repo = DocumentRepository(self.db)
        self.original = self.repo.list()["items"][0]

    def reset(self, **kwargs):
        return reset_demo_documents(self.source, self.db, **kwargs)

    def test_restore_and_backup_with_stale_requests_rejected(self):
        original = self.original
        key = str(uuid.uuid4())
        payload = {"expected_version": original["record_version"], "body": "변경"}
        _, edited = service.update_document(self.repo, original["id"], payload, key)
        _, withdrawn = service.withdraw_document(
            self.repo, original["id"], edited["record_version"], str(uuid.uuid4())
        )
        _, extra = service.create_document(
            self.repo, {"title": "추가", "body": "시연"}, str(uuid.uuid4())
        )
        report = self.reset(apply=True)
        restored = self.repo.get(original["id"])
        self.assertEqual(restored["published"]["body"], "원문")
        self.assertEqual(restored["published"]["metadata"]["source_ids"], ["source-1"])
        self.assertGreater(restored["record_version"], withdrawn["record_version"])
        self.assertEqual(self.repo.list()["total"], 1)
        self.assertIsNone(self.repo.get(extra["id"]))
        backup = DocumentRepository(Path(report["backup_dir"]) / "database.sqlite3")
        self.assertEqual(backup.get(original["id"])["draft"]["body"], "변경")
        self.assertIsNotNone(backup.get(extra["id"]))
        with self.assertRaises(service.DocumentServiceError) as replay:
            service.update_document(self.repo, original["id"], payload, key)
        self.assertEqual(replay.exception.status_code, 409)
        with self.assertRaises(service.DocumentServiceError) as stale:
            service.update_document(
                self.repo, original["id"], payload, str(uuid.uuid4())
            )
        self.assertEqual(stale.exception.status_code, 409)

    def test_dry_run_does_not_change_database_or_create_files(self):
        before = self.db.read_bytes()
        files = set(self.root.rglob("*"))
        report = self.reset()
        self.assertFalse(report["applied"])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(set(self.root.rglob("*")), files)

    def test_invalid_source_preserves_database(self):
        before = self.db.read_bytes()
        self.source.write_text("")
        with self.assertRaises(ValueError):
            self.reset(apply=True)
        self.assertEqual(self.db.read_bytes(), before)

    def test_backup_failure_and_partial_reset_roll_back(self):
        from app.documents import reset as module

        for target in ("_backup", "_verify_restored"):
            before = self.repo.get(self.original["id"])
            original = getattr(module, target)
            calls = 0

            def fail_live(*args, target=target, original=original):
                nonlocal calls
                calls += 1
                # Verification first happens during the memory rehearsal.
                if target == "_backup" or calls == 2:
                    raise OSError("injected failure")
                return original(*args)

            with (
                patch.object(module, target, side_effect=fail_live),
                self.assertRaises(OSError),
            ):
                self.reset(apply=True)
            self.assertEqual(self.repo.get(self.original["id"]), before)
            with (
                self.repo.transaction() as con,
                self.assertRaises(sqlite3.IntegrityError),
            ):
                con.execute("DELETE FROM document_revisions")
            manifests = [
                json.loads(p.read_text())
                for p in self.root.glob("backups/demo-reset-*/manifest.json")
            ]
            self.assertTrue(any(m["status"] == "failed" for m in manifests))

    def test_unsupported_schema_and_missing_database_are_not_modified(self):
        with sqlite3.connect(self.db) as con:
            con.execute("PRAGMA user_version=999")
        before = self.db.read_bytes()
        with self.assertRaises(ValueError):
            self.reset(apply=True)
        self.assertEqual(self.db.read_bytes(), before)
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(FileNotFoundError):
            reset_demo_documents(self.source, missing, apply=True)
        self.assertFalse(missing.exists())

    def test_process_lock_rejects_duplicate_reset(self):
        with Path(str(self.db) + ".reset.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run = subprocess.run(
                [
                    sys.executable,
                    "scripts/reset_demo_documents.py",
                    "--source",
                    str(self.source),
                    "--database",
                    str(self.db),
                    "--apply",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(run.returncode, 1)
            self.assertEqual(json.loads(run.stderr)["error_type"], "RuntimeError")
        self.assertFalse(list(self.root.glob("backups/demo-reset-*")))

    def test_wal_readers_see_complete_snapshot_and_writes_wait(self):
        from app.documents import reset as module

        with sqlite3.connect(self.db) as con:
            con.execute("PRAGMA journal_mode=WAL")
        _, extra = service.create_document(
            self.repo, {"title": "추가", "body": "본문"}, str(uuid.uuid4())
        )
        entered, release, writer_started = Event(), Event(), Event()
        verify = module._verify_restored
        calls = 0

        def pause_after_replace(*args):
            nonlocal calls
            verify(*args)
            calls += 1
            if calls == 2:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test release missing")

        def write():
            writer_started.set()
            return service.create_document(
                self.repo, {"title": "이후", "body": "본문"}, str(uuid.uuid4())
            )

        with (
            patch.object(module, "_verify_restored", side_effect=pause_after_replace),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            resetting = pool.submit(self.reset, apply=True)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(len(self.repo.published_snapshot()), 1)
                self.assertIsNotNone(self.repo.get(extra["id"]))
                writing = pool.submit(write)
                self.assertTrue(writer_started.wait(2))
                with self.assertRaises(TimeoutError):
                    writing.result(timeout=0.1)
            finally:
                release.set()
            report = resetting.result(timeout=5)
            writing.result(timeout=5)
        self.assertIsNone(self.repo.get(extra["id"]))
        self.assertEqual(self.repo.list()["total"], 2)
        self.assertEqual(
            DocumentRepository(Path(report["backup_dir"]) / "database.sqlite3").list()[
                "total"
            ],
            2,
        )

    def test_idempotency_ttl_is_not_extended_and_repeated_reset_increments_version(
        self,
    ):
        key = str(uuid.uuid4())
        fields = {"title": "추가", "body": "본문"}
        service.create_document(self.repo, fields, key)
        with self.repo.transaction() as con:
            created = con.execute(
                "SELECT created_at FROM idempotency_keys WHERE key=?", (key,)
            ).fetchone()[0]
        self.reset(apply=True)
        first = self.repo.get(self.original["id"])["record_version"]
        self.reset(apply=True)
        self.assertGreater(self.repo.get(self.original["id"])["record_version"], first)
        with self.assertRaises(service.DocumentServiceError) as result:
            service.create_document(self.repo, fields, key)
        self.assertEqual(result.exception.status_code, 409)
        with self.repo.transaction() as con:
            self.assertEqual(
                con.execute(
                    "SELECT created_at FROM idempotency_keys WHERE key=?", (key,)
                ).fetchone()[0],
                created,
            )
            con.execute(
                "UPDATE idempotency_keys SET created_at=? WHERE key=?",
                ((datetime.now(UTC) - timedelta(hours=25)).isoformat(), key),
            )
        status, _ = service.create_document(self.repo, fields, key)
        self.assertEqual(status, 201)

    def test_cli_dry_run_and_error_do_not_leak_document_content(self):
        from scripts.reset_demo_documents import main

        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--source", str(self.source), "--database", str(self.db)])
        self.assertEqual(status, 0)
        self.assertFalse(json.loads(output.getvalue())["applied"])
        error = io.StringIO()
        with (
            patch(
                "scripts.reset_demo_documents.reset_demo_documents",
                side_effect=ValueError("PRIVATE CONTENT"),
            ),
            redirect_stderr(error),
        ):
            status = main(["--source", str(self.source), "--database", str(self.db)])
        self.assertEqual(status, 1)
        self.assertNotIn("PRIVATE CONTENT", error.getvalue())

    def test_full_repository_baseline_and_legacy_provenance(self):
        from app.settings import DEFAULT_DOCUMENTS_PATH
        from scripts.import_registered_documents import import_registered_documents

        legacy = self.root / "legacy.jsonl"
        legacy.write_text(json.dumps({"doc": "레거시 본문"}) + "\n")
        import_registered_documents(
            source_path=legacy,
            database_path=self.db,
            source_id="legacy-test",
            apply=True,
            backup_dir=self.root / "legacy-backups",
        )
        original_source = DEFAULT_DOCUMENTS_PATH.read_bytes()
        rows = [
            json.loads(line) for line in original_source.splitlines() if line.strip()
        ]
        report = reset_demo_documents(DEFAULT_DOCUMENTS_PATH, self.db, apply=True)
        snapshot = self.repo.published_snapshot()
        self.assertEqual(report["restored_count"], len(rows))
        self.assertEqual(
            [d["published"]["body"] for d in snapshot], [r["document"] for r in rows]
        )
        self.assertEqual(DEFAULT_DOCUMENTS_PATH.read_bytes(), original_source)
        with self.repo.transaction(immediate=False) as con:
            self.assertEqual(
                con.execute("SELECT count(*) FROM legacy_document_imports").fetchone()[
                    0
                ],
                0,
            )
        backup = DocumentRepository(Path(report["backup_dir"]) / "database.sqlite3")
        with backup.transaction(immediate=False) as con:
            self.assertEqual(
                con.execute("SELECT count(*) FROM legacy_document_imports").fetchone()[
                    0
                ],
                1,
            )

    def test_http_after_reset_and_legacy_registration(self):
        from fastapi.testclient import TestClient

        from app.fastapi_main import app

        with (
            patch.dict("os.environ", {"SANAEBI_DOCUMENT_DB": str(self.db)}),
            TestClient(app) as client,
        ):
            key = str(uuid.uuid4())
            headers = {"Idempotency-Key": key}
            fields = {"title": "추가", "body": "시연"}
            created = client.post("/documents", json=fields, headers=headers)
            self.assertEqual(created.status_code, 201)
            self.reset(apply=True)
            replay = client.post("/documents", json=fields, headers=headers)
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(replay.json()["error"]["code"], "idempotency_conflict")
            self.assertEqual(
                client.get("/documents/" + created.json()["id"]).status_code, 404
            )
            stale = client.patch(
                "/documents/" + self.original["id"],
                json={
                    "expected_version": self.original["record_version"],
                    "body": "old",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["error"]["code"], "revision_conflict")
            self.assertEqual(
                client.post("/regist-docs", json={"doc": "새 레거시 문서"}).status_code,
                200,
            )
            self.assertEqual(client.get("/documents").json()["total"], 2)

    def test_invalid_row_and_duplicate_baseline_are_rejected_before_backup(self):
        valid = self.source.read_text()
        for content in ('{"document_id": "bad"}\n', valid + valid):
            self.source.write_text(content)
            before = self.db.read_bytes()
            with self.assertRaises(ValueError):
                self.reset(apply=True)
            self.assertEqual(self.db.read_bytes(), before)
            self.assertFalse(list(self.root.glob("backups/demo-reset-*")))


if __name__ == "__main__":
    unittest.main()
