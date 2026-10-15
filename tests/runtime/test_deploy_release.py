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
    load_release_inputs,
    parse_release_manifest,
    safe_extract_web_archive,
)
from scripts.package_release import package as package_release
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

    def test_schema_v1_remains_full_only_without_retrieval_descriptor(self):
        raw, _ = self.manifest()

        release = parse_release_manifest(raw, "a" * 40 + "-12345")

        self.assertEqual(release.schema_version, 1)
        self.assertIsNone(release.retrieval_manifest)
        self.assertIsNone(release.retrieval_manifest_sha256)

    def test_schema_v2_accepts_an_optional_retrieval_descriptor_pair(self):
        raw, files = self.manifest(schema_version=2)

        release_without_rag = parse_release_manifest(raw, "a" * 40 + "-12345")
        self.assertIsNone(release_without_rag.retrieval_manifest)

        retrieval_manifest = b'{"schema_version":1}'
        files["retrieval-release.json"] = retrieval_manifest
        value = json.loads(raw)
        value["retrieval_manifest"] = "retrieval-release.json"
        value["retrieval_manifest_sha256"] = hashlib.sha256(
            retrieval_manifest
        ).hexdigest()
        raw_with_rag = json.dumps(value).encode()

        release_with_rag = parse_release_manifest(raw_with_rag, "a" * 40 + "-12345")
        self.assertEqual(release_with_rag.schema_version, 2)
        self.assertEqual(release_with_rag.retrieval_manifest, "retrieval-release.json")
        release_with_rag.verify_payload_hashes(files)

    def test_schema_v2_rejects_a_partial_retrieval_descriptor(self):
        raw, _ = self.manifest(
            schema_version=2,
            retrieval_manifest="retrieval-release.json",
        )

        with self.assertRaises(DeploymentError):
            parse_release_manifest(raw, "a" * 40 + "-12345")

    def test_load_release_inputs_hashes_and_parses_retrieval_descriptor(self):
        release_id = "a" * 40 + "-12345"
        with tempfile.TemporaryDirectory() as directory:
            incoming = Path(directory) / "incoming"
            release_dir = incoming / release_id
            release_dir.mkdir(parents=True)
            web = b"web archive"
            model = json.dumps(
                {"schema_version": 1, "model_id": "1" * 32, "revision": "2" * 40}
            ).encode()
            retrieval = (
                Path(__file__).resolve().parents[2]
                / "deployment/retrieval-release.json"
            ).read_bytes()
            (release_dir / "web.tar.gz").write_bytes(web)
            (release_dir / "model-release.json").write_bytes(model)
            (release_dir / "retrieval-release.json").write_bytes(retrieval)
            release_json = {
                "schema_version": 2,
                "release_id": release_id,
                "image": "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64,
                "web_archive": "web.tar.gz",
                "web_sha256": hashlib.sha256(web).hexdigest(),
                "model_manifest": "model-release.json",
                "model_manifest_sha256": hashlib.sha256(model).hexdigest(),
                "retrieval_manifest": "retrieval-release.json",
                "retrieval_manifest_sha256": hashlib.sha256(retrieval).hexdigest(),
            }
            (release_dir / "release.json").write_text(json.dumps(release_json))

            inputs, payload = load_release_inputs(incoming, release_id)

            self.assertEqual(inputs.release.schema_version, 2)
            self.assertEqual(
                inputs.retrieval_release.model.model_id,
                "nlpai-lab/KURE-v1",
            )
            self.assertEqual(
                inputs.retrieval_release.model.splitter.revision,
                "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
            )
            self.assertEqual(payload["retrieval-release.json"], retrieval)

    def test_release_packager_publishes_hashed_v2_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            release_dir = Path(directory)
            (release_dir / "web.tar.gz").write_bytes(b"web")

            manifest = package_release(
                release_dir,
                "a" * 40,
                "12345",
                "sha256:" + "b" * 64,
            )

            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["retrieval_manifest"], "retrieval-release.json")
            self.assertEqual(
                manifest["retrieval_manifest_sha256"],
                hashlib.sha256(
                    (release_dir / "retrieval-release.json").read_bytes()
                ).hexdigest(),
            )

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
                json.dumps(
                    {"schema_version": 1, "release_id": release_id, "image": image}
                ),
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
    def _candidate_engine(
        self, root: Path, *, descriptor_mode: str | None, configured_mode: str | None
    ):
        release_id = "a" * 40 + "-12345"
        release_dir = root / "releases" / release_id
        release_dir.mkdir(parents=True)
        image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
        release = {
            "schema_version": 2,
            "release_id": release_id,
            "image": image,
            "web_archive": "web.tar.gz",
            "web_sha256": "1" * 64,
            "model_manifest": "model-release.json",
            "model_manifest_sha256": "2" * 64,
        }
        if descriptor_mode is not None:
            retrieval = json.loads(
                (
                    Path(__file__).resolve().parents[2]
                    / "deployment/retrieval-release.json"
                ).read_text(encoding="utf-8")
            )
            retrieval["default_mode"] = descriptor_mode
            retrieval_raw = json.dumps(retrieval).encode()
            (release_dir / "retrieval-release.json").write_bytes(retrieval_raw)
            release["retrieval_manifest"] = "retrieval-release.json"
            release["retrieval_manifest_sha256"] = hashlib.sha256(
                retrieval_raw
            ).hexdigest()
        (release_dir / "release.json").write_text(json.dumps(release))
        config = root / "etc"
        config.mkdir(parents=True)
        env_value = (
            f"SANAEBI_RETRIEVAL_MODE={configured_mode}\n"
            if configured_mode is not None
            else "SANAEBI_PUBLIC_DEMO=1\n"
        )
        (config / "api.env").write_text(env_value, encoding="utf-8")
        return DeploymentEngine(HostPaths(root=root, config=config)), release_id

    def test_candidate_mode_uses_new_descriptor_default_when_unset(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, release_id = self._candidate_engine(
                Path(directory), descriptor_mode="rag", configured_mode=None
            )
            bundle = engine.paths.retrieval_baselines / "schema-v1" / "bundle.sqlite3"
            with patch.object(
                engine,
                "_binding_for_release",
                return_value={"bundle_path": str(bundle)},
            ):
                mode, overrides, _ = engine._runtime_overrides(release_id)

        self.assertEqual(mode, "rag")
        self.assertEqual(overrides["SANAEBI_RETRIEVAL_MODE"], "rag")
        self.assertEqual(
            overrides["SANAEBI_RETRIEVAL_BUNDLE_CONTAINER_PATH"],
            "/retrieval-baselines/schema-v1/bundle.sqlite3",
        )
        self.assertEqual(
            overrides["SANAEBI_EMBEDDING_PATH"],
            "/models/embeddings/nlpai-lab--KURE-v1/8b418a58414668e75532ed045c22d9ca018ae2b2",
        )

    def test_previous_tiny_retrieval_release_keeps_its_embedding_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, release_id = self._candidate_engine(
                root, descriptor_mode="rag", configured_mode=None
            )
            release_dir = root / "releases" / release_id
            legacy_descriptor = (
                Path(__file__).resolve().parent
                / "fixtures/retrieval-release-tiny-v1.json"
            ).read_bytes()
            (release_dir / "retrieval-release.json").write_bytes(legacy_descriptor)
            release_path = release_dir / "release.json"
            release_value = json.loads(release_path.read_text(encoding="utf-8"))
            release_value["retrieval_manifest_sha256"] = hashlib.sha256(
                legacy_descriptor
            ).hexdigest()
            release_path.write_text(json.dumps(release_value), encoding="utf-8")
            bundle = root / "retrieval-baselines" / "schema-v1" / "bundle.sqlite3"
            with patch.object(
                engine,
                "_binding_for_release",
                return_value={"bundle_path": bundle},
            ):
                mode, overrides, _ = engine._runtime_overrides(release_id)

        self.assertEqual(mode, "rag")
        self.assertEqual(
            overrides["SANAEBI_EMBEDDING_PATH"],
            "/models/embeddings/exp-models--dragonkue-KoEn-E5-Tiny/292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
        )

    def test_candidate_rag_api_receives_host_source_and_bundle_mounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = HostPaths(root=root / "srv", data=root / "data")
            paths.data.mkdir(parents=True)
            model = root / "model"
            model.mkdir()
            bundle = paths.retrieval_baselines / "bundle.sqlite3"
            release_id = "c" * 40 + "-12345"
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            engine = DeploymentEngine(paths, runner=runner, uid=os.geteuid())
            with (
                patch("scripts.deploy_release.os.chown"),
                patch.object(engine, "_preflight_candidate_index"),
                patch.object(engine, "_wait_ready"),
            ):
                engine._preflight_candidate(
                    "candidate-image",
                    model,
                    release_id,
                    retrieval_binding={
                        "bundle_path": bundle,
                        "embedding_path": model,
                    },
                )

        api_start = calls[0]
        self.assertIn(
            "SANAEBI_RETRIEVAL_BASELINE=/retrieval-baseline/baseline.sqlite3", api_start
        )
        self.assertIn(
            "SANAEBI_RETRIEVAL_SOURCE=/retrieval-source/documents.jsonl", api_start
        )
        self.assertIn(
            f"type=bind,src={bundle},dst=/retrieval-baseline/baseline.sqlite3,readonly",
            api_start,
        )
        self.assertIn(
            f"type=bind,src={paths.baseline},dst=/retrieval-source/documents.jsonl,readonly",
            api_start,
        )

    def test_full_runtime_mount_directory_exists_before_compose_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = HostPaths(root=root / "srv", data=root / "data")
            paths.data.mkdir(parents=True)
            paths.database.write_bytes(b"existing database")
            engine = DeploymentEngine(paths, uid=os.geteuid())
            with (
                patch("scripts.deploy_release.os.chown"),
                patch.object(engine, "_copy_baseline_from_image"),
            ):
                initialized = engine._initialize_database_if_missing("legacy-image")
                self.assertTrue(paths.retrieval_baselines.is_dir())

        self.assertFalse(initialized)

    def test_legacy_descriptor_default_remains_full_when_unset(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, release_id = self._candidate_engine(
                Path(directory), descriptor_mode="full", configured_mode=None
            )
            mode, overrides, binding = engine._runtime_overrides(release_id)

        self.assertEqual(mode, "full")
        self.assertEqual(overrides["SANAEBI_RETRIEVAL_MODE"], "full")
        self.assertIsNone(binding)

    def test_explicit_full_mode_overrides_candidate_descriptor_default(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, release_id = self._candidate_engine(
                Path(directory), descriptor_mode="rag", configured_mode="full"
            )
            mode, overrides, binding = engine._runtime_overrides(release_id)

        self.assertEqual(mode, "full")
        self.assertEqual(overrides["SANAEBI_RETRIEVAL_MODE"], "full")
        self.assertIsNone(binding)

    def test_legacy_descriptorless_release_keeps_full_default(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, release_id = self._candidate_engine(
                Path(directory), descriptor_mode=None, configured_mode=None
            )
            mode, overrides, binding = engine._runtime_overrides(release_id)

        self.assertEqual(mode, "full")
        self.assertEqual(overrides["SANAEBI_RETRIEVAL_MODE"], "full")
        self.assertIsNone(binding)

    def test_previous_runtime_mode_comes_from_running_api_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "srv" / "sanaebi"
            config = Path(directory) / "etc" / "sanaebi"
            config.mkdir(parents=True)
            (config / "api.env").write_text(
                "SANAEBI_RETRIEVAL_MODE=rag\n", encoding="utf-8"
            )

            def runner(command, **_kwargs):
                self.assertEqual(command[1:3], ["inspect", "--format"])
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        ["SANAEBI_RETRIEVAL_MODE=full", "SANAEBI_PUBLIC_DEMO=1"]
                    ),
                    stderr="",
                )

            engine = DeploymentEngine(
                HostPaths(root=root, config=config), runner=runner
            )

            self.assertEqual(engine._active_api_retrieval_mode(), "full")

    def test_previous_runtime_without_mode_environment_is_discovered_as_full(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "srv" / "sanaebi"
            config = Path(directory) / "etc" / "sanaebi"
            config.mkdir(parents=True)

            def runner(_command, **_kwargs):
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(["SANAEBI_PUBLIC_DEMO=1"]),
                    stderr="",
                )

            engine = DeploymentEngine(
                HostPaths(root=root, config=config), runner=runner
            )

            self.assertEqual(engine._active_api_retrieval_mode(), "full")

    def test_force_mode_reconstructs_prior_mode_after_env_file_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "srv" / "sanaebi"
            config = Path(directory) / "etc" / "sanaebi"
            release_id = "a" * 40 + "-12345"
            release_dir = root / "releases" / release_id
            release_dir.mkdir(parents=True)
            config.mkdir(parents=True)
            (config / "api.env").write_text(
                "SANAEBI_RETRIEVAL_MODE=rag\n", encoding="utf-8"
            )
            retrieval = (
                Path(__file__).resolve().parents[2]
                / "deployment/retrieval-release.json"
            ).read_bytes()
            (release_dir / "retrieval-release.json").write_bytes(retrieval)
            (release_dir / "release.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "release_id": release_id,
                        "image": "ghcr.io/kant-2nd-project/sanaebi-api@sha256:"
                        + "b" * 64,
                        "web_archive": "web.tar.gz",
                        "web_sha256": "1" * 64,
                        "model_manifest": "model-release.json",
                        "model_manifest_sha256": "2" * 64,
                        "retrieval_manifest": "retrieval-release.json",
                        "retrieval_manifest_sha256": hashlib.sha256(
                            retrieval
                        ).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            engine = DeploymentEngine(HostPaths(root=root, config=config))

            mode, overrides, binding = engine._runtime_overrides(
                release_id, force_mode="full"
            )

            self.assertEqual(mode, "full")
            self.assertEqual(overrides["SANAEBI_RETRIEVAL_MODE"], "full")
            self.assertIsNone(binding)

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
                [
                    "docker",
                    "ps",
                    "--quiet",
                    "--filter",
                    "name=^/sanaebi-retrieval-indexer$",
                ],
            )
            self.assertEqual(
                calls[1][0],
                [
                    "docker",
                    "stop",
                    "--time",
                    "240",
                    "sanaebi-retrieval-indexer",
                ],
            )
            self.assertIn(
                ["docker", "stop", "--time", "240", "sanaebi-api"],
                [call[0] for call in calls],
            )
            journal = json.loads((root / "deployment-journal.json").read_text())
            self.assertEqual(journal["phase"], "rolled_back")

    def test_candidate_index_upgrades_only_the_copied_legacy_database(self):
        from app.documents.context import DocumentContextProvider
        from app.documents.repository import SCHEMA_VERSION, DocumentRepository

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.sqlite3"
            DocumentRepository(live).initialize()
            with sqlite3.connect(live) as connection:
                connection.execute("DROP TABLE document_maintenance_state")
                connection.execute("PRAGMA user_version = 2")
            original = live.read_bytes()
            data = root / "candidate"
            data.mkdir()
            candidate = data / "documents.sqlite3"
            snapshot_sqlite_database(live, candidate)
            phases = []

            def runner(command, **_kwargs):
                if "-c" in command:
                    phases.append("initialize")
                    with patch.dict(
                        os.environ, {"SANAEBI_DOCUMENT_DB": str(candidate)}
                    ):
                        exec(command[command.index("-c") + 1], {})  # noqa: S102 - execute our emitted migration command
                else:
                    phases.append("index")
                    # The real reader rejects a legacy schema before indexing.
                    DocumentContextProvider(database_path=candidate).snapshot()
                return SimpleNamespace(
                    returncode=0, stdout='{"ready": true, "missing": 0}', stderr=""
                )

            engine = DeploymentEngine(HostPaths(root=root), runner=runner)
            engine._preflight_candidate_index(
                "candidate-image",
                data,
                {"bundle_path": root / "baseline", "embedding_path": root / "model"},
            )
            self.assertEqual(phases, ["initialize", "index"])
            self.assertEqual(live.read_bytes(), original)
            with sqlite3.connect(candidate) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )

    def test_candidate_index_failure_removes_preflight_directory_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "srv" / "sanaebi"
            paths = HostPaths(
                root=root,
                data=Path(directory) / "var/lib/sanaebi/runtime",
                config=Path(directory) / "etc/sanaebi",
                operation_lock=Path(directory) / "run/operation.lock",
            )
            paths.data.mkdir(parents=True)
            release_id = "b" * 40 + "-12345"
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            engine = DeploymentEngine(paths, runner=runner, uid=os.geteuid())
            image = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
            model = root / "embeddings"
            model.mkdir(parents=True)
            binding = {
                "bundle_path": paths.data / "baseline.sqlite3",
                "embedding_path": model,
            }

            with (
                patch("scripts.deploy_release.os.chown"),
                patch.object(
                    engine,
                    "_preflight_candidate_index",
                    side_effect=DeploymentError("index failed"),
                ),
                self.assertRaisesRegex(DeploymentError, "index failed"),
            ):
                engine._preflight_candidate(
                    image,
                    model,
                    release_id,
                    retrieval_binding=binding,
                )

            self.assertFalse((paths.data / f".preflight-{release_id}").exists())
            self.assertTrue(
                any(command[:3] == ["docker", "rm", "--force"] for command in calls)
            )

    def test_first_rag_deploy_copies_host_baseline_before_preparing_bundle(self):
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
            retrieval_raw = (
                Path(__file__).resolve().parents[2]
                / "deployment/retrieval-release.json"
            ).read_bytes()
            from scripts.deployment_embedding import parse_manifest

            retrieval = parse_manifest(retrieval_raw)
            release = Release(
                release_id=new_id,
                image=new_image,
                web_archive="web.tar.gz",
                web_sha256="1" * 64,
                model_manifest="model-release.json",
                model_manifest_sha256="2" * 64,
                schema_version=2,
                retrieval_manifest="retrieval-release.json",
                retrieval_manifest_sha256=hashlib.sha256(retrieval_raw).hexdigest(),
            )
            inputs = ReleaseInputs(
                release=release,
                model_id=model_id,
                model_revision=new_revision,
                manifest_raw=b"{}",
                retrieval_release=retrieval,
                retrieval_raw=retrieval_raw,
            )
            data = root.parent.parent / "var" / "lib" / "sanaebi" / "runtime"
            paths = HostPaths(
                root=root,
                data=data,
                config=root / "etc",
                operation_lock=root / "run" / "operation.lock",
            )
            call_order = []

            def runner(_command, **_kwargs):
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            class ReadyResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            engine = DeploymentEngine(
                paths,
                runner=runner,
                urlopen=lambda *_args, **_kwargs: ReadyResponse(),
                sleep=lambda _seconds: None,
                uid=0,
            )

            def copy_host_baseline(_image):
                call_order.append("copy-baseline")
                paths.baseline.parent.mkdir(parents=True, exist_ok=True)
                paths.baseline.write_text('{"id":"host-baseline"}\\n')

            def prepare_baseline(_image, _release_id, _retrieval, embedding):
                call_order.append("prepare-retrieval")
                self.assertTrue(paths.baseline.is_file())
                return {
                    "release_id": new_id,
                    "bundle_path": paths.root / "baseline.sqlite3",
                    "embedding_path": embedding,
                }

            def runtime_overrides(release_id, *, prepared=None, force_mode=None):
                if release_id == old_id:
                    self.assertEqual(force_mode, "full")
                    return "full", {"SANAEBI_RETRIEVAL_MODE": "full"}, None
                self.assertIsNotNone(prepared)
                return "rag", {"SANAEBI_RETRIEVAL_MODE": "rag"}, prepared

            def compose(image, *arguments, **_kwargs):
                if (
                    image == new_image
                    and arguments[0] == "up"
                    and arguments[-1] == "api"
                ):
                    signal.raise_signal(signal.SIGTERM)

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
                patch.object(
                    engine, "_active_api_retrieval_mode", return_value="full"
                ) as active_mode,
                patch.object(engine, "_download_model", return_value=models),
                patch.object(engine, "_download_embedding", return_value=models),
                patch.object(
                    engine, "_copy_baseline_from_image", side_effect=copy_host_baseline
                ),
                patch.object(
                    engine, "_prepare_retrieval_baseline", side_effect=prepare_baseline
                ),
                patch.object(
                    engine, "_runtime_overrides", side_effect=runtime_overrides
                ),
                patch.object(
                    engine, "_initialize_database_if_missing", return_value=False
                ),
                patch.object(engine, "_preflight_candidate"),
                patch.object(engine, "_index_current_documents_once"),
                patch.object(engine, "_stop_indexer_if_running"),
                patch.object(engine, "_publish_static_assets"),
                patch.object(engine, "_wait_ready"),
                patch.object(engine, "_compose", side_effect=compose),
            ):
                previous_handler = _term_as_interrupt()
                try:
                    with self.assertRaises(KeyboardInterrupt):
                        engine.deploy(new_id)
                finally:
                    signal.signal(signal.SIGTERM, previous_handler)

            self.assertEqual(call_order[:2], ["copy-baseline", "prepare-retrieval"])
            active_mode.assert_called_once_with()
            journal = json.loads((root / "deployment-journal.json").read_text())
            self.assertEqual(journal["old_retrieval_mode"], "full")

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
                old_runtime_overrides={"SANAEBI_RETRIEVAL_MODE": "full"},
            )

            self.assertTrue(recovered)
            self.assertEqual(os.readlink(root / "current"), f"releases/{old_id}")
            self.assertEqual(os.readlink(root / "previous"), f"releases/{prior_id}")
            self.assertEqual(os.readlink(models / "current"), old_model)
            self.assertFalse((root / "maintenance").exists())
            compose_call, compose_kwargs = next(
                call for call in calls if call[0][:2] == ["docker", "compose"]
            )
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
                patch.object(engine, "_active_api_retrieval_mode", return_value="full"),
                patch.object(
                    engine, "_release_retrieval", return_value=(release, None)
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
            json.dumps(
                {
                    "schema_version": 1,
                    "release_id": release_id,
                    "image": image,
                    "web_archive": "web.tar.gz",
                    "web_sha256": "0" * 64,
                    "model_manifest": "model-release.json",
                    "model_manifest_sha256": "1" * 64,
                }
            ),
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
                "old_retrieval_mode": "full",
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
            (paths.config / "api.env").write_text(
                "SANAEBI_RETRIEVAL_MODE=rag\n", encoding="utf-8"
            )
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
                patch.object(
                    engine, "_runtime_overrides", wraps=engine._runtime_overrides
                ) as runtime_overrides,
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
            runtime_overrides.assert_called_once_with(old_id, force_mode="full")
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
