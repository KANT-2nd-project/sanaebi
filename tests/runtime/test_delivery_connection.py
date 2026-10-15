import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class DeliveryConnectionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ssh"), "OpenSSH is required")
    def test_runner_ssh_configuration_keeps_long_preparation_connected(self):
        workflow = Path(".github/workflows/delivery.yml").read_text()
        step = workflow.split("      - name: Configure pinned SSH identity\n", 1)[1]
        step = step.split("      - name:", 1)[0]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["bash", "-eu", "-c", script],
                env={
                    **os.environ,
                    "HOME": directory,
                    "SSH_KEY": "test-only-placeholder",
                    "KNOWN_HOSTS": "test-only-placeholder",
                },
                check=True,
                capture_output=True,
            )
            config = Path(directory) / ".ssh/config"
            result = subprocess.run(
                ["ssh", "-G", "-F", str(config), "deploy@example.invalid"],
                check=True,
                capture_output=True,
                text=True,
            )
            options = dict(
                line.split(" ", 1) for line in result.stdout.splitlines() if " " in line
            )
            self.assertEqual(options["serveraliveinterval"], "30")
            self.assertEqual(options["serveralivecountmax"], "6")
