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
    def retrieval_data(self) -> Path:
        return self.data / "retrieval"

    @property
    def embedding_models(self) -> Path:
        return self.root / "embeddings"

    @property
    def retrieval_baselines(self) -> Path:
        return self.root / "retrieval-baselines"

    @property
    def retrieval_bindings(self) -> Path:
        return self.root / "retrieval-bindings"

    @property
    def generation_budget_database(self) -> Path:
        return self.data / "generation-budget.sqlite3"

    @property
    def backups(self) -> Path:
        return self.data.parent / "backups"


DEFAULT_PATHS = HostPaths()
IMAGE_RE = re.compile(r"^ghcr\.io/kant-2nd-project/sanaebi-api@sha256:[0-9a-f]{64}$")
RELEASE_RE = re.compile(r"^[0-9a-f]{40}-[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RETRIEVAL_MODEL_ID = "exp-models/dragonkue-KoEn-E5-Tiny"
RETRIEVAL_MODEL_REVISION = "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9"
RETRIEVAL_INDEXER_NAME = "sanaebi-retrieval-indexer"
RESET_WORKER_STOP_SECONDS = 20


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


def _active_release(paths: HostPaths) -> dict:
    """Read the active release record without following the current pointer."""
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
    directory = paths.root / target
    try:
        directory_info = directory.lstat()
        release_path = directory / "release.json"
        release_info = release_path.lstat()
        raw = release_path.read_bytes()
        release = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise MaintenanceError("active release metadata is invalid") from error
    if (
        not stat.S_ISDIR(directory_info.st_mode)
        or stat.S_ISLNK(directory_info.st_mode)
        or not stat.S_ISREG(release_info.st_mode)
        or stat.S_ISLNK(release_info.st_mode)
        or not isinstance(release, dict)
        or release.get("release_id") != match.group(1)
        or type(release.get("schema_version")) is not int
        or release.get("schema_version") not in (1, 2)
        or not isinstance(release.get("image"), str)
        or IMAGE_RE.fullmatch(release["image"]) is None
    ):
        raise MaintenanceError("active release metadata does not match its pointer")
    release["_directory"] = directory
    return release


def _configured_retrieval_mode(paths: HostPaths) -> str | None:
    env_file = paths.config / "api.env"
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise MaintenanceError("API environment file is unavailable") from error
    configured = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() != "SANAEBI_RETRIEVAL_MODE":
            continue
        if configured is not None:
            raise MaintenanceError("retrieval mode is configured more than once")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        configured = value
    if configured is not None and configured not in {"full", "rag"}:
        raise MaintenanceError("retrieval mode must be full or rag")
    return configured


def _active_retrieval_runtime(paths: HostPaths) -> dict:
    release = _active_release(paths)
    image = release["image"]
    configured_mode = _configured_retrieval_mode(paths)
    if release.get("schema_version") == 1:
        configured_mode = None
    retrieval_name = release.get("retrieval_manifest")
    retrieval_digest = release.get("retrieval_manifest_sha256")
    if configured_mode == "rag" and not retrieval_name:
        raise MaintenanceError("active release does not include retrieval support")
    if not retrieval_name:
        return {"mode": "full", "image": image, "release_id": release["release_id"]}
    if (
        retrieval_name != "retrieval-release.json"
        or not isinstance(retrieval_digest, str)
        or SHA256_RE.fullmatch(retrieval_digest) is None
    ):
        raise MaintenanceError("active retrieval descriptor metadata is invalid")
    descriptor_path = release["_directory"] / retrieval_name
    try:
        descriptor_info = descriptor_path.lstat()
        descriptor_raw = descriptor_path.read_bytes()
        descriptor = json.loads(descriptor_raw)
    except (OSError, json.JSONDecodeError) as error:
        raise MaintenanceError("active retrieval descriptor is unavailable") from error
    if (
        not stat.S_ISREG(descriptor_info.st_mode)
        or hashlib.sha256(descriptor_raw).hexdigest() != retrieval_digest
        or not isinstance(descriptor, dict)
        or descriptor.get("schema_version") != 1
        or descriptor.get("default_mode") not in {"full", "rag"}
        or type(descriptor.get("baseline_schema_version")) is not int
        or not 1 <= descriptor["baseline_schema_version"] <= 1000
        or type(descriptor.get("index_schema_version")) is not int
        or not 1 <= descriptor["index_schema_version"] <= 1000
    ):
        raise MaintenanceError("active retrieval descriptor failed validation")
    model = descriptor.get("embedding")
    if (
        not isinstance(model, dict)
        or model.get("model_id") != RETRIEVAL_MODEL_ID
        or model.get("revision") != RETRIEVAL_MODEL_REVISION
        or model.get("dimension") != 384
        or model.get("pooling") != "attention-mask-mean"
        or model.get("normalization") != "l2"
    ):
        raise MaintenanceError("active retrieval model contract is unsupported")
    mode = configured_mode or descriptor["default_mode"]
    runtime = {"mode": mode, "image": image, "release_id": release["release_id"]}
    if mode != "rag":
        return runtime

    binding_path = paths.retrieval_bindings / f"{release['release_id']}.json"
    try:
        binding_info = binding_path.lstat()
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MaintenanceError("active retrieval binding is unavailable") from error
    if (
        not stat.S_ISREG(binding_info.st_mode)
        or not isinstance(binding, dict)
        or binding.get("schema_version") != 1
        or binding.get("release_id") != release["release_id"]
        or binding.get("model_id") != RETRIEVAL_MODEL_ID
        or binding.get("revision") != RETRIEVAL_MODEL_REVISION
        or binding.get("baseline_schema_version")
        != descriptor["baseline_schema_version"]
        or binding.get("index_schema_version") != descriptor["index_schema_version"]
        or not isinstance(binding.get("spec_id"), str)
        or SHA256_RE.fullmatch(binding["spec_id"]) is None
        or not isinstance(binding.get("source_sha256"), str)
        or SHA256_RE.fullmatch(binding["source_sha256"]) is None
    ):
        raise MaintenanceError("active retrieval binding is invalid")
    try:
        source_info = paths.baseline.lstat()
        source_sha = hashlib.sha256(paths.baseline.read_bytes()).hexdigest()
    except OSError as error:
        raise MaintenanceError("immutable demo baseline is unavailable") from error
    if not stat.S_ISREG(source_info.st_mode) or source_sha != binding["source_sha256"]:
        raise MaintenanceError("host baseline differs from its retrieval binding")
    bundle = (
        paths.retrieval_baselines
        / f"schema-v{binding['baseline_schema_version']}"
        / binding["spec_id"]
        / binding["source_sha256"]
        / "baseline.sqlite3"
    )
    embedding = (
        paths.embedding_models
        / RETRIEVAL_MODEL_ID.replace("/", "--")
        / RETRIEVAL_MODEL_REVISION
    )
    try:
        bundle_info = bundle.lstat()
        embedding_info = embedding.lstat()
    except OSError as error:
        raise MaintenanceError("retrieval bundle or model is unavailable") from error
    if (
        stat.S_ISLNK(bundle_info.st_mode)
        or not stat.S_ISREG(bundle_info.st_mode)
        or stat.S_ISLNK(embedding_info.st_mode)
        or not stat.S_ISDIR(embedding_info.st_mode)
    ):
        raise MaintenanceError("retrieval bundle or model path is unsafe")
    return {
        **runtime,
        "binding": binding,
        "bundle": bundle,
        "embedding": embedding,
        "source": paths.baseline,
    }


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


def _maintenance_env(paths: HostPaths, **extra: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
        "DOCKER_CONFIG": str(paths.config / "docker-auth"),
        **extra,
    }


def _run_worker_preflight(
    paths: HostPaths,
    runtime: dict,
    *,
    runner=subprocess.run,
) -> dict:
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
        f"type=bind,src={runtime['source']},dst=/retrieval-source/documents.jsonl,readonly",
        "--mount",
        f"type=bind,src={runtime['bundle']},dst=/retrieval-baseline/baseline.sqlite3,readonly",
        runtime["image"],
        "python",
        "-m",
        "scripts.reset_demo_retrieval",
        "--check",
        "--source",
        "/retrieval-source/documents.jsonl",
        "--database",
        "/data/documents.sqlite3",
        "--bundle",
        "/retrieval-baseline/baseline.sqlite3",
    ]
    result = runner(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
        env=_maintenance_env(paths),
    )
    if result.returncode:
        raise MaintenanceError(
            f"retrieval reset preflight failed with exit code {result.returncode}"
        )
    try:
        report = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise MaintenanceError(
            "retrieval reset preflight returned invalid metadata"
        ) from error
    binding = runtime["binding"]
    if (
        not isinstance(report, dict)
        or report.get("status") != "ready"
        or report.get("spec_id") != binding["spec_id"]
        or report.get("source_sha256") != binding["source_sha256"]
    ):
        raise MaintenanceError(
            "retrieval reset preflight does not match active release"
        )
    return report


def _stop_retrieval_worker(paths: HostPaths, *, runner=subprocess.run) -> bool:
    result = runner(
        [
            "docker",
            "ps",
            "--quiet",
            "--filter",
            f"name=^/{RETRIEVAL_INDEXER_NAME}$",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        env=_maintenance_env(paths),
    )
    if result.returncode:
        raise MaintenanceError("retrieval worker inspection failed")
    if not getattr(result, "stdout", "").strip():
        return False
    result = runner(
        [
            "docker",
            "stop",
            "--time",
            str(RESET_WORKER_STOP_SECONDS),
            RETRIEVAL_INDEXER_NAME,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=RESET_WORKER_STOP_SECONDS + 10,
        env=_maintenance_env(paths),
    )
    if result.returncode:
        raise MaintenanceError("retrieval worker could not be stopped")
    return True


def _resume_retrieval_worker(
    paths: HostPaths, runtime: dict, *, runner=subprocess.run
) -> None:
    model_id = RETRIEVAL_MODEL_ID.replace("/", "--")
    model_path = f"/models/embeddings/{model_id}/{RETRIEVAL_MODEL_REVISION}"
    command = [
        "docker",
        "compose",
        "--project-name",
        "sanaebi",
        "--file",
        str(paths.config / "compose.yaml"),
        "--profile",
        "rag",
        "up",
        "--detach",
        "retrieval-indexer",
    ]
    env = _maintenance_env(
        paths,
        SANAEBI_IMAGE=runtime["image"],
        SANAEBI_RETRIEVAL_MODE="rag",
        SANAEBI_EMBEDDING_PATH=model_path,
        SANAEBI_RETRIEVAL_BUNDLE_HOST_PATH=str(runtime["bundle"]),
        SANAEBI_RETRIEVAL_SOURCE_HOST_PATH=str(runtime["source"]),
    )
    result = runner(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
        env=env,
    )
    if result.returncode:
        raise MaintenanceError("retrieval worker could not be restarted")
    status = runner(
        ["docker", "inspect", "--format", "{{.State.Running}}", RETRIEVAL_INDEXER_NAME],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        env=_maintenance_env(paths),
    )
    if status.returncode or status.stdout.strip() != "true":
        raise MaintenanceError("retrieval worker did not return to running state")


def _reset_demo_retrieval(
    paths: HostPaths, runtime: dict, *, runner=subprocess.run
) -> dict:
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
        f"type=bind,src={runtime['source']},dst=/retrieval-source/documents.jsonl,readonly",
        "--mount",
        f"type=bind,src={runtime['bundle']},dst=/retrieval-baseline/baseline.sqlite3,readonly",
        "--env",
        "SANAEBI_DOCUMENT_DB=/data/documents.sqlite3",
        "--env",
        "SANAEBI_RETRIEVAL_ROOT=/data/retrieval",
        runtime["image"],
        "python",
        "-m",
        "scripts.reset_demo_retrieval",
        "--source",
        "/retrieval-source/documents.jsonl",
        "--database",
        "/data/documents.sqlite3",
        "--bundle",
        "/retrieval-baseline/baseline.sqlite3",
    ]
    result = runner(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        env=_maintenance_env(paths),
    )
    if result.returncode:
        raise MaintenanceError(
            f"retrieval document reset failed with exit code {result.returncode}"
        )
    try:
        report = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise MaintenanceError(
            "retrieval document reset returned invalid metadata"
        ) from error
    if (
        not isinstance(report, dict)
        or report.get("status") != "ready"
        or report.get("documents_reset") is not True
        or report.get("retrieval_ready") is not True
        or report.get("ready") is not True
        or report.get("missing") != 0
    ):
        raise MaintenanceError("retrieval document reset did not reach ready state")
    return report


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
    runtime = _active_retrieval_runtime(paths)
    if runtime["mode"] != "rag":
        # A worker left over from an interrupted mode switch must not write the
        # derived index while a legacy/full document reset is in progress.
        _stop_retrieval_worker(paths, runner=runner)
        backup = create_database_backup(
            paths.database, paths.backups / "pre-reset", label="pre-reset"
        )
        reset_demo_documents(paths, runner=runner)
        return backup

    _run_worker_preflight(paths, runtime, runner=runner)
    resume_worker = False
    try:
        # Once preflight succeeds, always try to bring the worker back, including
        # when stopping it or taking the backup fails.
        resume_worker = True
        _stop_retrieval_worker(paths, runner=runner)
        backup = create_database_backup(
            paths.database, paths.backups / "pre-reset", label="pre-reset"
        )
        _reset_demo_retrieval(paths, runtime, runner=runner)
    except BaseException as error:
        if resume_worker:
            try:
                _resume_retrieval_worker(paths, runtime, runner=runner)
            except Exception as resume_error:  # noqa: BLE001 - report both state boundaries
                raise MaintenanceError(
                    "retrieval reset failed and the worker could not be restarted; "
                    f"failure types: {type(error).__name__}, {type(resume_error).__name__}"
                ) from error
        raise
    _resume_retrieval_worker(paths, runtime, runner=runner)
    return backup


def restore_retrieval(
    paths: HostPaths = DEFAULT_PATHS, *, runner=subprocess.run
) -> dict:
    """Reconnect valid baseline vectors to current revisions without source reset."""
    runtime = _active_retrieval_runtime(paths)
    if runtime["mode"] != "rag":
        raise MaintenanceError("mapping recovery requires an active rag release")
    _run_worker_preflight(paths, runtime, runner=runner)
    resume_worker = False
    try:
        resume_worker = True
        _stop_retrieval_worker(paths, runner=runner)
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
            f"type=bind,src={runtime['source']},dst=/retrieval-source/documents.jsonl,readonly",
            "--mount",
            f"type=bind,src={runtime['bundle']},dst=/retrieval-baseline/baseline.sqlite3,readonly",
            "--env",
            "SANAEBI_DOCUMENT_DB=/data/documents.sqlite3",
            "--env",
            "SANAEBI_RETRIEVAL_ROOT=/data/retrieval",
            "--env",
            "SANAEBI_RETRIEVAL_BASELINE=/retrieval-baseline/baseline.sqlite3",
            "--env",
            "SANAEBI_RETRIEVAL_SOURCE=/retrieval-source/documents.jsonl",
            runtime["image"],
            "python",
            "-m",
            "scripts.index_documents",
            "--restore-baseline",
        ]
        result = runner(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            env=_maintenance_env(paths),
        )
        if result.returncode:
            raise MaintenanceError(
                f"retrieval mapping restore failed with exit code {result.returncode}"
            )
        try:
            report = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise MaintenanceError("mapping restore returned invalid status") from error
        if (
            not isinstance(report, dict)
            or report.get("ready") is not True
            or report.get("missing") != 0
        ):
            raise MaintenanceError(
                "mapping restore did not prepare all current documents"
            )
    except BaseException as error:
        if resume_worker:
            try:
                _resume_retrieval_worker(paths, runtime, runner=runner)
            except Exception as resume_error:  # noqa: BLE001 - report both state boundaries
                raise MaintenanceError(
                    "mapping recovery failed and the worker could not be restarted; "
                    f"failure types: {type(error).__name__}, {type(resume_error).__name__}"
                ) from error
        raise
    _resume_retrieval_worker(paths, runtime, runner=runner)
    return report


def _require_root() -> None:
    if os.geteuid() != 0:
        raise MaintenanceError("this command must run as root")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup", help="create a consistent daily SQLite backup")
    subparsers.add_parser("reset", help="restore the immutable demo document baseline")
    subparsers.add_parser(
        "restore-retrieval",
        help="reconnect baseline vectors to current documents without resetting them",
    )
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
            elif args.command == "reset":
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
            else:
                report = restore_retrieval()
                print(
                    json.dumps(
                        {
                            "status": "success",
                            "operation": "restore-retrieval",
                            "ready_count": report.get("ready_count"),
                            "expected": report.get("expected"),
                            "missing": report.get("missing"),
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
