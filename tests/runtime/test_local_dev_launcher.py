"""The launcher shares dotenv and owns only its child process groups."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.settings import PROJECT_ROOT


@unittest.skipUnless(shutil.which("node"), "Node is required for development launcher")
class DevLauncherTests(unittest.TestCase):
    def test_worker_is_opt_in_for_rag_and_python_shares_dotenv(self):
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                "import {commands} from './scripts/dev_runtime.mjs'; console.log(JSON.stringify([commands('rag'), commands('full'), commands('rag', true), commands('full', true)]));",
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        rag, full, watched_rag, watched_full = json.loads(result.stdout)
        self.assertEqual(len(rag), 2)
        self.assertEqual(len(watched_rag), 3)
        self.assertEqual(watched_full, full)
        self.assertEqual(len(full), 2)
        for command, arguments in (rag[0], watched_rag[2]):
            self.assertEqual(command, "uv")
            self.assertEqual(arguments[:4], ["run", "--locked", "--env-file", ".env"])

    def test_failed_preflight_starts_no_services_and_hides_raw_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "uv"
            executable.write_text(
                '#!/bin/sh\nprintf \'{"ready":false,"errors":["baseline_missing"]}\\n\'\nexit 1\n'
            )
            executable.chmod(0o755)
            result = subprocess.run(
                ["node", "scripts/dev_runtime.mjs"],
                check=False,
                cwd=PROJECT_ROOT,
                env={**os.environ, "PATH": directory + ":" + os.environ["PATH"]},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("setup:local", result.stderr)

    def test_uv_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            envfile = Path(directory) / "test.env"
            envfile.write_text("SANAEBI_TEST_CONFIG_PRIORITY=file\n")
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--locked",
                    "--env-file",
                    str(envfile),
                    "python",
                    "-c",
                    "import os; print(os.environ['SANAEBI_TEST_CONFIG_PRIORITY'])",
                ],
                cwd=PROJECT_ROOT,
                env={**os.environ, "SANAEBI_TEST_CONFIG_PRIORITY": "shell"},
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.stdout.strip(), "shell")

    def test_shutdown_reaps_grandchildren_without_touching_unrelated_process(self):
        self._check_shutdown(child_failure=False)

    def test_child_failure_stops_sibling_groups(self):
        self._check_shutdown(child_failure=True)

    def _check_shutdown(self, *, child_failure):
        import signal
        import sys
        import time

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = f"""#!{sys.executable}
import os, sys, json, signal, time
if 'scripts.local_runtime' in sys.argv:
    print(json.dumps({{"ready": True, "mode": "rag"}})); sys.exit(0)
pid = os.fork()
if pid == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(os.environ['DEV_TEST_PID_FILE'], 'a') as handle:
        handle.write(str(os.getpid()) + '\\n')
if pid != 0 and os.environ.get('DEV_TEST_CHILD_FAIL') == '1' and 'uvicorn' in sys.argv:
    time.sleep(1); sys.exit(9)
while True: time.sleep(1)
"""
            for name in ("uv", "npm"):
                executable = root / name
                executable.write_text(program)
                executable.chmod(0o755)
            pidfile = root / "pids"
            unrelated = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            launcher = subprocess.Popen(
                ["node", "scripts/dev_runtime.mjs"],
                cwd=PROJECT_ROOT,
                env={
                    **os.environ,
                    "PATH": directory + ":" + os.environ["PATH"],
                    "DEV_TEST_PID_FILE": str(pidfile),
                    "DEV_TEST_CHILD_FAIL": "1" if child_failure else "0",
                },
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pids = []
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if pidfile.exists():
                        pids = [int(x) for x in pidfile.read_text().splitlines()]
                        if len(pids) == 2:
                            break
                    time.sleep(0.05)
                self.assertEqual(len(pids), 2)
                if not child_failure:
                    launcher.send_signal(signal.SIGINT)
                self.assertEqual(launcher.wait(timeout=10), 9 if child_failure else 130)
                for pid in pids:
                    status = Path(f"/proc/{pid}/stat")
                    self.assertTrue(
                        not status.exists() or status.read_text().split()[2] == "Z"
                    )
                self.assertIsNone(unrelated.poll())
            finally:
                if launcher.poll() is None:
                    launcher.kill()
                    launcher.wait()
                unrelated.terminate()
                unrelated.wait()
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
