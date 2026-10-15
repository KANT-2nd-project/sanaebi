"""Reset CLI behavior across full and RAG modes, including lock/recovery paths."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from threading import Event
from unittest.mock import patch

from app.documents.context import DocumentContextProvider
from app.documents.repository import DocumentRepository
from app.retrieval import reset as retrieval_reset
from app.retrieval.baseline import baseline_path, prepare_baseline
from app.retrieval.config import SERVER_SPEC
from scripts import index_documents, reset_demo_documents
from tests.runtime.kure_helpers import KureFakeEmbedder

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _row(body: str = "기준 본문") -> dict[str, object]:
    return {
        "document_id": "reset-entrypoint-001",
        "title": "리셋 진입점 기준",
        "document": body,
        "category": "정책",
        "version": "1.0.0",
        "review_status": "reviewed",
        "source_ids": ["reset-entrypoint-source"],
        "policy_decision_ids": ["reset-entrypoint-policy"],
    }


@contextmanager
def _external_writer_lock(root: Path):
    """Hold the real retrieval lock in another Python process."""
    code = """\
import sys
from app.retrieval.config import SERVER_SPEC
from app.retrieval.sync import writer_lock

with writer_lock(sys.argv[1], spec=SERVER_SPEC):
    print("LOCKED", flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(root)],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def release():
        if process.poll() is None and process.stdin and not process.stdin.closed:
            try:
                process.stdin.write("release\n")
                process.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()

    try:
        ready = process.stdout.readline()
        if ready != "LOCKED\n":
            error = process.stderr.read()
            raise AssertionError(
                f"writer lock process did not become ready: {ready!r} {error}"
            )
        yield release
    finally:
        release()
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise
        error = process.stderr.read()
        if return_code != 0:
            raise AssertionError(f"writer lock process failed: {error}")
        process.stdout.close()
        process.stderr.close()


class ResetEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sanaebi-reset-entrypoints-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.jsonl"
        self.write_source()
        self.database = self.root / "documents.sqlite3"
        self.repository = DocumentRepository(self.database)
        self.repository.initialize()
        self.retrieval_root = self.root / "retrieval"
        self.bundle_root = self.root / "bundles"
        self.bundle = prepare_baseline(
            self.source,
            self.bundle_root,
            KureFakeEmbedder(),
            spec=SERVER_SPEC,
        )

    def write_source(self, body: str = "기준 본문"):
        self.source.write_text(
            json.dumps(_row(body), ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def env(self, *, mode: str, include_bundle: bool = True) -> dict[str, str]:
        result = os.environ.copy()
        for name in (
            "SANAEBI_DOCUMENT_DB",
            "SANAEBI_RETRIEVAL_MODE",
            "SANAEBI_RETRIEVAL_ROOT",
            "SANAEBI_RETRIEVAL_BASELINE",
            "SANAEBI_RETRIEVAL_SOURCE",
        ):
            result.pop(name, None)
        result.update(
            {
                "SANAEBI_DOCUMENT_DB": str(self.database),
                "SANAEBI_RETRIEVAL_MODE": mode,
                "SANAEBI_RETRIEVAL_ROOT": str(self.retrieval_root),
                "SANAEBI_RETRIEVAL_SOURCE": str(self.source),
            }
        )
        if include_bundle:
            result["SANAEBI_RETRIEVAL_BASELINE"] = str(self.bundle)
        return result

    def run_document_cli(
        self,
        *args: str,
        mode: str,
        include_bundle: bool = True,
        include_source: bool = True,
    ):
        command = [
            sys.executable,
            "-m",
            "scripts.reset_demo_documents",
            *args,
        ]
        if include_source:
            command.extend(("--source", str(self.source)))
        command.extend(("--database", str(self.database)))
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=self.env(mode=mode, include_bundle=include_bundle),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def snapshot(self):
        return DocumentContextProvider(database_path=self.database).snapshot()

    def test_rag_cli_resets_documents_and_restores_baseline(self):
        run = self.run_document_cli("--apply", mode="rag", include_source=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["documents_reset"])
        self.assertTrue(report["retrieval_ready"])
        self.assertEqual(self.repository.list()["total"], 1)
        listed = self.repository.list()["items"][0]
        self.assertEqual(
            self.repository.get(listed["id"])["published"]["body"], "기준 본문"
        )

    def test_full_cli_resets_the_selected_source_without_retrieval_state(self):
        run = self.run_document_cli("--apply", mode="full")
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertTrue(report["applied"])
        self.assertEqual(report["status"], "success")
        self.assertEqual(self.repository.list()["total"], 1)

    def test_cli_without_apply_is_a_dry_run_in_rag_mode(self):
        before = self.database.read_bytes()
        run = self.run_document_cli(mode="rag")
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertFalse(report["applied"])
        self.assertEqual(report["status"], "validated")
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(self.repository.list()["total"], 0)

    def test_custom_cli_source_selects_its_derived_default_bundle(self):
        configured_source = self.root / "configured-source.jsonl"
        configured_source.write_text(
            json.dumps(_row("설정된 다른 원본"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        custom_source = self.root / "custom-source.jsonl"
        custom_source.write_text(
            json.dumps(_row("명시한 사용자 원본"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        artifact_root = self.root / "artifacts" / "retrieval-baselines"
        custom_bundle = prepare_baseline(
            custom_source,
            artifact_root,
            KureFakeEmbedder(),
            spec=SERVER_SPEC,
        )
        expected_bundle = baseline_path(custom_source, artifact_root, spec=SERVER_SPEC)
        self.assertEqual(custom_bundle, expected_bundle)

        env = os.environ.copy()
        for name in (
            "SANAEBI_DOCUMENT_DB",
            "SANAEBI_RETRIEVAL_MODE",
            "SANAEBI_RETRIEVAL_ROOT",
            "SANAEBI_RETRIEVAL_BASELINE",
            "SANAEBI_RETRIEVAL_SOURCE",
        ):
            env.pop(name, None)
        env.update(
            {
                "SANAEBI_DOCUMENT_DB": str(self.database),
                "SANAEBI_RETRIEVAL_MODE": "rag",
                "SANAEBI_RETRIEVAL_ROOT": str(self.retrieval_root),
                "SANAEBI_RETRIEVAL_SOURCE": str(configured_source),
            }
        )
        with (
            patch("app.settings.PROJECT_ROOT", self.root),
            patch.dict(os.environ, env, clear=True),
            redirect_stdout(StringIO()) as output,
            redirect_stderr(StringIO()) as error,
        ):
            status = reset_demo_documents.main(
                [
                    "--apply",
                    "--source",
                    str(custom_source),
                    "--database",
                    str(self.database),
                ]
            )

        self.assertEqual(status, 0, error.getvalue())
        self.assertTrue(json.loads(output.getvalue())["retrieval_ready"])
        listed = self.repository.list()["items"][0]
        self.assertEqual(
            self.repository.get(listed["id"])["published"]["body"],
            "명시한 사용자 원본",
        )

    def test_external_writer_lock_failure_leaves_documents_unchanged(self):
        before = self.snapshot().fingerprint

        def short_wait_lock(root, *, spec):
            from app.retrieval.sync import writer_lock

            return writer_lock(root, spec=spec, timeout=0.15)

        with (
            _external_writer_lock(self.retrieval_root),
            patch.dict(os.environ, self.env(mode="rag"), clear=True),
            patch.object(retrieval_reset, "writer_lock", short_wait_lock),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()) as error,
        ):
            status = reset_demo_documents.main(
                [
                    "--apply",
                    "--source",
                    str(self.source),
                    "--database",
                    str(self.database),
                ]
            )

        report = json.loads(error.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(report["documents_reset"])
        self.assertFalse(report["retrieval_ready"])
        self.assertEqual(report["error_type"], "RetrievalWriterBusy")
        self.assertEqual(self.snapshot().fingerprint, before)

    def test_source_changed_while_waiting_for_lock_is_rejected_without_reset(self):
        before = self.snapshot().fingerprint
        waiting = Event()

        def observing_writer_lock(root, *, spec):
            from app.retrieval.sync import writer_lock

            waiting.set()
            return writer_lock(root, spec=spec, timeout=4)

        def run_cli():
            with (
                patch.dict(os.environ, self.env(mode="rag"), clear=True),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()) as error,
            ):
                status = reset_demo_documents.main(
                    [
                        "--apply",
                        "--source",
                        str(self.source),
                        "--database",
                        str(self.database),
                    ]
                )
                return status, error.getvalue()

        with (
            _external_writer_lock(self.retrieval_root) as release_lock,
            patch.object(retrieval_reset, "writer_lock", observing_writer_lock),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(run_cli)
            self.assertTrue(
                waiting.wait(timeout=3), "CLI did not reach the writer lock"
            )
            self.write_source("소스가 락 대기 중 변경됨")
            release_lock()
            status, error = future.result(timeout=6)

        report = json.loads(error)
        self.assertEqual(status, 1)
        self.assertFalse(report["documents_reset"])
        self.assertEqual(report["error_type"], "RetrievalUnavailable")
        self.assertEqual(self.snapshot().fingerprint, before)

    def test_systemd_execstart_resolves_full_and_rag_settings_from_env_file(self):
        uv_bin = shutil.which("uv")
        if uv_bin is None:
            self.skipTest("uv is required to exercise the systemd ExecStart command")

        unit = (
            PROJECT_ROOT / "deployment/systemd/sanaebi-demo-reset.service"
        ).read_text(encoding="utf-8")
        settings_probe = """\
import json
from app.settings import (
    get_document_database_path,
    get_retrieval_baseline,
    get_retrieval_mode,
    get_retrieval_root,
    get_retrieval_source,
)

print(json.dumps({
    "mode": get_retrieval_mode(),
    "database": str(get_document_database_path()),
    "root": str(get_retrieval_root()),
    "source": str(get_retrieval_source()),
    "bundle": str(get_retrieval_baseline()),
}))
"""
        inherited_environment = os.environ.copy()
        for name in (
            "SANAEBI_DOCUMENT_DB",
            "SANAEBI_RETRIEVAL_MODE",
            "SANAEBI_RETRIEVAL_ROOT",
            "SANAEBI_RETRIEVAL_BASELINE",
            "SANAEBI_RETRIEVAL_SOURCE",
        ):
            inherited_environment.pop(name, None)

        for mode in ("full", "rag"):
            database = self.root / f"{mode}.sqlite3"
            repository = DocumentRepository(database)
            repository.initialize()
            retrieval_root = self.root / f"{mode}-retrieval"
            runtime_env = self.root / f"{mode}.env"
            runtime_env.write_text(
                "\n".join(
                    (
                        f"SANAEBI_RETRIEVAL_MODE={mode}",
                        f"SANAEBI_DOCUMENT_DB={database}",
                        f"SANAEBI_RETRIEVAL_ROOT={retrieval_root}",
                        f"SANAEBI_RETRIEVAL_SOURCE={self.source}",
                        f"SANAEBI_RETRIEVAL_BASELINE={self.bundle}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            rendered = (
                unit.replace("@RUN_USER@", "test-user")
                .replace("@PROJECT_ROOT@", str(PROJECT_ROOT))
                .replace("@UV_BIN@", uv_bin)
                .replace("@RUNTIME_ENV@", str(runtime_env))
            )
            for placeholder in (
                "@RUN_USER@",
                "@PROJECT_ROOT@",
                "@UV_BIN@",
                "@RUNTIME_ENV@",
            ):
                self.assertNotIn(placeholder, rendered)
            working_directory = next(
                line.split("=", 1)[1]
                for line in rendered.splitlines()
                if line.startswith("WorkingDirectory=")
            )
            command = shlex.split(
                next(
                    line.split("=", 1)[1]
                    for line in rendered.splitlines()
                    if line.startswith("ExecStart=")
                )
            )
            self.assertEqual(working_directory, str(PROJECT_ROOT))
            self.assertEqual(
                command,
                [
                    uv_bin,
                    "run",
                    "--no-sync",
                    "--env-file",
                    str(runtime_env),
                    "python",
                    "-m",
                    "scripts.reset_demo_documents",
                    "--apply",
                ],
            )

            probe = subprocess.run(
                [
                    uv_bin,
                    "run",
                    "--no-sync",
                    "--env-file",
                    str(runtime_env),
                    "python",
                    "-c",
                    settings_probe,
                ],
                cwd=working_directory,
                env=inherited_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(
                json.loads(probe.stdout),
                {
                    "mode": mode,
                    "database": str(database),
                    "root": str(retrieval_root),
                    "source": str(self.source),
                    "bundle": str(self.bundle),
                },
            )

            run = subprocess.run(
                command,
                cwd=working_directory,
                env=inherited_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(run.stdout)
            if mode == "full":
                self.assertTrue(report["applied"])
                self.assertEqual(report["status"], "success")
            else:
                self.assertTrue(report["documents_reset"])
                self.assertTrue(report["retrieval_ready"])
                self.assertEqual(report["status"], "ready")
            self.assertEqual(repository.list()["total"], 1)
            listed = repository.list()["items"][0]
            self.assertEqual(
                repository.get(listed["id"])["published"]["body"], "기준 본문"
            )

    def test_partial_rag_reset_recovers_without_running_document_reset_again(self):
        env = self.env(mode="rag")
        args = [
            "--apply",
            "--source",
            str(self.source),
            "--database",
            str(self.database),
        ]
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(
                retrieval_reset,
                "restore_baseline",
                side_effect=OSError("injected isolated mapping failure"),
            ),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()) as failure_output,
        ):
            status = reset_demo_documents.main(args)

        failed = json.loads(failure_output.getvalue())
        self.assertEqual(status, 1)
        self.assertTrue(failed["documents_reset"])
        self.assertFalse(failed["retrieval_ready"])
        self.assertEqual(failed["error_type"], "OSError")
        recovery_environment = failed["recovery_environment"]
        self.assertEqual(
            recovery_environment,
            {
                "SANAEBI_DOCUMENT_DB": str(self.database.resolve()),
                "SANAEBI_RETRIEVAL_SOURCE": str(self.source.resolve()),
                "SANAEBI_RETRIEVAL_ROOT": str(self.retrieval_root.resolve()),
                "SANAEBI_RETRIEVAL_BASELINE": str(self.bundle.resolve()),
            },
        )
        saved = self.snapshot()
        version = self.repository.list()["items"][0]["record_version"]
        recovery_env = os.environ.copy()
        for name in (
            "SANAEBI_DOCUMENT_DB",
            "SANAEBI_RETRIEVAL_MODE",
            "SANAEBI_RETRIEVAL_ROOT",
            "SANAEBI_RETRIEVAL_BASELINE",
            "SANAEBI_RETRIEVAL_SOURCE",
        ):
            recovery_env.pop(name, None)
        recovery_env.update(recovery_environment)

        with (
            patch.dict(os.environ, recovery_env, clear=True),
            patch.object(
                retrieval_reset,
                "reset_demo_documents",
                side_effect=AssertionError("recovery must not reset documents"),
            ),
            patch.object(
                index_documents,
                "create_embedder",
                side_effect=AssertionError("baseline recovery must not load a model"),
            ),
            redirect_stdout(StringIO()) as recovery_output,
        ):
            recovery_status = index_documents.main(["--restore-baseline"])

        recovered = json.loads(recovery_output.getvalue())
        self.assertEqual(recovery_status, 0)
        self.assertTrue(recovered["ready"])
        self.assertEqual(self.snapshot(), saved)
        self.assertEqual(self.repository.list()["items"][0]["record_version"], version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
