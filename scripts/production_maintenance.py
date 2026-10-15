"""Root-only SQLite backup and disposable-document reset helpers."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class MaintenanceError(RuntimeError):
    """A maintenance operation could not be completed safely."""


@dataclass(frozen=True)
class HostPaths:
    root: Path = Path("/srv/sanaebi")
    data: Path = Path("/var/lib/sanaebi/runtime")
    config: Path = Path("/etc/sanaebi")
    operation_lock: Path = Path("/run/lock/sanaebi-operation.lock")

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def baseline(self) -> Path:
        return self.data.parent / "baseline" / "documents.jsonl"

    @property
    def database(self) -> Path:
        return self.data / "documents.sqlite3"

    @property
    def generation_budget_database(self) -> Path:
        return self.data / "generation-budget.sqlite3"

    @property
    def backups(self) -> Path:
        return self.data.parent / "backups"


DEFAULT_PATHS = HostPaths()
IMAGE_RE = re.compile(r"^ghcr\.io/kant-2nd-project/sanaebi-api@sha256:[0-9a-f]{64}$")
RELEASE_RE = re.compile(r"^[0-9a-f]{40}-[0-9]+$")


@contextmanager
def operation_lock(path: Path = DEFAULT_PATHS.operation_lock):
    """Serialize deploy, reset, and backup using one persistent flock inode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise MaintenanceError("operation lock is not a regular file")
        if info.st_mode & 0o077:
            raise MaintenanceError("operation lock permissions are too broad")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def snapshot_sqlite_database(source: Path, destination: Path) -> dict[str, int | str]:
    """Create a consistent, exclusive SQLite backup without changing the source."""
    source = Path(source)
    destination = Path(destination)
    try:
        source_info = source.lstat()
    except FileNotFoundError as error:
        raise FileNotFoundError("source SQLite database does not exist") from error
    if not stat.S_ISREG(source_info.st_mode):
        raise MaintenanceError("source SQLite database is not a regular file")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with (
            closing(
                sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
            ) as live,
            closing(sqlite3.connect(temporary)) as backup,
        ):
            live.backup(backup)
            backup.commit()
            integrity = backup.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise MaintenanceError("SQLite backup integrity check failed")
            schema_version = int(backup.execute("PRAGMA user_version").fetchone()[0])
            page_count = int(backup.execute("PRAGMA page_count").fetchone()[0])
        os.chmod(temporary, 0o600)
        with temporary.open("rb") as file:
            os.fsync(file.fileno())
        # link() gives no-overwrite semantics even if another process races us.
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {
            "schema_version": schema_version,
            "page_count": page_count,
            "integrity": "ok",
        }
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _backup_name(label: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", label):
        raise MaintenanceError("invalid backup label")
    timestamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%dT%H%M%S%z")
    return f"{label}-{timestamp}-{uuid.uuid4().hex[:8]}.sqlite3"


def create_database_backup(database: Path, backup_dir: Path, *, label: str) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_path = backup_dir / _backup_name(label)
    result = snapshot_sqlite_database(database, backup_path)
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "label": label,
        "source_name": Path(database).name,
        "backup_name": backup_path.name,
        "sha256": digest,
        **result,
    }
    _atomic_json(backup_path.with_suffix(".manifest.json"), manifest)
    return backup_path


def _read_active_image(paths: HostPaths) -> str:
    current = paths.current
    try:
        current_info = current.lstat()
    except FileNotFoundError as error:
        raise MaintenanceError("there is no active release") from error
    if not stat.S_ISLNK(current_info.st_mode):
        raise MaintenanceError("current release pointer is not a symlink")
    target = os.readlink(current)
    match = re.fullmatch(r"releases/([0-9a-f]{40}-[0-9]+)", target)
    if match is None:
        raise MaintenanceError("current release pointer is outside the release store")
    release_dir = paths.root / target
    release_file = release_dir / "release.json"
    if release_file.is_symlink() or not release_file.is_file():
        raise MaintenanceError("active release metadata is missing or unsafe")
    try:
        release = json.loads(release_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MaintenanceError("active release metadata is invalid") from error
    if release.get("release_id") != match.group(1):
        raise MaintenanceError("active release identity does not match its pointer")
    image = release.get("image")
    if not isinstance(image, str) or IMAGE_RE.fullmatch(image) is None:
        raise MaintenanceError("active release image is not digest-pinned")
    return image


def reset_demo_documents(
    paths: HostPaths = DEFAULT_PATHS,
    *,
    runner=subprocess.run,
) -> None:
    image = _read_active_image(paths)
    if paths.baseline.is_symlink() or not paths.baseline.is_file():
        raise MaintenanceError("immutable demo baseline is missing or unsafe")
    if paths.database.is_symlink() or not paths.database.is_file():
        raise MaintenanceError("demo database is missing or unsafe")
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--user",
        "10001:10001",
        "--mount",
        f"type=bind,src={paths.data},dst=/data",
        "--mount",
        f"type=bind,src={paths.baseline},dst=/app/data/company-knowledge/documents.jsonl,readonly",
        "--env",
        "SANAEBI_DOCUMENT_DB=/data/documents.sqlite3",
        image,
        "python",
        "scripts/reset_demo_documents.py",
        "--source",
        "/app/data/company-knowledge/documents.jsonl",
        "--database",
        "/data/documents.sqlite3",
        "--apply",
    ]
    result = runner(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
            "DOCKER_CONFIG": str(paths.config / "docker-auth"),
        },
    )
    if result.returncode:
        raise MaintenanceError(
            f"demo reset container failed with exit code {result.returncode}"
        )


def create_daily_backups(paths: HostPaths = DEFAULT_PATHS) -> dict[str, Path | None]:
    """Back up each SQLite file independently; there is no cross-file snapshot."""
    outputs: dict[str, Path | None] = {
        "documents": create_database_backup(
            paths.database, paths.backups / "daily", label="daily"
        )
    }
    budget = paths.generation_budget_database
    try:
        budget_info = budget.lstat()
    except FileNotFoundError:
        outputs["generation_budget"] = None
    else:
        if not stat.S_ISREG(budget_info.st_mode):
            raise MaintenanceError("generation budget database is not a regular file")
        outputs["generation_budget"] = create_database_backup(
            budget, paths.backups / "daily", label="daily"
        )
    return outputs


def reset_demo_documents_with_backup(
    paths: HostPaths = DEFAULT_PATHS,
    *,
    runner=subprocess.run,
) -> Path:
    """Make a root-controlled document snapshot before running the app reset."""
    backup = create_database_backup(
        paths.database, paths.backups / "pre-reset", label="pre-reset"
    )
    reset_demo_documents(paths, runner=runner)
    return backup


def _require_root() -> None:
    if os.geteuid() != 0:
        raise MaintenanceError("this command must run as root")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup", help="create a consistent daily SQLite backup")
    subparsers.add_parser("reset", help="restore the immutable demo document baseline")
    args = parser.parse_args(argv)
    try:
        _require_root()
        with operation_lock():
            if args.command == "backup":
                result = create_daily_backups()
                print(
                    json.dumps(
                        {
                            "status": "success",
                            "backups": {
                                name: str(path) if path is not None else None
                                for name, path in result.items()
                            },
                        }
                    )
                )
            else:
                backup = reset_demo_documents_with_backup()
                print(
                    json.dumps(
                        {
                            "status": "success",
                            "operation": "reset",
                            "document_backup": str(backup),
                        }
                    )
                )
    except (
        OSError,
        sqlite3.Error,
        MaintenanceError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps({"status": "failed", "error_type": type(error).__name__}),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
