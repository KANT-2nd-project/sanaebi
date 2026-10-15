import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.production_maintenance import (
    HostPaths,
    MaintenanceError,
    _active_retrieval_runtime,
    reset_demo_documents_with_backup,
    restore_retrieval,
)

RELEASE_ID = "a" * 40 + "-12345"
IMAGE = "ghcr.io/kant-2nd-project/sanaebi-api@sha256:" + "b" * 64
MODEL_ID = "exp-models/dragonkue-KoEn-E5-Tiny"
REVISION = "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9"


class RagHostMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.paths = HostPaths(
            root=root / "srv" / "sanaebi",
            data=root / "var/lib/sanaebi/runtime",
            config=root / "etc/sanaebi",
            operation_lock=root / "run/operation.lock",
        )
        self.paths.root.mkdir(parents=True)
        self.paths.data.mkdir(parents=True)
        self.paths.config.mkdir(parents=True)
        self.paths.baseline.parent.mkdir(parents=True)
        self.paths.baseline.write_bytes(b'{"id":"baseline"}\n')
        sqlite3.connect(self.paths.database).close()
        release_dir = self.paths.root / "releases" / RELEASE_ID
        release_dir.mkdir(parents=True)
        retrieval_descriptor = (
            Path(__file__).resolve().parents[2] / "deployment/retrieval-release.json"
        ).read_bytes()
        descriptor = {
            "schema_version": 2,
            "release_id": RELEASE_ID,
            "image": IMAGE,
            "retrieval_manifest": "retrieval-release.json",
            "retrieval_manifest_sha256": hashlib.sha256(
                retrieval_descriptor
            ).hexdigest(),
        }
        (release_dir / "release.json").write_text(
            json.dumps(descriptor), encoding="utf-8"
        )
        (release_dir / "retrieval-release.json").write_bytes(retrieval_descriptor)
        (self.paths.root / "current").symlink_to(f"releases/{RELEASE_ID}")
        self.source_sha256 = hashlib.sha256(
            self.paths.baseline.read_bytes()
        ).hexdigest()
        self.spec_id = "1" * 64
        self.bundle = (
            self.paths.retrieval_baselines
            / "schema-v1"
            / self.spec_id
            / self.source_sha256
            / "baseline.sqlite3"
        )
        self.bundle.parent.mkdir(parents=True)
        self.bundle.write_bytes(b"immutable baseline bundle")
        self.embedding = (
            self.paths.embedding_models
            / "exp-models--dragonkue-KoEn-E5-Tiny"
            / REVISION
        )
        self.embedding.mkdir(parents=True)
        binding = {
            "schema_version": 1,
            "release_id": RELEASE_ID,
            "model_id": MODEL_ID,
            "revision": REVISION,
            "baseline_schema_version": 1,
            "index_schema_version": 1,
            "spec_id": self.spec_id,
            "source_sha256": self.source_sha256,
        }
        self.paths.retrieval_bindings.mkdir(parents=True)
        (self.paths.retrieval_bindings / f"{RELEASE_ID}.json").write_text(
            json.dumps(binding), encoding="utf-8"
        )
        (self.paths.config / "api.env").write_text(
            "SANAEBI_RETRIEVAL_MODE=rag\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_active_retrieval_runtime_uses_descriptor_default_without_env_override(
        self,
    ):
        (self.paths.config / "api.env").write_text(
            "SANAEBI_PUBLIC_DEMO=1\n", encoding="utf-8"
        )

        runtime = _active_retrieval_runtime(self.paths)

        self.assertEqual(runtime["mode"], "rag")

    def test_active_retrieval_runtime_honors_explicit_full_override(self):
        (self.paths.config / "api.env").write_text(
            "SANAEBI_RETRIEVAL_MODE=full\n", encoding="utf-8"
        )

        runtime = _active_retrieval_runtime(self.paths)

        self.assertEqual(runtime["mode"], "full")

    def test_legacy_full_descriptor_remains_full_without_env_override(self):
        release_dir = self.paths.root / "releases" / RELEASE_ID
        descriptor_path = release_dir / "retrieval-release.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        descriptor["default_mode"] = "full"
        raw = json.dumps(descriptor).encode()
        descriptor_path.write_bytes(raw)
        release_path = release_dir / "release.json"
        release = json.loads(release_path.read_text(encoding="utf-8"))
        release["retrieval_manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        release_path.write_text(json.dumps(release), encoding="utf-8")
        (self.paths.config / "api.env").write_text(
            "SANAEBI_PUBLIC_DEMO=1\n", encoding="utf-8"
        )

        runtime = _active_retrieval_runtime(self.paths)

        self.assertEqual(runtime["mode"], "full")

    def runner_with(self, *, check_code=0, reset_code=0, restore_code=0):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            output = ""
            return_code = 0
            if command[:2] == ["docker", "inspect"]:
                output = "true"
            elif command[:2] == ["docker", "ps"]:
                output = "container-id"
            elif command[:2] == ["docker", "stop"]:
                output = "sanaebi-retrieval-indexer"
            elif command[:2] == ["docker", "compose"]:
                output = "started"
            elif command[:2] == ["docker", "run"]:
                command_text = " ".join(command)
                if "scripts.reset_demo_retrieval" in command_text:
                    if "--check" in command:
                        return_code = check_code
                        output = json.dumps(
                            {
                                "status": "ready",
                                "spec_id": self.spec_id,
                                "source_sha256": self.source_sha256,
                            }
                        )
                    else:
                        backup_files = list(
                            (self.paths.backups / "pre-reset").glob("*.sqlite3")
                        )
                        if not backup_files:
                            raise AssertionError("reset ran before database backup")
                        return_code = reset_code
                        output = json.dumps(
                            {
                                "status": "ready",
                                "documents_reset": True,
                                "retrieval_ready": True,
                                "ready": True,
                                "missing": 0,
                            }
                        )
                if "index_documents" in command_text:
                    return_code = restore_code
                    output = json.dumps(
                        {"status": "success", "ready": True, "missing": 0}
                    )
            return SimpleNamespace(returncode=return_code, stdout=output, stderr="")

        return calls, runner

    def test_rag_midnight_reset_preflights_stops_resets_and_resumes_worker(self):
        original_source = self.paths.baseline.read_bytes()
        calls, runner = self.runner_with()

        backup = reset_demo_documents_with_backup(self.paths, runner=runner)

        commands = [command for command, _ in calls]
        check_index = next(
            index
            for index, command in enumerate(commands)
            if "scripts.reset_demo_retrieval" in " ".join(command)
            and "--check" in command
        )
        stop_index = next(
            index
            for index, command in enumerate(commands)
            if command[:2] == ["docker", "stop"]
        )
        reset_index = next(
            index
            for index, command in enumerate(commands)
            if "scripts.reset_demo_retrieval" in " ".join(command)
            and "--check" not in command
        )
        resume_index = next(
            index
            for index, command in enumerate(commands)
            if command[:2] == ["docker", "compose"] and "up" in command
        )
        self.assertLess(check_index, stop_index)
        self.assertLess(stop_index, reset_index)
        self.assertLess(reset_index, resume_index)
        self.assertTrue(backup.is_file())
        self.assertEqual(self.paths.baseline.read_bytes(), original_source)
        for command, kwargs in calls:
            self.assertNotIn("--env-file", command)
            self.assertNotIn("/models/embedding", " ".join(command))
            self.assertNotIn("OPENAI_API_KEY", repr(kwargs.get("env", {})))
            self.assertNotIn("HF_TOKEN", repr(kwargs.get("env", {})))

    def test_failed_rag_reset_preflight_never_stops_worker_or_writes_documents(self):
        original_source = self.paths.baseline.read_bytes()
        calls, runner = self.runner_with(check_code=1)

        with self.assertRaises(MaintenanceError):
            reset_demo_documents_with_backup(self.paths, runner=runner)

        commands = [command for command, _ in calls]
        self.assertFalse(any(command[:2] == ["docker", "stop"] for command in commands))
        self.assertFalse(
            any(
                "scripts.reset_demo_retrieval" in " ".join(command)
                and "--check" not in command
                for command in commands
            )
        )
        self.assertEqual(self.paths.baseline.read_bytes(), original_source)
        self.assertFalse(list((self.paths.backups / "pre-reset").glob("*.sqlite3")))

    def test_failed_midnight_reset_still_restarts_worker(self):
        calls, runner = self.runner_with(reset_code=1)

        with self.assertRaises(MaintenanceError):
            reset_demo_documents_with_backup(self.paths, runner=runner)

        commands = [command for command, _ in calls]
        self.assertTrue(
            any(
                command[:2] == ["docker", "compose"] and "up" in command
                for command in commands
            )
        )
        self.assertEqual(self.paths.baseline.read_bytes(), b'{"id":"baseline"}\n')

    def test_mapping_only_recovery_never_resets_source_or_loads_embedding_model(self):
        source_before = self.paths.baseline.read_bytes()
        database_before = self.paths.database.read_bytes()
        calls, runner = self.runner_with()

        restore_retrieval(self.paths, runner=runner)

        commands = [command for command, _ in calls]
        restore_index = next(
            index
            for index, command in enumerate(commands)
            if "index_documents" in " ".join(command)
        )
        stop_index = next(
            index
            for index, command in enumerate(commands)
            if command[:2] == ["docker", "stop"]
        )
        resume_index = next(
            index
            for index, command in enumerate(commands)
            if command[:2] == ["docker", "compose"] and "up" in command
        )
        self.assertLess(stop_index, restore_index)
        self.assertLess(restore_index, resume_index)
        self.assertIn("--restore-baseline", commands[restore_index])
        self.assertFalse(
            any(
                "scripts.reset_demo_retrieval" in " ".join(command)
                and "--check" not in command
                for command in commands
            )
        )
        self.assertFalse(
            any("/models/embedding" in " ".join(command) for command in commands)
        )
        self.assertEqual(self.paths.baseline.read_bytes(), source_before)
        self.assertEqual(self.paths.database.read_bytes(), database_before)

    def test_failed_mapping_restore_still_restarts_worker(self):
        source_before = self.paths.baseline.read_bytes()
        database_before = self.paths.database.read_bytes()
        calls, runner = self.runner_with(restore_code=1)

        with self.assertRaises(MaintenanceError):
            restore_retrieval(self.paths, runner=runner)

        commands = [command for command, _ in calls]
        self.assertTrue(
            any(
                command[:2] == ["docker", "compose"] and "up" in command
                for command in commands
            )
        )
        self.assertEqual(self.paths.baseline.read_bytes(), source_before)
        self.assertEqual(self.paths.database.read_bytes(), database_before)

    def test_same_model_schema_a_to_b_to_a_keeps_both_host_bundles_selectable(self):
        original_source = self.paths.baseline.read_bytes()
        schema_a = self.bundle
        schema_a_bytes = schema_a.read_bytes()
        release_b = "c" * 40 + "-22222"
        source_sha = self.source_sha256
        spec_id = self.spec_id

        base_descriptor = json.loads(
            (
                self.paths.root / "releases" / RELEASE_ID / "retrieval-release.json"
            ).read_text(encoding="utf-8")
        )
        descriptor_b = {
            **base_descriptor,
            "baseline_schema_version": 2,
            "index_schema_version": 2,
        }
        raw_b = json.dumps(descriptor_b).encode()
        release_dir_b = self.paths.root / "releases" / release_b
        release_dir_b.mkdir(parents=True)
        (release_dir_b / "retrieval-release.json").write_bytes(raw_b)
        (release_dir_b / "release.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "release_id": release_b,
                    "image": IMAGE,
                    "retrieval_manifest": "retrieval-release.json",
                    "retrieval_manifest_sha256": hashlib.sha256(raw_b).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        binding_b = {
            "schema_version": 1,
            "release_id": release_b,
            "model_id": MODEL_ID,
            "revision": REVISION,
            "baseline_schema_version": 2,
            "index_schema_version": 2,
            "spec_id": spec_id,
            "source_sha256": source_sha,
        }
        (self.paths.retrieval_bindings / f"{release_b}.json").write_text(
            json.dumps(binding_b), encoding="utf-8"
        )
        schema_b = (
            self.paths.retrieval_baselines
            / "schema-v2"
            / spec_id
            / source_sha
            / "baseline.sqlite3"
        )
        schema_b.parent.mkdir(parents=True)
        schema_b.write_bytes(b"schema B baseline bundle")

        def activate(release_id):
            (self.paths.root / "current").unlink()
            (self.paths.root / "current").symlink_to(f"releases/{release_id}")
            return _active_retrieval_runtime(self.paths)["bundle"]

        self.assertEqual(activate(RELEASE_ID), schema_a)
        self.assertEqual(activate(release_b), schema_b)
        self.assertEqual(activate(RELEASE_ID), schema_a)
        self.assertEqual(schema_a.read_bytes(), schema_a_bytes)
        self.assertEqual(schema_b.read_bytes(), b"schema B baseline bundle")
        self.assertEqual(self.paths.baseline.read_bytes(), original_source)


if __name__ == "__main__":
    unittest.main()
