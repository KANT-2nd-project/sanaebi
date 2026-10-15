import hashlib
import io
import json
import os
import signal
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.deploy_release import (
    DeploymentEngine,
    DeploymentError,
    Release,
    ReleaseInputs,
    _atomic_symlink,
    _check_path_chain,
    _pointer_target,
    _term_as_interrupt,
    parse_release_manifest,
    safe_extract_web_archive,
)
from scripts.production_maintenance import (
    HostPaths,
    MaintenanceError,
    create_daily_backups,
    reset_demo_documents,
    reset_demo_documents_with_backup,
    snapshot_sqlite_database,
)


class ReleaseInputTests(unittest.TestCase):
    def manifest(self, **changes):
        files = {
            "web.tar.gz": b"archive bytes",
            "model-release.json": b'{"schema_version":1}',
        }
        value = {
            "schema_version": 1,
            "release_id": "a" * 40 + "-12345",
            "image": "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64,
            "web_archive": "web.tar.gz",
            "web_sha256": hashlib.sha256(files["web.tar.gz"]).hexdigest(),
            "model_manifest": "model-release.json",
            "model_manifest_sha256": hashlib.sha256(
                files["model-release.json"]
            ).hexdigest(),
        }
        value.update(changes)
        return json.dumps(value).encode(), files

    def test_manifest_requires_exact_release_identity_and_digest_pinned_image(self):
        raw, _ = self.manifest(image="ghcr.io/kant-2nd-project/sanaebi-api:latest")

        with self.assertRaises(DeploymentError):
            parse_release_manifest(raw, "a" * 40 + "-12345")

    def test_manifest_rejects_archive_path_escape(self):
        raw, _ = self.manifest(web_archive="../web.tar.gz")

        with self.assertRaises(DeploymentError):
            parse_release_manifest(raw, "a" * 40 + "-12345")

    def test_manifest_rejects_hash_mismatch(self):
        raw, files = self.manifest(web_sha256="0" * 64)
        release = parse_release_manifest(raw, "a" * 40 + "-12345")

        with self.assertRaises(DeploymentError):
            release.verify_payload_hashes(files)

    def make_archive(self, root, name, content=b"content", kind=tarfile.REGTYPE):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
        root.write_bytes(archive.getvalue())

    def test_web_archive_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "web.tar.gz"
            self.make_archive(archive, "../escaped.txt")

            with self.assertRaises(DeploymentError):
                safe_extract_web_archive(archive, root / "web")

            self.assertFalse((root.parent / "escaped.txt").exists())

    def test_web_archive_rejects_symlinks_and_requires_static_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "web.tar.gz"
            self.make_archive(archive, "index.html", kind=tarfile.SYMTYPE)

            with self.assertRaises(DeploymentError):
                safe_extract_web_archive(archive, root / "web")


class SqliteBackupTests(unittest.TestCase):
    def test_snapshot_uses_sqlite_backup_and_preserves_live_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "documents.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE records (value TEXT)")
                connection.execute("INSERT INTO records VALUES ('preserve me')")
            destination = root / "backups" / "snapshot.sqlite3"

            snapshot_sqlite_database(source, destination)

            with sqlite3.connect(destination) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM records").fetchone()[0],
                    "preserve me",
                )
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                )
            with sqlite3.connect(source) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM records").fetchone()[0], 1
                )

    def test_snapshot_refuses_to_overwrite_an_existing_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "documents.sqlite3"
            destination = root / "snapshot.sqlite3"
            sqlite3.connect(source).close()
            destination.write_bytes(b"keep")

            with self.assertRaises(FileExistsError):
                snapshot_sqlite_database(source, destination)

            self.assertEqual(destination.read_bytes(), b"keep")

    def test_daily_backup_includes_optional_generation_budget_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "var" / "lib" / "sanaebi" / "runtime"
            data.mkdir(parents=True)
            paths = HostPaths(root=root / "srv" / "sanaebi", data=data)
            sqlite3.connect(paths.database).close()
            sqlite3.connect(paths.generation_budget_database).close()

            backups = create_daily_backups(paths)

            self.assertEqual(set(backups), {"documents", "generation_budget"})
            self.assertTrue(backups["documents"].is_file())
            self.assertTrue(backups["generation_budget"].is_file())
            self.assertNotEqual(backups["documents"], backups["generation_budget"])

    def test_daily_backup_skips_missing_generation_budget_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "var" / "lib" / "sanaebi" / "runtime"
            data.mkdir(parents=True)
            paths = HostPaths(root=root / "srv" / "sanaebi", data=data)
            sqlite3.connect(paths.database).close()

            backups = create_daily_backups(paths)

            self.assertTrue(backups["documents"].is_file())
            self.assertIsNone(backups["generation_budget"])

    def test_reset_creates_root_document_backup_before_container_and_not_budget_backup(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "var" / "lib" / "sanaebi" / "runtime"
            data.mkdir(parents=True)
            paths = HostPaths(root=root / "srv" / "sanaebi", data=data)
            with sqlite3.connect(paths.database) as connection:
                connection.execute("CREATE TABLE documents (value TEXT)")
                connection.execute("INSERT INTO documents VALUES ('before reset')")
            sqlite3.connect(paths.generation_budget_database).close()
            release_id = "a" * 40 + "-12345"
            release_dir = paths.root / "releases" / release_id
            release_dir.mkdir(parents=True)
            image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
            (release_dir / "release.json").write_text(
                json.dumps({"release_id": release_id, "image": image}),
                encoding="utf-8",
            )
            (paths.root / "current").symlink_to(f"releases/{release_id}")
            paths.baseline.parent.mkdir(parents=True)
            paths.baseline.write_text('{"id":"baseline"}\n', encoding="utf-8")
            seen = {}

            def runner(_command, **_kwargs):
                seen["files"] = list((paths.backups / "pre-reset").glob("*.sqlite3"))
                return SimpleNamespace(returncode=0)

            reset_backup = reset_demo_documents_with_backup(paths, runner=runner)

            self.assertEqual(reset_backup.parent, paths.backups / "pre-reset")
            self.assertEqual(seen["files"], [reset_backup])
            with sqlite3.connect(reset_backup) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM documents").fetchone()[0],
                    "before reset",
                )
            self.assertFalse(
                (paths.backups / "pre-reset" / "generation_budget").exists()
            )

    def test_reset_uses_pinned_image_without_model_or_secret_mounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = HostPaths(
                root=root / "srv" / "sanaebi",
                data=root / "var" / "lib" / "sanaebi" / "runtime",
                config=root / "etc" / "sanaebi",
                operation_lock=root / "run" / "operation.lock",
            )
            release_id = "a" * 40 + "-12345"
            release_dir = paths.root / "releases" / release_id
            release_dir.mkdir(parents=True)
            image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
            (release_dir / "release.json").write_text(
                json.dumps({"release_id": release_id, "image": image}),
                encoding="utf-8",
            )
            paths.root.mkdir(parents=True, exist_ok=True)
            (paths.root / "current").symlink_to(f"releases/{release_id}")
            paths.baseline.parent.mkdir(parents=True)
            paths.baseline.write_text('{"id":"baseline"}\n', encoding="utf-8")
            paths.database.parent.mkdir(parents=True, exist_ok=True)
            sqlite3.connect(paths.database).close()
            self.assertFalse(paths.baseline.is_relative_to(paths.data))
            self.assertFalse(paths.backups.is_relative_to(paths.data))
            captured = {}

            def runner(command, **kwargs):
                captured["command"] = command
                captured.update(kwargs)
                return SimpleNamespace(returncode=0)

            with patch.dict(os.environ, {"HF_TOKEN": "test-secret", "PATH": "/bin"}):
                reset_demo_documents(paths, runner=runner)

            command = captured["command"]
            self.assertEqual(command[command.index("--network") + 1], "none")
            self.assertIn(image, command)
            self.assertIn(f"type=bind,src={paths.data},dst=/data", command)
            self.assertIn(
                f"type=bind,src={paths.baseline},dst=/app/data/company-knowledge/documents.jsonl,readonly",
                command,
            )
            self.assertFalse(any("/models" in value for value in command))
            self.assertNotIn("--env-file", command)
            self.assertNotIn("HF_TOKEN", captured["env"])
            self.assertNotIn("test-secret", repr(captured))

    def test_reset_rejects_untrusted_active_release_pointer_before_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pointer = root / "current"
            pointer.symlink_to("../../etc")

            with self.assertRaises(MaintenanceError):
                reset_demo_documents(
                    HostPaths(root=root), runner=lambda *_args, **_kwargs: self.fail()
                )


class HostPathTests(unittest.TestCase):
    def test_path_chain_rejects_symlink_and_file_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent"
            parent.write_text("not a directory", encoding="utf-8")

            with self.assertRaises(DeploymentError):
                _check_path_chain(parent / "child")

            symlink = root / "link"
            symlink.symlink_to(root, target_is_directory=True)
            with self.assertRaises(DeploymentError):
                _check_path_chain(symlink / "child")

    def test_release_pointer_rejects_unexpected_subdirectory(self):
        with tempfile.TemporaryDirectory() as directory:
            pointer = Path(directory) / "current"
            pointer.symlink_to("releases/../etc")

            with self.assertRaises(DeploymentError):
                _pointer_target(pointer, "releases/")

    def test_atomic_symlink_can_remove_a_missing_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            pointer = Path(directory) / "current"

            _atomic_symlink(pointer, None)

            self.assertFalse(pointer.exists())
            self.assertFalse(pointer.is_symlink())

    def test_failed_first_deployment_stops_candidate_and_clears_pointers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "srv" / "sanaebi"
            root.mkdir(parents=True)
            models = root / "models"
            models.mkdir()
            new_id = "b" * 40 + "-12345"
            (root / "current").symlink_to(f"releases/{new_id}")
            (models / "current").symlink_to("9" * 32 + "/" + "8" * 40)
            (root / "maintenance").write_text("deployment\n", encoding="ascii")
            calls = []

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                output = "container-id\n" if command[:2] == ["docker", "ps"] else ""
                return SimpleNamespace(returncode=0, stdout=output, stderr="")

            engine = DeploymentEngine(
                HostPaths(root=root),
                runner=runner,
                sleep=lambda _seconds: None,
                uid=0,
            )
            engine._active_journal = {"release_id": new_id}

            recovered = engine._rollback(
                old_release=None,
                old_current=None,
                old_previous=None,
                old_model=None,
                release_id=new_id,
            )

            self.assertTrue(recovered)
            self.assertFalse((root / "current").is_symlink())
            self.assertFalse((models / "current").is_symlink())
            self.assertFalse((root / "maintenance").exists())
            self.assertEqual(
                calls[0][0],
                ["docker", "ps", "--quiet", "--filter", "name=^/sanaebi-api$"],
            )
            self.assertEqual(
                calls[1][0], ["docker", "stop", "--time", "240", "sanaebi-api"]
            )
            journal = json.loads((root / "deployment-journal.json").read_text())
            self.assertEqual(journal["phase"], "rolled_back")

    def test_failed_update_restores_release_model_and_web_pointers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "srv" / "sanaebi"
            models = root / "models"
            models.mkdir(parents=True)
            new_id = "b" * 40 + "-12345"
            old_id = "a" * 40 + "-111"
            prior_id = "c" * 40 + "-222"
            old_model = "9" * 32 + "/" + "8" * 40
            new_model = "7" * 32 + "/" + "6" * 40
            (root / "current").symlink_to(f"releases/{new_id}")
            (root / "previous").symlink_to(f"releases/{old_id}")
            (models / "current").symlink_to(new_model)
            (root / "maintenance").write_text("deployment\n", encoding="ascii")
            calls = []

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            class ReadyResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            old_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "d" * 64
            engine = DeploymentEngine(
                HostPaths(root=root),
                runner=runner,
                urlopen=lambda *_args, **_kwargs: ReadyResponse(),
                sleep=lambda _seconds: None,
                uid=0,
            )
            engine._active_journal = {"release_id": new_id}

            recovered = engine._rollback(
                old_release=(old_id, old_image),
                old_current=f"releases/{old_id}",
                old_previous=f"releases/{prior_id}",
                old_model=old_model,
                release_id=new_id,
            )

            self.assertTrue(recovered)
            self.assertEqual(os.readlink(root / "current"), f"releases/{old_id}")
            self.assertEqual(os.readlink(root / "previous"), f"releases/{prior_id}")
            self.assertEqual(os.readlink(models / "current"), old_model)
            self.assertFalse((root / "maintenance").exists())
            compose_call, compose_kwargs = calls[0]
            self.assertEqual(compose_call[:2], ["docker", "compose"])
            self.assertEqual(compose_kwargs["env"]["SANAEBI_IMAGE"], old_image)

    def test_sigterm_during_api_switch_rolls_back_before_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "srv" / "sanaebi"
            models = root / "models"
            models.mkdir(parents=True)
            new_id = "b" * 40 + "-12345"
            old_id = "a" * 40 + "-111"
            model_id = "9" * 32
            new_revision = "8" * 40
            old_revision = "7" * 40
            old_model = f"{model_id}/{old_revision}"
            new_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
            old_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "d" * 64
            (root / "current").symlink_to(f"releases/{old_id}")
            (models / "current").symlink_to(old_model)
            release = Release(
                release_id=new_id,
                image=new_image,
                web_archive="web.tar.gz",
                web_sha256="1" * 64,
                model_manifest="model-release.json",
                model_manifest_sha256="2" * 64,
            )
            inputs = ReleaseInputs(
                release=release,
                model_id=model_id,
                model_revision=new_revision,
                manifest_raw=b"{}",
            )

            def runner(_command, **_kwargs):
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            journal_before_model_download = {}

            def download_model(*_args):
                journal_before_model_download.update(
                    json.loads((root / "deployment-journal.json").read_text())
                )
                return models

            engine = DeploymentEngine(
                HostPaths(
                    root=root,
                    data=root.parent.parent / "var" / "lib" / "sanaebi" / "runtime",
                    config=root / "etc",
                    operation_lock=root / "run" / "operation.lock",
                ),
                runner=runner,
                sleep=lambda _seconds: None,
                uid=0,
            )
            with (
                patch(
                    "scripts.deploy_release.load_release_inputs",
                    return_value=(inputs, {}),
                ),
                patch.object(engine, "_require_root_and_trusted_inputs"),
                patch.object(engine, "_check_no_incomplete_journal"),
                patch.object(engine, "_copy_incoming_to_stage", return_value=root),
                patch.object(
                    engine, "_active_release", return_value=(old_id, old_image)
                ),
                patch.object(engine, "_download_model", side_effect=download_model),
                patch.object(
                    engine, "_initialize_database_if_missing", return_value=False
                ),
                patch.object(engine, "_preflight_candidate"),
                patch.object(engine, "_publish_static_assets"),
                patch.object(engine, "_wait_ready"),
            ):

                def compose(image, *arguments, **_kwargs):
                    if image == new_image and arguments[0] == "up":
                        signal.raise_signal(signal.SIGTERM)

                previous_handler = _term_as_interrupt()
                try:
                    with (
                        patch.object(engine, "_compose", side_effect=compose),
                        self.assertRaises(KeyboardInterrupt),
                    ):
                        engine.deploy(new_id)
                finally:
                    signal.signal(signal.SIGTERM, previous_handler)

            self.assertEqual(os.readlink(root / "current"), f"releases/{old_id}")
            self.assertEqual(os.readlink(models / "current"), old_model)
            self.assertFalse((root / "maintenance").exists())
            journal = json.loads((root / "deployment-journal.json").read_text())
            self.assertEqual(journal["phase"], "rolled_back")
            self.assertEqual(journal["old_current_target"], f"releases/{old_id}")
            self.assertIsNone(journal["old_previous_target"])
            self.assertEqual(journal["old_model_target"], old_model)
            self.assertEqual(journal["candidate_image"], new_image)
            self.assertEqual(
                journal_before_model_download["old_current_target"],
                f"releases/{old_id}",
            )
            self.assertEqual(
                journal_before_model_download["candidate_image"], new_image
            )


class InterruptedDeploymentRecoveryTests(unittest.TestCase):
    def _make_release(self, root, release_id, image):
        directory = root / "releases" / release_id
        directory.mkdir(parents=True)
        (directory / "release.json").write_text(
            json.dumps({"release_id": release_id, "image": image}),
            encoding="utf-8",
        )

    def _make_model(self, root, target):
        directory = root / "models" / target
        directory.mkdir(parents=True)
        for name in (
            "config.json",
            "metadata.json",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
        ):
            (directory / name).write_bytes(b"verified model artifact")

    def _engine(self, root, runner):
        paths = HostPaths(
            root=root / "srv" / "sanaebi",
            data=root / "var" / "lib" / "sanaebi" / "runtime",
            config=root / "etc" / "sanaebi",
            operation_lock=root / "run" / "operation.lock",
        )
        paths.root.mkdir(parents=True)
        paths.data.mkdir(parents=True)
        paths.config.mkdir(parents=True)
        engine = DeploymentEngine(paths, runner=runner, uid=os.geteuid())
        return paths, engine

    def _journal(
        self,
        engine,
        *,
        release_id,
        phase,
        candidate_image,
        candidate_model_id,
        candidate_model_revision,
        old_current_target,
        old_previous_target,
        old_model_target,
        old_release_image,
    ):
        engine._atomic_write_json(
            engine.paths.root / "deployment-journal.json",
            {
                "schema_version": 1,
                "release_id": release_id,
                "phase": phase,
                "image": candidate_image,
                "candidate_image": candidate_image,
                "candidate_preflight_container": f"sanaebi-preflight-{release_id}",
                "candidate_preflight_data": f".preflight-{release_id}",
                "candidate_model_id": candidate_model_id,
                "candidate_model_revision": candidate_model_revision,
                "old_current_target": old_current_target,
                "old_previous_target": old_previous_target,
                "old_model_target": old_model_target,
                "old_release_image": old_release_image,
            },
        )

    def test_root_recovery_restores_prior_pointers_and_api_without_touching_database(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_id = "b" * 40 + "-12345"
            old_id = "a" * 40 + "-111"
            prior_id = "c" * 40 + "-222"
            candidate_model_id, candidate_revision = "7" * 32, "6" * 40
            old_model_id, old_revision = "9" * 32, "8" * 40
            candidate_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
            old_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "d" * 64
            prior_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "e" * 64
            calls = []
            compose_images = []

            def runner(command, **kwargs):
                calls.append(command)
                compose_images.append(kwargs.get("env", {}).get("SANAEBI_IMAGE"))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            paths, engine = self._engine(root, runner)
            self._make_release(paths.root, old_id, old_image)
            self._make_release(paths.root, prior_id, prior_image)
            self._make_release(paths.root, candidate_id, candidate_image)
            old_model = f"{old_model_id}/{old_revision}"
            candidate_model = f"{candidate_model_id}/{candidate_revision}"
            self._make_model(paths.root, old_model)
            self._make_model(paths.root, candidate_model)
            (paths.root / "current").symlink_to(f"releases/{candidate_id}")
            (paths.root / "previous").symlink_to(f"releases/{old_id}")
            (paths.root / "models" / "current").symlink_to(candidate_model)
            (paths.root / "maintenance").write_text("deployment\n", encoding="ascii")
            with sqlite3.connect(paths.database) as connection:
                connection.execute("CREATE TABLE records(value TEXT)")
                connection.execute("INSERT INTO records VALUES ('preserve user edits')")
            self._journal(
                engine,
                release_id=candidate_id,
                phase="new_api_started",
                candidate_image=candidate_image,
                candidate_model_id=candidate_model_id,
                candidate_model_revision=candidate_revision,
                old_current_target=f"releases/{old_id}",
                old_previous_target=f"releases/{prior_id}",
                old_model_target=old_model,
                old_release_image=old_image,
            )

            with (
                patch.object(engine, "_require_recovery_inputs"),
                patch.object(engine, "_wait_ready") as wait_ready,
            ):
                self.assertEqual(engine.recover(), "rolled_back")

            self.assertEqual(os.readlink(paths.root / "current"), f"releases/{old_id}")
            self.assertEqual(
                os.readlink(paths.root / "previous"), f"releases/{prior_id}"
            )
            self.assertEqual(os.readlink(paths.root / "models" / "current"), old_model)
            self.assertFalse((paths.root / "maintenance").exists())
            self.assertTrue(
                any(command[:2] == ["docker", "compose"] for command in calls)
            )
            self.assertIn(old_image, compose_images)
            wait_ready.assert_called_once_with("http://127.0.0.1:18000/health/ready")
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM records").fetchone()[0],
                    "preserve user edits",
                )
            journal = json.loads((paths.root / "deployment-journal.json").read_text())
            self.assertEqual(journal["phase"], "rolled_back")
            self.assertFalse(journal["database_restored"])

    def test_root_recovery_stops_failed_first_deploy_and_removes_candidate_pointers(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_id = "b" * 40 + "-12345"
            candidate_model_id, candidate_revision = "7" * 32, "6" * 40
            candidate_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64

            def runner(command, **_kwargs):
                if command[:3] == ["docker", "ps", "--all"]:
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                if command[:2] == ["docker", "ps"]:
                    return SimpleNamespace(
                        returncode=0, stdout="candidate-id\n", stderr=""
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            paths, engine = self._engine(root, runner)
            self._make_release(paths.root, candidate_id, candidate_image)
            candidate_model = f"{candidate_model_id}/{candidate_revision}"
            self._make_model(paths.root, candidate_model)
            (paths.root / "current").symlink_to(f"releases/{candidate_id}")
            (paths.root / "models" / "current").symlink_to(candidate_model)
            (paths.root / "maintenance").write_text("deployment\n", encoding="ascii")
            self._journal(
                engine,
                release_id=candidate_id,
                phase="new_api_started",
                candidate_image=candidate_image,
                candidate_model_id=candidate_model_id,
                candidate_model_revision=candidate_revision,
                old_current_target=None,
                old_previous_target=None,
                old_model_target=None,
                old_release_image=None,
            )

            with patch.object(engine, "_require_recovery_inputs"):
                self.assertEqual(engine.recover(), "rolled_back")

            self.assertFalse((paths.root / "current").exists())
            self.assertFalse((paths.root / "models" / "current").exists())
            self.assertFalse((paths.root / "maintenance").exists())

    def test_recovery_before_maintenance_marks_journal_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_id = "b" * 40 + "-12345"
            candidate_model_id, candidate_revision = "7" * 32, "6" * 40
            candidate_image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            paths, engine = self._engine(root, runner)
            self._journal(
                engine,
                release_id=candidate_id,
                phase="model_ready",
                candidate_image=candidate_image,
                candidate_model_id=candidate_model_id,
                candidate_model_revision=candidate_revision,
                old_current_target=None,
                old_previous_target=None,
                old_model_target=None,
                old_release_image=None,
            )

            with patch.object(engine, "_require_recovery_inputs"):
                self.assertEqual(engine.recover(), "rolled_back")

            self.assertFalse((paths.root / "maintenance").exists())
            self.assertFalse(
                any(command[:2] == ["docker", "compose"] for command in calls)
            )

    def test_recovery_requires_root(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = HostPaths(root=Path(directory) / "srv" / "sanaebi")
            engine = DeploymentEngine(paths, uid=1001)

            with self.assertRaisesRegex(DeploymentError, "must run as root"):
                engine.recover()


if __name__ == "__main__":
    unittest.main()
