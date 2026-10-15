#!/usr/bin/python3
"""Root-owned entry point accepting only short-lived Actions registry credentials."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    if os.geteuid() != 0 or sys.argv[1:] not in (["login"], ["logout"]):
        raise SystemExit("Only root login/logout is supported")
    os.umask(0o077)
    directory = Path("/etc/sanaebi/docker-auth")
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink():
        raise SystemExit("Invalid credential directory")
    environment = {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": str(directory)}
    if sys.argv[1] == "logout":
        (directory / "config.json").unlink(missing_ok=True)
        return
    token = sys.stdin.buffer.read(8193)
    if not token or len(token) > 8192 or b"\x00" in token:
        raise SystemExit("Invalid credential input")
    result = subprocess.run(
        [
            "/usr/bin/docker",
            "login",
            "ghcr.io",
            "--username",
            "js2923",
            "--password-stdin",
        ],
        input=token,
        env=environment,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise SystemExit("Registry authentication failed")
    print("Registry authentication configured")


if __name__ == "__main__":
    main()
