"""Install one validated immutable Sanaebi release on the production host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

# The installed helper lives under /usr/local/libexec/sanaebi/scripts while its
# sibling modules live one directory above it. Keep direct-script execution
# independent of the caller's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.deployment_embedding import (
    ReleaseError as EmbeddingReleaseError,
)
from scripts.deployment_embedding import (
    RetrievalRelease,
)
from scripts.deployment_embedding import (
    parse_manifest as parse_retrieval_manifest,
)
from scripts.deployment_embedding import (
    validate_model_directory as validate_retrieval_model_directory,
)
from scripts.production_maintenance import (
    DEFAULT_PATHS,
    HostPaths,
    MaintenanceError,
    create_database_backup,
    operation_lock,
    snapshot_sqlite_database,
)

EXPECTED_IMAGE = re.compile(
    r"^ghcr\.io/kant-2nd-project/sanaebi-api@sha256:[0-9a-f]{64}$"
)
RELEASE_ID = re.compile(r"^[0-9a-f]{40}-[0-9]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MODEL_ID = re.compile(r"^[0-9a-f]{32}$")
MODEL_REVISION = re.compile(r"^[0-9a-f]{40}$")
RECOVERABLE_PHASES = {
    "release_validated",
    "pulling_image",
    "model_ready",
    "candidate_ready",
    "maintenance_enabled",
    "previous_api_stopped",
    "database_backed_up",
    "new_api_started",
    "new_api_ready",
    "web_switched",
    "recovering",
    "recovery_required",
}
PRE_DOWNTIME_PHASES = {
    "release_validated",
    "pulling_image",
    "model_ready",
    "candidate_ready",
}
MODEL_FILES = {
    "config.json",
    "metadata.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
}
MAX_RELEASE_JSON = 64 * 1024
MAX_MODEL_MANIFEST = 1024 * 1024
MAX_WEB_ARCHIVE = 128 * 1024 * 1024
MAX_WEB_FILES = 20_000
MAX_WEB_BYTES = 1024 * 1024 * 1024
READY_TIMEOUT_SECONDS = 240
STOP_TIMEOUT_SECONDS = 240


class DeploymentError(RuntimeError):
    """A release failed a safety check or a deployment phase."""


@dataclass(frozen=True)
class Release:
    release_id: str
    image: str
    web_archive: str
    web_sha256: str
    model_manifest: str
    model_manifest_sha256: str
    schema_version: int = 1
    retrieval_manifest: str | None = None
    retrieval_manifest_sha256: str | None = None

    def verify_payload_hashes(self, payload: Mapping[str, bytes]) -> None:
        for name, expected in (
            (self.web_archive, self.web_sha256),
            (self.model_manifest, self.model_manifest_sha256),
            *(
                ((self.retrieval_manifest, self.retrieval_manifest_sha256),)
                if self.retrieval_manifest is not None
                and self.retrieval_manifest_sha256 is not None
                else ()
            ),
        ):
            content = payload.get(name)
            if content is None:
                raise DeploymentError(f"release payload is missing {name}")
            if hashlib.sha256(content).hexdigest() != expected:
                raise DeploymentError(f"release payload hash mismatch: {name}")


@dataclass(frozen=True)
class ReleaseInputs:
    release: Release
    model_id: str
    model_revision: str
    manifest_raw: bytes
    retrieval_release: RetrievalRelease | None = None
    retrieval_raw: bytes | None = None


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_release_manifest(raw: bytes, expected_release_id: str) -> Release:
    if not RELEASE_ID.fullmatch(expected_release_id):
        raise DeploymentError(
            "release id must be a full commit SHA followed by a run id"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise DeploymentError("release.json is not valid UTF-8 JSON") from error
    base_fields = {
        "schema_version",
        "release_id",
        "image",
        "web_archive",
        "web_sha256",
        "model_manifest",
        "model_manifest_sha256",
    }
    if not isinstance(value, dict) or not base_fields.issubset(value):
        raise DeploymentError("release.json has an unsupported shape")
    schema_version = value["schema_version"]
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise DeploymentError("unsupported release.json schema")
    retrieval_fields = {"retrieval_manifest", "retrieval_manifest_sha256"}
    present_retrieval_fields = set(value) & retrieval_fields
    if schema_version == 1 and set(value) != base_fields:
        raise DeploymentError("release.json has an unsupported shape")
    if schema_version == 2 and set(value) not in (
        base_fields,
        base_fields | retrieval_fields,
    ):
        raise DeploymentError("release.json has an unsupported shape")
    if value["release_id"] != expected_release_id:
        raise DeploymentError("release.json identity does not match its directory")
    image = value["image"]
    if not isinstance(image, str) or EXPECTED_IMAGE.fullmatch(image) is None:
        raise DeploymentError(
            "API image must use the approved GHCR repository and SHA-256 digest"
        )
    for field, required_name in (
        ("web_archive", "web.tar.gz"),
        ("model_manifest", "model-release.json"),
    ):
        name = value[field]
        if name != required_name or Path(name).name != name:
            raise DeploymentError(
                f"{field} must be the approved release-local filename"
            )
    retrieval_manifest = None
    retrieval_manifest_sha256 = None
    if present_retrieval_fields:
        retrieval_manifest = value["retrieval_manifest"]
        if (
            retrieval_manifest != "retrieval-release.json"
            or Path(retrieval_manifest).name != retrieval_manifest
        ):
            raise DeploymentError(
                "retrieval_manifest must be the approved release-local filename"
            )
        retrieval_manifest_sha256 = value["retrieval_manifest_sha256"]
    digest_fields = ["web_sha256", "model_manifest_sha256"]
    if retrieval_manifest is not None:
        digest_fields.append("retrieval_manifest_sha256")
    for field in digest_fields:
        if not isinstance(value[field], str) or SHA256.fullmatch(value[field]) is None:
            raise DeploymentError(f"{field} must be a lowercase SHA-256 digest")
    return Release(
        release_id=expected_release_id,
        image=image,
        web_archive=value["web_archive"],
        web_sha256=value["web_sha256"],
        model_manifest=value["model_manifest"],
        model_manifest_sha256=value["model_manifest_sha256"],
        schema_version=schema_version,
        retrieval_manifest=retrieval_manifest,
        retrieval_manifest_sha256=retrieval_manifest_sha256,
    )


def _safe_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        raise DeploymentError("web archive contains an invalid path")
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise DeploymentError("web archive contains an absolute path")
    if any(part in ("", ".", "..") for part in posix.parts):
        raise DeploymentError("web archive path escapes its destination")
    return posix


def safe_extract_web_archive(archive: Path, destination: Path) -> None:
    """Extract only regular files/directories under destination; reject links."""
    archive = Path(archive)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise DeploymentError("web extraction destination already exists")
    try:
        archive_info = archive.lstat()
    except OSError as error:
        raise DeploymentError("web archive is unavailable") from error
    if not stat.S_ISREG(archive_info.st_mode) or archive_info.st_size > MAX_WEB_ARCHIVE:
        raise DeploymentError("web archive is not a bounded regular file")
    destination.mkdir(parents=True, mode=0o755)
    seen: dict[str, bool] = {}
    total_bytes = 0
    file_count = 0
    try:
        with tarfile.open(archive, mode="r:*") as tar:
            members = []
            for member in tar:
                if len(members) >= MAX_WEB_FILES:
                    raise DeploymentError("web archive has too many entries")
                relative = _safe_member_path(member.name)
                key = relative.as_posix()
                if key in seen:
                    raise DeploymentError("web archive contains duplicate paths")
                for parent in relative.parents:
                    parent_key = parent.as_posix()
                    if parent_key != "." and seen.get(parent_key) is False:
                        raise DeploymentError(
                            "web archive has a file used as a directory"
                        )
                if member.isdir():
                    seen[key] = True
                elif member.type in (tarfile.REGTYPE, tarfile.AREGTYPE):
                    if member.size < 0 or member.size > MAX_WEB_BYTES:
                        raise DeploymentError("web archive contains an oversized file")
                    seen[key] = False
                    total_bytes += member.size
                    file_count += 1
                    if total_bytes > MAX_WEB_BYTES:
                        raise DeploymentError(
                            "web archive expands beyond the size limit"
                        )
                else:
                    raise DeploymentError(
                        "web archive links and special files are forbidden"
                    )
                members.append((member, relative))

            if file_count == 0:
                raise DeploymentError("web archive contains no files")
            for member, relative in members:
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o755)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                source = tar.extractfile(member)
                if source is None:
                    raise DeploymentError("web archive file could not be read")
                remaining = member.size
                with source, target.open("xb") as output:
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise DeploymentError("web archive file was truncated")
                        output.write(chunk)
                        remaining -= len(chunk)
                    if source.read(1):
                        raise DeploymentError(
                            "web archive file exceeds its declared size"
                        )
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(target, 0o644)
        if not (destination / "index.html").is_file():
            raise DeploymentError(
                "web archive is not a static export (index.html missing)"
            )
        static_assets = destination / "_next" / "static"
        if static_assets.is_symlink() or not static_assets.is_dir():
            raise DeploymentError("web archive is missing _next/static")
        os.chmod(destination, 0o755)
    except (tarfile.TarError, OSError) as error:
        shutil.rmtree(destination, ignore_errors=True)
        if isinstance(error, DeploymentError):
            raise
        raise DeploymentError("web archive could not be safely extracted") from error
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _check_path_chain(path: Path) -> None:
    path = Path(os.path.abspath(path))
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise DeploymentError(f"symlink path component is forbidden: {cursor}")
        if not stat.S_ISDIR(info.st_mode):
            raise DeploymentError(
                f"non-directory path component is forbidden: {cursor}"
            )


def _read_at(directory_fd: int, name: str, limit: int) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise DeploymentError(
                f"release input is not a bounded regular file: {name}"
            )
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > limit:
            raise DeploymentError(f"release input exceeds the size limit: {name}")
        return content
    finally:
        os.close(descriptor)


def _safe_release_dir(directory: Path, release_id: str) -> int:
    if not RELEASE_ID.fullmatch(release_id):
        raise DeploymentError("invalid release id")
    directory = Path(directory)
    _check_path_chain(directory.parent)
    parent_info = directory.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode):
        raise DeploymentError("incoming release parent is not a directory")
    _check_path_chain(directory)
    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise DeploymentError("incoming release is not a directory")
    return descriptor


def load_release_inputs(
    incoming: Path, release_id: str
) -> tuple[ReleaseInputs, dict[str, bytes]]:
    directory = Path(incoming) / release_id
    directory_fd = _safe_release_dir(directory, release_id)
    try:
        raw = _read_at(directory_fd, "release.json", MAX_RELEASE_JSON)
        release = parse_release_manifest(raw, release_id)
        archive = _read_at(directory_fd, release.web_archive, MAX_WEB_ARCHIVE)
        model_manifest = _read_at(
            directory_fd, release.model_manifest, MAX_MODEL_MANIFEST
        )
        payload = {
            release.web_archive: archive,
            release.model_manifest: model_manifest,
        }
        retrieval_raw = None
        retrieval_release = None
        if release.retrieval_manifest is not None:
            retrieval_raw = _read_at(
                directory_fd, release.retrieval_manifest, MAX_MODEL_MANIFEST
            )
            payload[release.retrieval_manifest] = retrieval_raw
        release.verify_payload_hashes(payload)
        try:
            model = json.loads(
                model_manifest.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise DeploymentError("model-release.json is invalid JSON") from error
        if not isinstance(model, dict) or model.get("schema_version") != 1:
            raise DeploymentError("model-release.json schema is unsupported")
        model_id, revision = model.get("model_id"), model.get("revision")
        if not isinstance(model_id, str) or MODEL_ID.fullmatch(model_id) is None:
            raise DeploymentError("model-release.json has an invalid model id")
        if not isinstance(revision, str) or MODEL_REVISION.fullmatch(revision) is None:
            raise DeploymentError("model-release.json has an invalid revision")
        if retrieval_raw is not None:
            try:
                retrieval_release = parse_retrieval_manifest(retrieval_raw)
            except EmbeddingReleaseError as error:
                raise DeploymentError("retrieval-release.json is invalid") from error
        return (
            ReleaseInputs(
                release,
                model_id,
                revision,
                model_manifest,
                retrieval_release,
                retrieval_raw,
            ),
            payload,
        )
    finally:
        os.close(directory_fd)


def _secure_file(path: Path, *, private: bool) -> None:
    _check_path_chain(path.parent)
    for directory in reversed(path.parent.parents):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise DeploymentError(
                f"trusted file directory is not root-controlled: {directory}"
            )
    parent_info = path.parent.lstat()
    if parent_info.st_uid != 0 or parent_info.st_mode & 0o022:
        raise DeploymentError(
            f"trusted file directory is not root-controlled: {path.parent}"
        )
    try:
        info = path.lstat()
    except OSError as error:
        raise DeploymentError(
            f"required trusted file is unavailable: {path}"
        ) from error
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise DeploymentError(f"trusted file must be a root-owned regular file: {path}")
    if info.st_mode & 0o022:
        raise DeploymentError(f"trusted file must not be group/world writable: {path}")
    if private and info.st_mode & 0o077:
        raise DeploymentError(f"secret file must be owner-only: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise DeploymentError("deployment payload is missing or unsafe") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DeploymentError("deployment payload is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return size, digest.hexdigest()


def _atomic_symlink(path: Path, relative_target: str | None) -> None:
    path = Path(path)
    if relative_target is None:
        if path.is_symlink():
            path.unlink()
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        elif path.exists():
            raise DeploymentError(f"release pointer is not a symlink: {path.name}")
        return
    if path.exists() and not path.is_symlink():
        raise DeploymentError(f"release pointer is not a symlink: {path.name}")
    temp = path.parent / f".{path.name}.{os.getpid()}.{time.monotonic_ns()}"
    try:
        os.symlink(relative_target, temp)
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _pointer_target(pointer: Path, expected_prefix: str) -> str | None:
    try:
        info = pointer.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISLNK(info.st_mode):
        raise DeploymentError(f"release pointer is not a symlink: {pointer.name}")
    target = os.readlink(pointer)
    if expected_prefix == "releases/":
        valid = (
            target.startswith(expected_prefix)
            and RELEASE_ID.fullmatch(target.removeprefix(expected_prefix)) is not None
        )
    elif expected_prefix == "":
        valid = re.fullmatch(r"[0-9a-f]{32}/[0-9a-f]{40}", target) is not None
    else:
        valid = False
    if not valid:
        raise DeploymentError(f"release pointer escapes its store: {pointer.name}")
    return target


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if destination.is_symlink():
        raise DeploymentError("static asset destination is a symlink")
    if destination.exists():
        if not destination.is_file() or _sha256(source) != _sha256(destination):
            raise DeploymentError("immutable static asset path has conflicting content")
        return
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temp = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, 0o644)
        os.link(temp, destination, follow_symlinks=False)
        temp.unlink()
    except FileExistsError:
        if not destination.is_file() or _sha256(source) != _sha256(destination):
            raise DeploymentError("immutable static asset path has conflicting content")
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _assert_safe_tree(root: Path, *, allow_empty: bool = True) -> None:
    for path in [root, *root.rglob("*")]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise DeploymentError(f"symlink is forbidden in release tree: {path}")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise DeploymentError(f"special file is forbidden in release tree: {path}")


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise DeploymentError("release metadata is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeploymentError("release metadata is invalid") from error
    if not isinstance(value, dict):
        raise DeploymentError("release metadata must be an object")
    return value


class DeploymentEngine:
    def __init__(
        self,
        paths: HostPaths = DEFAULT_PATHS,
        *,
        runner: Callable = subprocess.run,
        urlopen: Callable = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        uid: int | None = None,
        helper_path: Path | None = None,
    ):
        self.paths = paths
        self.runner = runner
        self.urlopen = urlopen
        self.sleep = sleep
        self.uid = os.geteuid() if uid is None else uid
        self.helper_path = Path(__file__) if helper_path is None else Path(helper_path)
        self._active_journal: dict | None = None

    def _require_root_and_trusted_inputs(self) -> None:
        if self.uid != 0:
            raise DeploymentError("deployment helper must run as root")
        _secure_file(self.helper_path, private=False)
        for path, private in (
            (self.paths.config / "compose.yaml", False),
            (self.paths.config / "api.env", True),
            (self.paths.config / "hf-download.env", True),
        ):
            _secure_file(path, private=private)
        docker_auth = self.paths.config / "docker-auth"
        try:
            auth_info = docker_auth.lstat()
        except OSError as error:
            raise DeploymentError(
                "root-only Docker credential directory is unavailable"
            ) from error
        if (
            not stat.S_ISDIR(auth_info.st_mode)
            or auth_info.st_uid != 0
            or auth_info.st_mode & 0o077
        ):
            raise DeploymentError("Docker credential directory must be root-only")
        if stat.S_IMODE(auth_info.st_mode) != 0o700:
            raise DeploymentError("Docker credential directory must have mode 0700")
        _check_path_chain(self.paths.root)
        _check_path_chain(self.paths.data)
        state_root = self.paths.data.parent
        try:
            state_info = state_root.lstat()
        except OSError as error:
            raise DeploymentError("persistent state root is unavailable") from error
        if (
            not stat.S_ISDIR(state_info.st_mode)
            or state_info.st_uid != 0
            or state_info.st_mode & 0o022
        ):
            raise DeploymentError(
                "persistent state root must be root-owned and not group/world-writable"
            )

    def _require_recovery_inputs(self) -> None:
        if self.uid != 0:
            raise DeploymentError("deployment recovery must run as root")
        _secure_file(self.helper_path, private=False)
        _secure_file(self.paths.config / "compose.yaml", private=False)
        _secure_file(self.paths.config / "api.env", private=True)
        docker_auth = self.paths.config / "docker-auth"
        try:
            auth_info = docker_auth.lstat()
        except OSError as error:
            raise DeploymentError(
                "root-only Docker credential directory is unavailable"
            ) from error
        if (
            not stat.S_ISDIR(auth_info.st_mode)
            or auth_info.st_uid != 0
            or stat.S_IMODE(auth_info.st_mode) != 0o700
        ):
            raise DeploymentError("Docker credential directory must be root-only")
        for directory in (self.paths.root, self.paths.data, self.paths.data.parent):
            _check_path_chain(directory)
            try:
                info = directory.lstat()
            except OSError as error:
                raise DeploymentError(
                    "trusted recovery directory is unavailable"
                ) from error
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != 0
                or info.st_mode & 0o022
            ):
                raise DeploymentError(
                    "recovery directories must be root-owned and not group/world-writable"
                )

    def _docker_env(self, **extra: str) -> dict[str, str]:
        return {
            **os.environ,
            "DOCKER_CONFIG": str(self.paths.config / "docker-auth"),
            **extra,
        }

    def _run(self, label: str, command: list[str], *, timeout: int = 600, **kwargs):
        result = self.runner(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=self._docker_env(),
            **kwargs,
        )
        if result.returncode:
            raise DeploymentError(f"{label} failed with exit code {result.returncode}")
        return result

    def _journal(self, phase: str, **fields) -> None:
        self._active_journal = {
            **(self._active_journal or {}),
            "schema_version": 1,
            "release_id": self._active_journal.get("release_id")
            if self._active_journal
            else None,
            "phase": phase,
            "updated_at": datetime.now(UTC).isoformat(),
            **fields,
        }
        self._atomic_write_json(
            self.paths.root / "deployment-journal.json", self._active_journal
        )

    @staticmethod
    def _atomic_write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
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

    def _check_no_incomplete_journal(self) -> None:
        journal = self.paths.root / "deployment-journal.json"
        if not journal.exists():
            return
        value = _read_json(journal)
        if value.get("phase") not in ("complete", "rolled_back"):
            raise DeploymentError(
                "an unfinished deployment journal requires root-only recover"
            )

    def _validate_recovery_release(self, target: str) -> tuple[str, str]:
        match = re.fullmatch(r"releases/([0-9a-f]{40}-[0-9]+)", target)
        if match is None:
            raise DeploymentError("journal contains an unsafe prior release pointer")
        release_id = match.group(1)
        release_dir = self.paths.root / target
        _check_path_chain(release_dir)
        try:
            info = release_dir.lstat()
        except OSError as error:
            raise DeploymentError("journal prior release is unavailable") from error
        if not stat.S_ISDIR(info.st_mode):
            raise DeploymentError("journal prior release is not a directory")
        release = _read_json(release_dir / "release.json")
        image = release.get("image")
        if (
            release.get("release_id") != release_id
            or not isinstance(image, str)
            or EXPECTED_IMAGE.fullmatch(image) is None
        ):
            raise DeploymentError("journal prior release metadata is invalid")
        return release_id, image

    def _validate_recovery_model(self, target: str) -> None:
        if re.fullmatch(r"[0-9a-f]{32}/[0-9a-f]{40}", target) is None:
            raise DeploymentError("journal contains an unsafe prior model pointer")
        directory = self.paths.root / "models" / target
        _check_path_chain(directory)
        try:
            info = directory.lstat()
        except OSError as error:
            raise DeploymentError("journal prior model is unavailable") from error
        if not stat.S_ISDIR(info.st_mode):
            raise DeploymentError("journal prior model is not a directory")
        try:
            entries = list(directory.iterdir())
        except OSError as error:
            raise DeploymentError("journal prior model is unreadable") from error
        if {entry.name for entry in entries} != MODEL_FILES:
            raise DeploymentError("journal prior model inventory is invalid")
        for entry in entries:
            if not stat.S_ISREG(entry.lstat().st_mode):
                raise DeploymentError("journal prior model contains an unsafe file")

    def _load_recovery_journal(self) -> dict:
        path = self.paths.root / "deployment-journal.json"
        try:
            info = path.lstat()
        except OSError as error:
            raise DeploymentError("there is no readable deployment journal") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.uid
            or info.st_mode & 0o077
        ):
            raise DeploymentError("deployment journal is not trusted")
        journal = _read_json(path)
        if (
            type(journal.get("schema_version")) is not int
            or journal["schema_version"] != 1
            or not isinstance(journal.get("release_id"), str)
            or RELEASE_ID.fullmatch(journal["release_id"]) is None
            or not isinstance(journal.get("phase"), str)
        ):
            raise DeploymentError("deployment journal header is invalid")
        phase = journal["phase"]
        if phase in ("complete", "rolled_back"):
            return journal
        if phase not in RECOVERABLE_PHASES:
            raise DeploymentError("deployment journal phase is unsupported")

        release_id = journal["release_id"]
        required = {
            "candidate_image",
            "candidate_preflight_container",
            "candidate_preflight_data",
            "candidate_model_id",
            "candidate_model_revision",
            "old_current_target",
            "old_previous_target",
            "old_model_target",
            "old_release_image",
        }
        if not required.issubset(journal):
            raise DeploymentError(
                "journal lacks saved rollback pointers; keep maintenance enabled and use the host recovery procedure"
            )
        if journal.get("old_retrieval_mode") not in (None, "full", "rag"):
            raise DeploymentError("deployment journal prior retrieval mode is invalid")
        image = journal["candidate_image"]
        if (
            not isinstance(image, str)
            or EXPECTED_IMAGE.fullmatch(image) is None
            or journal.get("image") != image
        ):
            raise DeploymentError("deployment journal candidate image is invalid")
        if (
            journal["candidate_preflight_container"]
            != f"sanaebi-preflight-{release_id}"
        ):
            raise DeploymentError("deployment journal candidate container is invalid")
        if journal["candidate_preflight_data"] != f".preflight-{release_id}":
            raise DeploymentError("deployment journal candidate data path is invalid")
        if (
            not isinstance(journal["candidate_model_id"], str)
            or MODEL_ID.fullmatch(journal["candidate_model_id"]) is None
            or not isinstance(journal["candidate_model_revision"], str)
            or MODEL_REVISION.fullmatch(journal["candidate_model_revision"]) is None
        ):
            raise DeploymentError("deployment journal candidate model is invalid")

        old_current = journal["old_current_target"]
        old_previous = journal["old_previous_target"]
        old_model = journal["old_model_target"]
        old_image = journal["old_release_image"]
        if old_current is None:
            if old_image is not None:
                raise DeploymentError(
                    "deployment journal prior release is inconsistent"
                )
        elif not isinstance(old_current, str):
            raise DeploymentError("deployment journal prior release pointer is invalid")
        else:
            prior_release = self._validate_recovery_release(old_current)
            if old_image != prior_release[1]:
                raise DeploymentError("deployment journal prior image does not match")
        if old_previous is not None:
            if not isinstance(old_previous, str):
                raise DeploymentError("deployment journal previous pointer is invalid")
            self._validate_recovery_release(old_previous)
        if old_model is not None:
            if not isinstance(old_model, str):
                raise DeploymentError(
                    "deployment journal prior model pointer is invalid"
                )
            self._validate_recovery_model(old_model)
        if old_image is not None and (
            not isinstance(old_image, str)
            or EXPECTED_IMAGE.fullmatch(old_image) is None
        ):
            raise DeploymentError("deployment journal prior image is invalid")
        return journal

    def _remove_preflight_artifacts(self, journal: Mapping[str, object]) -> None:
        container = str(journal["candidate_preflight_container"])
        result = self.runner(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"name=^/{container}$",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=self._docker_env(),
        )
        if result.returncode:
            raise DeploymentError(
                f"candidate container inspection failed with exit code {result.returncode}"
            )
        if result.stdout.strip():
            self._run(
                "candidate container cleanup",
                ["docker", "rm", "--force", container],
                timeout=60,
            )

        data = self.paths.data / str(journal["candidate_preflight_data"])
        try:
            info = data.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(info.st_mode):
            raise DeploymentError("candidate preflight data is not a directory")
        _assert_safe_tree(data)
        shutil.rmtree(data)

    def recover(self) -> str:
        """Recover one interrupted deployment without restoring or replacing SQLite."""
        self._require_recovery_inputs()
        with operation_lock(self.paths.operation_lock):
            journal = self._load_recovery_journal()
            self._active_journal = journal
            phase = str(journal["phase"])
            marker = self.paths.root / "maintenance"
            marker_exists = marker.exists() or marker.is_symlink()
            if marker_exists:
                marker_info = marker.lstat()
                if not stat.S_ISREG(marker_info.st_mode):
                    raise DeploymentError("maintenance marker is unsafe")
            if phase in ("complete", "rolled_back"):
                if marker_exists:
                    raise DeploymentError(
                        "terminal journal conflicts with the maintenance marker"
                    )
                return phase

            self._remove_preflight_artifacts(journal)
            release_id = str(journal["release_id"])
            candidate_image = str(journal["candidate_image"])
            candidate_model = (
                f"{journal['candidate_model_id']}/{journal['candidate_model_revision']}"
            )

            if phase == "web_switched" and not marker_exists:
                try:
                    active = self._active_release()
                    active_model = _pointer_target(
                        self.paths.root / "models" / "current", ""
                    )
                    if (
                        active == (release_id, candidate_image)
                        and active_model == candidate_model
                    ):
                        self._wait_ready("http://127.0.0.1:18000/health/ready")
                        self._journal(
                            "complete",
                            recovered_after_commit=True,
                            finished_at=datetime.now(UTC).isoformat(),
                        )
                        return "complete"
                except DeploymentError:
                    pass

            if phase in PRE_DOWNTIME_PHASES and not marker_exists:
                self._journal(
                    "rolled_back",
                    interrupted_before_maintenance=True,
                    database_restored=False,
                )
                return "rolled_back"

            if not marker_exists:
                self._maintenance_on(release_id)
            self._journal(
                "recovering", recovery_started_at=datetime.now(UTC).isoformat()
            )
            try:
                self._stop_indexer_if_running()
                errors = []
                for path, target in (
                    (
                        self.paths.root / "models" / "current",
                        journal["old_model_target"],
                    ),
                    (self.paths.root / "current", journal["old_current_target"]),
                    (self.paths.root / "previous", journal["old_previous_target"]),
                ):
                    try:
                        self._restore_pointer(path, target)
                    except Exception as error:  # noqa: BLE001 - attempt all safe pointer restores
                        errors.append(type(error).__name__)
                if errors:
                    raise DeploymentError(
                        "one or more release pointers could not be restored"
                    )

                old_current = journal["old_current_target"]
                old_image = journal["old_release_image"]
                if old_current is not None:
                    old_release_id = old_current.removeprefix("releases/")
                    old_mode = journal.get("old_retrieval_mode")
                    if old_mode is None:
                        # Older journal revisions did not save the prior runtime
                        # mode; retain their config-based recovery compatibility.
                        old_mode = self._configured_retrieval_mode() or "full"
                    if old_mode not in ("full", "rag"):
                        raise DeploymentError("journaled retrieval mode is invalid")
                    mode, runtime_overrides, _ = self._runtime_overrides(
                        old_release_id, force_mode=old_mode
                    )
                    if mode == "rag":
                        self._compose(
                            str(old_image),
                            "up",
                            "--detach",
                            "--no-deps",
                            "--force-recreate",
                            "retrieval-indexer",
                            profile="rag",
                            env_overrides=runtime_overrides,
                        )
                    self._compose(
                        str(old_image),
                        "up",
                        "--detach",
                        "--no-deps",
                        "--force-recreate",
                        "api",
                        env_overrides=runtime_overrides,
                    )
                    self._wait_ready("http://127.0.0.1:18000/health/ready")
                else:
                    self._stop_api_if_running()
                self._maintenance_off()
                self._journal(
                    "rolled_back",
                    interrupted_deployment_recovered=True,
                    database_restored=False,
                    finished_at=datetime.now(UTC).isoformat(),
                )
                return "rolled_back"
            except Exception as error:  # noqa: BLE001 - keep traffic blocked after uncertain recovery
                self._journal(
                    "recovery_required",
                    recovery_error_type=type(error).__name__,
                    database_restored=False,
                )
                raise DeploymentError(
                    "recovery failed; maintenance remains enabled and the database was not restored"
                ) from None

    def _copy_incoming_to_stage(
        self, release_id: str, release: Release, payload: Mapping[str, bytes]
    ) -> Path:
        store = self.paths.root / "releases"
        _check_path_chain(store)
        store.mkdir(parents=True, exist_ok=True, mode=0o755)
        destination = store / release_id
        release_metadata = {
            "schema_version": release.schema_version,
            "release_id": release.release_id,
            "image": release.image,
            "web_archive": release.web_archive,
            "web_sha256": release.web_sha256,
            "model_manifest": release.model_manifest,
            "model_manifest_sha256": release.model_manifest_sha256,
        }
        if release.retrieval_manifest is not None:
            release_metadata.update(
                retrieval_manifest=release.retrieval_manifest,
                retrieval_manifest_sha256=release.retrieval_manifest_sha256,
            )
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_dir():
                raise DeploymentError("existing release path is not a safe directory")
            metadata = _read_json(destination / "release.json")
            if metadata != release_metadata:
                raise DeploymentError(
                    "existing release directory differs from this release"
                )
            for field, digest in (
                (release.web_archive, release.web_sha256),
                (release.model_manifest, release.model_manifest_sha256),
                *(
                    ((release.retrieval_manifest, release.retrieval_manifest_sha256),)
                    if release.retrieval_manifest is not None
                    and release.retrieval_manifest_sha256 is not None
                    else ()
                ),
            ):
                stored = destination / field
                if (
                    stored.is_symlink()
                    or not stored.is_file()
                    or _sha256(stored) != digest
                ):
                    raise DeploymentError(
                        "existing release payload differs from this release"
                    )
            _assert_safe_tree(destination)
            return destination

        temporary = Path(tempfile.mkdtemp(prefix=f".{release_id}.", dir=store))
        try:
            os.chmod(temporary, 0o755)
            (temporary / "release.json").write_text(
                json.dumps(release_metadata, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            (temporary / release.web_archive).write_bytes(payload[release.web_archive])
            (temporary / release.model_manifest).write_bytes(
                payload[release.model_manifest]
            )
            if release.retrieval_manifest is not None:
                (temporary / release.retrieval_manifest).write_bytes(
                    payload[release.retrieval_manifest]
                )
            os.chmod(temporary / "release.json", 0o644)
            os.chmod(temporary / release.web_archive, 0o644)
            os.chmod(temporary / release.model_manifest, 0o644)
            if release.retrieval_manifest is not None:
                os.chmod(temporary / release.retrieval_manifest, 0o644)
            safe_extract_web_archive(temporary / release.web_archive, temporary / "web")
            _assert_safe_tree(temporary)
            os.rename(temporary, destination)
            directory_fd = os.open(store, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return destination
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _validate_model_tree(self, model_path: Path) -> None:
        if model_path.is_symlink() or not model_path.is_dir():
            raise DeploymentError(
                "Hugging Face downloader did not produce the expected model directory"
            )
        files = list(model_path.iterdir())
        expected = {
            "config.json",
            "metadata.json",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
        }
        if {path.name for path in files} != expected:
            raise DeploymentError(
                "downloaded classifier files do not match the pinned manifest"
            )
        for path in files:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise DeploymentError(
                    "downloaded classifier contains a non-regular file"
                )
        for directory in (model_path, *model_path.parents):
            if directory == self.paths.root.parent:
                break
            if directory.is_symlink():
                raise DeploymentError("downloaded model path contains a symlink")
        os.chmod(model_path.parent, 0o755)
        for path in files:
            os.chmod(path, 0o444)
        os.chmod(model_path, 0o555)

    def _download_model(
        self, release: Release, inputs: ReleaseInputs, release_dir: Path
    ) -> Path:
        models = self.paths.root / "models"
        models.mkdir(parents=True, exist_ok=True, mode=0o755)
        _check_path_chain(models)
        model_path = models / inputs.model_id / inputs.model_revision
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--user",
            "0:0",
            "--env-file",
            str(self.paths.config / "hf-download.env"),
            "--mount",
            f"type=bind,src={models},dst=/models",
            "--mount",
            f"type=bind,src={release_dir / release.model_manifest},dst=/model-release.json,readonly",
            "--entrypoint",
            "python",
            release.image,
            "scripts/deployment_model.py",
            "--manifest",
            "/model-release.json",
            "--root",
            "/models",
        ]
        self._run("Hugging Face model preparation", command, timeout=1800)
        self._validate_model_tree(model_path)
        return model_path

    def _download_embedding(
        self, release: Release, inputs: ReleaseInputs, release_dir: Path
    ) -> Path | None:
        if inputs.retrieval_release is None or release.retrieval_manifest is None:
            return None
        models = self.paths.embedding_models
        models.mkdir(parents=True, exist_ok=True, mode=0o755)
        _check_path_chain(models)
        model = inputs.retrieval_release.model
        model_path = models / model.model_id.replace("/", "--") / model.revision
        manifest_path = release_dir / release.retrieval_manifest
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--user",
            "0:0",
            "--mount",
            f"type=bind,src={models},dst=/models/embeddings",
            "--mount",
            f"type=bind,src={manifest_path},dst=/retrieval-release.json,readonly",
            "--entrypoint",
            "python",
            release.image,
            "scripts/deployment_embedding.py",
            "--manifest",
            "/retrieval-release.json",
            "--root",
            "/models/embeddings",
        ]
        self._run("retrieval embedding preparation", command, timeout=1800)
        self._validate_embedding_tree(model_path, inputs.retrieval_release)
        return model_path

    @staticmethod
    def _validate_embedding_tree(model_path: Path, retrieval: RetrievalRelease) -> None:
        try:
            validate_retrieval_model_directory(model_path, retrieval)
        except EmbeddingReleaseError as error:
            raise DeploymentError(
                "retrieval model directory failed validation"
            ) from error
        for path in model_path.iterdir():
            if path.is_dir():
                for child in path.iterdir():
                    os.chmod(child, 0o444)
                os.chmod(path, 0o555)
            else:
                os.chmod(path, 0o444)
        os.chmod(model_path, 0o555)

    def _prepare_retrieval_baseline(
        self,
        image: str,
        release_id: str,
        retrieval: RetrievalRelease,
        embedding_path: Path,
    ) -> dict[str, object]:
        source = self.paths.baseline
        if source.is_symlink() or not source.is_file():
            raise DeploymentError("immutable host company baseline is unavailable")
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        baseline_root = self.paths.retrieval_baselines
        baseline_root.mkdir(parents=True, exist_ok=True, mode=0o755)
        _check_path_chain(baseline_root)
        os.chown(baseline_root, 10001, 10001)
        os.chmod(baseline_root, 0o750)
        model = retrieval.model
        container_model = (
            f"/models/embeddings/{model.model_id.replace('/', '--')}/{model.revision}"
        )
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
            f"type=bind,src={source},dst=/retrieval-source/documents.jsonl,readonly",
            "--mount",
            f"type=bind,src={embedding_path},dst={container_model},readonly",
            "--mount",
            f"type=bind,src={baseline_root},dst=/retrieval-baselines",
            "--env",
            f"SANAEBI_EMBEDDING_PATH={container_model}",
            image,
            "python",
            "-m",
            "scripts.prepare_retrieval_baseline",
            "--source",
            "/retrieval-source/documents.jsonl",
            "--output-root",
            "/retrieval-baselines",
        ]
        result = self._run("host baseline embedding preparation", command, timeout=1800)
        try:
            report = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise DeploymentError(
                "baseline preparation returned invalid metadata"
            ) from error
        if (
            not isinstance(report, dict)
            or report.get("status") != "ready"
            or report.get("source_sha256") != source_sha
            or not isinstance(report.get("spec_id"), str)
            or SHA256.fullmatch(report["spec_id"]) is None
            or type(report.get("source_document_count")) is not int
            or type(report.get("chunk_count")) is not int
        ):
            raise DeploymentError("baseline preparation did not verify host source")
        spec_id = report["spec_id"]
        bundle = (
            baseline_root
            / f"schema-v{retrieval.baseline_schema_version}"
            / spec_id
            / source_sha
            / "baseline.sqlite3"
        )
        bundle_in_container = (
            f"/retrieval-baselines/schema-v{retrieval.baseline_schema_version}/"
            f"{spec_id}/{source_sha}/baseline.sqlite3"
        )
        if report.get("bundle") != bundle_in_container:
            raise DeploymentError("baseline bundle path does not match its metadata")
        try:
            bundle_info = bundle.lstat()
        except OSError as error:
            raise DeploymentError("prepared baseline bundle is unavailable") from error
        if not stat.S_ISREG(bundle_info.st_mode):
            raise DeploymentError("prepared baseline bundle is unsafe")
        binding = {
            "schema_version": 1,
            "release_id": release_id,
            "model_id": model.model_id,
            "revision": model.revision,
            "baseline_schema_version": retrieval.baseline_schema_version,
            "index_schema_version": retrieval.index_schema_version,
            "spec_id": spec_id,
            "source_sha256": source_sha,
            "source_document_count": report["source_document_count"],
            "chunk_count": report["chunk_count"],
        }
        self._atomic_write_json(
            self.paths.retrieval_bindings / f"{release_id}.json", binding
        )
        return {**binding, "bundle_path": bundle, "embedding_path": embedding_path}

    def _copy_baseline_from_image(self, image: str) -> None:
        baseline = self.paths.baseline
        if baseline.exists() or baseline.is_symlink():
            if baseline.is_symlink() or not baseline.is_file():
                raise DeploymentError("existing immutable baseline is unsafe")
            return
        baseline.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        container_name = f"sanaebi-baseline-{os.getpid()}-{time.monotonic_ns()}"
        temp = baseline.parent / f".{baseline.name}.{os.getpid()}.partial"
        if temp.exists() or temp.is_symlink():
            raise DeploymentError("baseline temporary path already exists")
        try:
            self._run(
                "baseline container creation",
                ["docker", "create", "--name", container_name, image],
            )
            self._run(
                "baseline extraction",
                [
                    "docker",
                    "cp",
                    f"{container_name}:/app/data/company-knowledge/documents.jsonl",
                    str(temp),
                ],
            )
            info = temp.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
                raise DeploymentError("image baseline is not a non-empty regular file")
            os.chmod(temp, 0o440)
            os.chown(temp, 0, 10001)
            os.replace(temp, baseline)
            os.chown(baseline.parent, 0, 10001)
            os.chmod(baseline.parent, 0o750)
        finally:
            try:
                self._run(
                    "baseline container cleanup",
                    ["docker", "rm", "--force", container_name],
                )
            except DeploymentError:
                pass
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def _initialize_database_if_missing(self, image: str) -> bool:
        self.paths.data.mkdir(parents=True, exist_ok=True, mode=0o750)
        runtime_info = self.paths.data.lstat()
        if not stat.S_ISDIR(runtime_info.st_mode):
            raise DeploymentError("runtime database directory is not a safe directory")
        os.chown(self.paths.data, 10001, 10001)
        os.chmod(self.paths.data, 0o750)
        retrieval_baselines = self.paths.retrieval_baselines
        retrieval_baselines.mkdir(parents=True, exist_ok=True, mode=0o750)
        baseline_info = retrieval_baselines.lstat()
        if not stat.S_ISDIR(baseline_info.st_mode):
            raise DeploymentError(
                "retrieval baseline directory is not a safe directory"
            )
        os.chown(retrieval_baselines, 10001, 10001)
        os.chmod(retrieval_baselines, 0o750)
        self._copy_baseline_from_image(image)
        database = self.paths.database
        if database.exists() or database.is_symlink():
            if database.is_symlink() or not database.is_file():
                raise DeploymentError("document database path is not a regular file")
            return False
        temporary_data = self.paths.data / f".seed-{os.getpid()}-{time.monotonic_ns()}"
        temporary_data.mkdir(mode=0o700)
        os.chown(temporary_data, 10001, 10001)
        baseline = self.paths.baseline
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
            f"type=bind,src={temporary_data},dst=/data",
            "--mount",
            f"type=bind,src={baseline},dst=/app/data/company-knowledge/documents.jsonl,readonly",
            "--env",
            "SANAEBI_DOCUMENT_DB=/data/documents.sqlite3",
            "--entrypoint",
            "python",
            image,
            "scripts/import_company_knowledge.py",
            "--source",
            "/app/data/company-knowledge/documents.jsonl",
            "--database",
            "/data/documents.sqlite3",
            "--apply",
            "--publish-imported",
        ]
        try:
            self._run("initial document import", command, timeout=600)
            seeded = temporary_data / "documents.sqlite3"
            if seeded.is_symlink() or not seeded.is_file():
                raise DeploymentError(
                    "initial document import did not create a database"
                )
            info = seeded.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise DeploymentError("initial document database is not a regular file")
            if database.exists() or database.is_symlink():
                raise DeploymentError(
                    "document database appeared during initial import"
                )
            os.link(seeded, database, follow_symlinks=False)
            os.chown(database, 10001, 10001)
            os.chmod(database, 0o660)
            return True
        finally:
            shutil.rmtree(temporary_data, ignore_errors=True)

    def _preflight_candidate(
        self,
        image: str,
        model_path: Path,
        release_id: str,
        retrieval_binding: Mapping[str, object] | None = None,
    ) -> None:
        data = self.paths.data / f".preflight-{release_id}"
        if data.exists() or data.is_symlink():
            raise DeploymentError("candidate preflight directory already exists")
        data.mkdir(mode=0o700)
        container = f"sanaebi-preflight-{release_id}"
        started = False
        try:
            os.chown(data, 10001, 10001)
            candidate_database = data / "documents.sqlite3"
            if self.paths.database.exists():
                snapshot_sqlite_database(self.paths.database, candidate_database)
                os.chown(candidate_database, 10001, 10001)
                os.chmod(candidate_database, 0o660)
            if retrieval_binding is not None:
                self._preflight_candidate_index(image, data, retrieval_binding)
            mode = "rag" if retrieval_binding is not None else "full"
            command = [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                "--pull=never",
                "--network",
                "host",
                "--user",
                "10001:10001",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=256m",
                "--env-file",
                str(self.paths.config / "api.env"),
                "--env",
                "SANAEBI_DOCUMENT_DB=/data/documents.sqlite3",
                "--env",
                "SANAEBI_GENERATION_BUDGET_DB=/data/generation-budget.sqlite3",
                "--env",
                "SANAEBI_CLASSIFIER_PATH=/models/classifier",
                "--env",
                f"SANAEBI_RETRIEVAL_MODE={mode}",
                "--env",
                "SANAEBI_RETRIEVAL_ROOT=/data/retrieval",
                "--env",
                "SANAEBI_PUBLIC_DEMO=1",
                "--env",
                "SANAEBI_DAILY_GENERATION_LIMIT=1000",
                "--env",
                "TRACE_DIR=",
                "--env",
                "TRACE_FULL_PROMPT=0",
                "--mount",
                f"type=bind,src={data},dst=/data",
                "--mount",
                f"type=bind,src={model_path},dst=/models/classifier,readonly",
            ]
            if retrieval_binding is not None:
                embedding_path = Path(retrieval_binding["embedding_path"])
                bundle_path = Path(retrieval_binding["bundle_path"])
                command.extend(
                    [
                        "--env",
                        "SANAEBI_RETRIEVAL_BASELINE=/retrieval-baseline/baseline.sqlite3",
                        "--env",
                        "SANAEBI_RETRIEVAL_SOURCE=/retrieval-source/documents.jsonl",
                        "--env",
                        "SANAEBI_EMBEDDING_PATH=/models/embedding",
                        "--mount",
                        f"type=bind,src={self.paths.baseline},dst=/retrieval-source/documents.jsonl,readonly",
                        "--mount",
                        f"type=bind,src={bundle_path},dst=/retrieval-baseline/baseline.sqlite3,readonly",
                        "--mount",
                        f"type=bind,src={embedding_path},dst=/models/embedding,readonly",
                    ]
                )
            command.extend(
                [
                    "--entrypoint",
                    "python",
                    image,
                    "-m",
                    "uvicorn",
                    "app.fastapi_main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18001",
                    "--workers",
                    "1",
                    "--proxy-headers",
                    "--forwarded-allow-ips",
                    "127.0.0.1",
                    "--no-access-log",
                    "--timeout-graceful-shutdown",
                    "240",
                ]
            )
            self._run("candidate startup", command)
            started = True
            self._wait_ready("http://127.0.0.1:18001/health/ready")
        finally:
            try:
                self._run(
                    "candidate cleanup",
                    ["docker", "rm", "--force", container],
                    timeout=60,
                )
            except DeploymentError:
                if started:
                    raise
            shutil.rmtree(data, ignore_errors=True)

    def _preflight_candidate_index(
        self,
        image: str,
        data: Path,
        binding: Mapping[str, object],
    ) -> None:
        source = self.paths.baseline
        bundle = Path(binding["bundle_path"])
        embedding = Path(binding["embedding_path"])
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
            f"type=bind,src={data},dst=/data",
            "--mount",
            f"type=bind,src={source},dst=/retrieval-source/documents.jsonl,readonly",
            "--mount",
            f"type=bind,src={bundle},dst=/retrieval-baseline/baseline.sqlite3,readonly",
            "--mount",
            f"type=bind,src={embedding},dst=/models/embedding,readonly",
            "--env",
            "SANAEBI_DOCUMENT_DB=/data/documents.sqlite3",
            "--env",
            "SANAEBI_RETRIEVAL_ROOT=/data/retrieval",
            "--env",
            "SANAEBI_RETRIEVAL_BASELINE=/retrieval-baseline/baseline.sqlite3",
            "--env",
            "SANAEBI_RETRIEVAL_SOURCE=/retrieval-source/documents.jsonl",
            "--env",
            "SANAEBI_EMBEDDING_PATH=/models/embedding",
            "--entrypoint",
            "python",
            image,
            "-m",
            "scripts.index_documents",
            "--once",
        ]
        # Read-only index access requires the candidate schema. Migrate only the
        # isolated DB copy, just as API startup will do after the live backup.
        initialize = command[:-3] + [
            "-c",
            (
                "from app.documents.repository import DocumentRepository; "
                "from app.settings import get_document_database_path; "
                "DocumentRepository(get_document_database_path()).initialize()"
            ),
        ]
        self._run("candidate document schema preparation", initialize, timeout=600)
        result = self._run("candidate retrieval index", command, timeout=1800)
        try:
            status = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise DeploymentError("candidate index returned invalid status") from error
        if (
            not isinstance(status, dict)
            or status.get("ready") is not True
            or status.get("missing") != 0
        ):
            raise DeploymentError("candidate retrieval index is not ready")

    def _wait_ready(self, url: str, *, timeout: int = READY_TIMEOUT_SECONDS) -> None:
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                with self.urlopen(url, timeout=5) as response:
                    if response.status == 200:
                        return
                    last_error = f"HTTP {response.status}"
            except (OSError, urllib.error.URLError, TimeoutError) as error:
                last_error = type(error).__name__
            self.sleep(2)
        raise DeploymentError(
            f"API readiness check timed out ({last_error or 'no response'})"
        )

    def _configured_retrieval_mode(self) -> str | None:
        path = self.paths.config / "api.env"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise DeploymentError("API environment file is unavailable") from error
        configured = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != "SANAEBI_RETRIEVAL_MODE":
                continue
            if configured is not None:
                raise DeploymentError("retrieval mode is configured more than once")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            configured = value
        if configured is not None and configured not in {"full", "rag"}:
            raise DeploymentError("retrieval mode must be full or rag")
        return configured

    def _active_api_retrieval_mode(self) -> str:
        """Read the mode from the running container, not a possibly edited env file."""
        result = self.runner(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .Config.Env}}",
                "sanaebi-api",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=self._docker_env(),
        )
        if result.returncode:
            raise DeploymentError("active API runtime mode could not be inspected")
        try:
            environment = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise DeploymentError("active API runtime metadata is invalid") from error
        if not isinstance(environment, list) or any(
            not isinstance(value, str) for value in environment
        ):
            raise DeploymentError("active API runtime metadata is invalid")
        configured = [
            value.partition("=")[2]
            for value in environment
            if value.startswith("SANAEBI_RETRIEVAL_MODE=")
        ]
        if len(configured) > 1:
            raise DeploymentError(
                "active API retrieval mode is configured more than once"
            )
        mode = configured[0] if configured else "full"
        if mode not in {"full", "rag"}:
            raise DeploymentError("active API retrieval mode is invalid")
        return mode

    def _release_retrieval(
        self, release_id: str
    ) -> tuple[Release, RetrievalRelease | None]:
        directory = self.paths.root / "releases" / release_id
        try:
            release_raw = (directory / "release.json").read_bytes()
            release = parse_release_manifest(release_raw, release_id)
        except (OSError, DeploymentError) as error:
            raise DeploymentError("active release metadata is invalid") from error
        if release.retrieval_manifest is None:
            return release, None
        descriptor = directory / release.retrieval_manifest
        try:
            descriptor_raw = descriptor.read_bytes()
        except OSError as error:
            raise DeploymentError(
                "active retrieval descriptor is unavailable"
            ) from error
        if (
            hashlib.sha256(descriptor_raw).hexdigest()
            != release.retrieval_manifest_sha256
        ):
            raise DeploymentError("active retrieval descriptor hash does not match")
        try:
            retrieval = parse_retrieval_manifest(descriptor_raw)
        except EmbeddingReleaseError as error:
            raise DeploymentError("active retrieval descriptor is invalid") from error
        return release, retrieval

    def _binding_for_release(
        self,
        release_id: str,
        retrieval: RetrievalRelease,
        *,
        prepared: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if prepared is None:
            path = self.paths.retrieval_bindings / f"{release_id}.json"
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise DeploymentError("retrieval binding is unsafe")
                binding = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise DeploymentError(
                    "release retrieval binding is unavailable"
                ) from error
        else:
            binding = dict(prepared)
        model = retrieval.model
        if (
            not isinstance(binding, dict)
            or binding.get("schema_version") != 1
            or binding.get("release_id") != release_id
            or binding.get("model_id") != model.model_id
            or binding.get("revision") != model.revision
            or binding.get("baseline_schema_version")
            != retrieval.baseline_schema_version
            or binding.get("index_schema_version") != retrieval.index_schema_version
            or not isinstance(binding.get("spec_id"), str)
            or SHA256.fullmatch(binding["spec_id"]) is None
            or not isinstance(binding.get("source_sha256"), str)
            or SHA256.fullmatch(binding["source_sha256"]) is None
        ):
            raise DeploymentError("release retrieval binding does not match its model")
        try:
            source_info = self.paths.baseline.lstat()
            source_sha = hashlib.sha256(self.paths.baseline.read_bytes()).hexdigest()
        except OSError as error:
            raise DeploymentError("host baseline is unavailable") from error
        if (
            not stat.S_ISREG(source_info.st_mode)
            or source_sha != binding["source_sha256"]
        ):
            raise DeploymentError("host baseline differs from the retrieval binding")
        bundle = (
            self.paths.retrieval_baselines
            / f"schema-v{retrieval.baseline_schema_version}"
            / str(binding["spec_id"])
            / str(binding["source_sha256"])
            / "baseline.sqlite3"
        )
        embedding = (
            self.paths.embedding_models
            / model.model_id.replace("/", "--")
            / model.revision
        )
        for path, name in ((bundle, "baseline bundle"), (embedding, "embedding model")):
            try:
                info = path.lstat()
            except OSError as error:
                raise DeploymentError(f"release {name} is unavailable") from error
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISDIR(info.st_mode)
                and name == "embedding model"
            ):
                raise DeploymentError(f"release {name} is unsafe")
            if name == "baseline bundle" and not stat.S_ISREG(info.st_mode):
                raise DeploymentError("release baseline bundle is unsafe")
        return {**binding, "bundle_path": bundle, "embedding_path": embedding}

    def _runtime_overrides(
        self,
        release_id: str,
        *,
        prepared: Mapping[str, object] | None = None,
        force_mode: str | None = None,
    ) -> tuple[str, dict[str, str], dict[str, object] | None]:
        _, retrieval = self._release_retrieval(release_id)
        if retrieval is None:
            requested_mode = "full"
        else:
            requested_mode = (
                force_mode
                or self._configured_retrieval_mode()
                or retrieval.default_mode
            )
        binding = None
        if retrieval is not None and (prepared is not None or requested_mode == "rag"):
            binding = self._binding_for_release(
                release_id, retrieval, prepared=prepared
            )
        if requested_mode == "rag" and binding is None:
            raise DeploymentError("rag mode requires a prepared release binding")
        model_path = "/models/embeddings/not-ready"
        bundle_path = "/srv/sanaebi/retrieval-baselines/not-ready.sqlite3"
        bundle_container_path = "/retrieval-baselines/not-ready.sqlite3"
        if retrieval is not None:
            model = retrieval.model
            model_path = f"/models/embeddings/{model.model_id.replace('/', '--')}/{model.revision}"
        if binding is not None:
            bundle_path = str(binding["bundle_path"])
            try:
                bundle_relative = (
                    Path(bundle_path)
                    .resolve()
                    .relative_to(self.paths.retrieval_baselines.resolve())
                )
            except ValueError as error:
                raise DeploymentError(
                    "release retrieval bundle escaped its root"
                ) from error
            bundle_container_path = str(
                PurePosixPath("/retrieval-baselines")
                / PurePosixPath(bundle_relative.as_posix())
            )
        overrides = {
            "SANAEBI_RETRIEVAL_MODE": requested_mode,
            "SANAEBI_RETRIEVAL_ROOT": "/data/retrieval",
            "SANAEBI_EMBEDDING_PATH": model_path,
            "SANAEBI_RETRIEVAL_BUNDLE_HOST_PATH": bundle_path,
            "SANAEBI_RETRIEVAL_SOURCE_HOST_PATH": str(self.paths.baseline),
            "SANAEBI_RETRIEVAL_BUNDLE_CONTAINER_PATH": bundle_container_path,
            "SANAEBI_RETRIEVAL_BASELINES_HOST_DIR": str(self.paths.retrieval_baselines),
            "SANAEBI_RETRIEVAL_SOURCE_HOST_DIR": str(self.paths.baseline.parent),
        }
        return requested_mode, overrides, binding

    def _index_current_documents_once(
        self,
        image: str,
        binding: Mapping[str, object],
        overrides: Mapping[str, str],
    ) -> None:
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
            f"type=bind,src={self.paths.data},dst=/data",
            "--mount",
            f"type=bind,src={self.paths.baseline},dst=/retrieval-source/documents.jsonl,readonly",
            "--mount",
            f"type=bind,src={binding['bundle_path']},dst=/retrieval-baseline/baseline.sqlite3,readonly",
            "--mount",
            f"type=bind,src={binding['embedding_path']},dst=/models/embedding,readonly",
            "--env",
            "SANAEBI_DOCUMENT_DB=/data/documents.sqlite3",
            "--env",
            "SANAEBI_RETRIEVAL_ROOT=/data/retrieval",
            "--env",
            "SANAEBI_RETRIEVAL_BASELINE=/retrieval-baseline/baseline.sqlite3",
            "--env",
            "SANAEBI_RETRIEVAL_SOURCE=/retrieval-source/documents.jsonl",
            "--env",
            "SANAEBI_EMBEDDING_PATH=/models/embedding",
            "--entrypoint",
            "python",
            image,
            "-m",
            "scripts.index_documents",
            "--once",
        ]
        result = self._run(
            "production retrieval index preparation", command, timeout=1800
        )
        try:
            status = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise DeploymentError("production index returned invalid status") from error
        if (
            not isinstance(status, dict)
            or status.get("ready") is not True
            or status.get("missing") != 0
        ):
            raise DeploymentError("production retrieval index is not ready")

    def _stop_indexer_if_running(self) -> None:
        result = self.runner(
            [
                "docker",
                "ps",
                "--quiet",
                "--filter",
                "name=^/sanaebi-retrieval-indexer$",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=self._docker_env(),
        )
        if result.returncode:
            raise DeploymentError("retrieval worker inspection failed")
        if result.stdout.strip():
            self._run(
                "retrieval worker shutdown",
                [
                    "docker",
                    "stop",
                    "--time",
                    str(STOP_TIMEOUT_SECONDS),
                    "sanaebi-retrieval-indexer",
                ],
                timeout=STOP_TIMEOUT_SECONDS + 30,
            )

    def _compose(
        self,
        image: str,
        *arguments: str,
        timeout: int = 600,
        profile: str | None = None,
        env_overrides: Mapping[str, str] | None = None,
    ) -> None:
        command = [
            "docker",
            "compose",
            "--project-name",
            "sanaebi",
            "--file",
            str(self.paths.config / "compose.yaml"),
        ]
        if profile is not None:
            command.extend(["--profile", profile])
        command.extend(arguments)
        result = self.runner(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=self._docker_env(SANAEBI_IMAGE=image, **dict(env_overrides or {})),
        )
        if result.returncode:
            raise DeploymentError(
                f"Docker Compose operation failed with exit code {result.returncode}"
            )

    def _publish_static_assets(self, release_dir: Path) -> None:
        static_root = release_dir / "web" / "_next" / "static"
        _assert_safe_tree(static_root)
        assets_root = self.paths.root / "assets" / "_next" / "static"
        _check_path_chain(assets_root)
        assets_root.mkdir(parents=True, exist_ok=True, mode=0o755)
        for source in sorted(static_root.rglob("*")):
            if source.is_dir():
                continue
            relative = source.relative_to(static_root)
            _atomic_copy(source, assets_root / relative)

    def _maintenance_on(self, release_id: str) -> None:
        marker = self.paths.root / "maintenance"
        if marker.exists() or marker.is_symlink():
            raise DeploymentError("maintenance marker already exists")
        descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as file:
                file.write(f"deployment {release_id}\n")
                file.flush()
                os.fsync(file.fileno())
            self._fsync_directory(marker.parent)
        except BaseException:
            marker.unlink(missing_ok=True)
            raise

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _maintenance_off(self) -> None:
        marker = self.paths.root / "maintenance"
        if not marker.exists() and not marker.is_symlink():
            return
        info = marker.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise DeploymentError("maintenance marker was replaced by an unsafe path")
        marker.unlink()
        self._fsync_directory(marker.parent)

    def _promote_web(self, release_id: str) -> None:
        current = self.paths.root / "current"
        previous = self.paths.root / "previous"
        old_current = _pointer_target(current, "releases/")
        _pointer_target(previous, "releases/")
        if old_current is not None:
            _atomic_symlink(previous, old_current)
        _atomic_symlink(current, f"releases/{release_id}")

    def _set_model_pointer(self, inputs: ReleaseInputs | None) -> None:
        target = (
            f"{inputs.model_id}/{inputs.model_revision}" if inputs is not None else None
        )
        _atomic_symlink(self.paths.root / "models" / "current", target)

    def _active_release(self) -> tuple[str, str] | None:
        target = _pointer_target(self.paths.root / "current", "releases/")
        if target is None:
            return None
        release_id = target.removeprefix("releases/")
        if not RELEASE_ID.fullmatch(release_id):
            raise DeploymentError("current release pointer has an invalid identity")
        release = _read_json(self.paths.root / target / "release.json")
        image = release.get("image")
        if release.get("release_id") != release_id or not isinstance(image, str):
            raise DeploymentError("current release metadata does not match its pointer")
        if EXPECTED_IMAGE.fullmatch(image) is None:
            raise DeploymentError("current release image is not digest-pinned")
        return release_id, image

    def _restore_pointer(self, path: Path, target: str | None) -> None:
        _atomic_symlink(path, target)

    def _stop_api_if_running(self) -> None:
        result = self.runner(
            ["docker", "ps", "--quiet", "--filter", "name=^/sanaebi-api$"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=self._docker_env(),
        )
        if result.returncode:
            raise DeploymentError(
                f"API container inspection failed with exit code {result.returncode}"
            )
        if result.stdout.strip():
            self._run(
                "failed API shutdown",
                ["docker", "stop", "--time", str(STOP_TIMEOUT_SECONDS), "sanaebi-api"],
                timeout=STOP_TIMEOUT_SECONDS + 30,
            )

    def _rollback(
        self,
        *,
        old_release: tuple[str, str] | None,
        old_current: str | None,
        old_previous: str | None,
        old_model: str | None,
        release_id: str,
        old_runtime_overrides: Mapping[str, str] | None = None,
    ) -> bool:
        errors = []
        try:
            self._stop_indexer_if_running()
        except Exception as error:  # noqa: BLE001 - do not restore pointers under a live writer
            errors.append(type(error).__name__)
        if errors:
            self._journal(
                "recovery_required",
                failed_release_id=release_id,
                rollback_error_types=errors,
                database_restored=False,
            )
            return False
        try:
            self._restore_pointer(self.paths.root / "models" / "current", old_model)
        except Exception as error:  # noqa: BLE001 - best effort recovery continues
            errors.append(type(error).__name__)
        try:
            self._restore_pointer(self.paths.root / "current", old_current)
            self._restore_pointer(self.paths.root / "previous", old_previous)
        except Exception as error:  # noqa: BLE001 - best effort recovery continues
            errors.append(type(error).__name__)
        if old_release is not None:
            try:
                _, old_image = old_release
                if old_runtime_overrides is None:
                    _, old_runtime_overrides, _ = self._runtime_overrides(
                        old_release[0]
                    )
                if old_runtime_overrides.get("SANAEBI_RETRIEVAL_MODE") == "rag":
                    self._compose(
                        old_image,
                        "up",
                        "--detach",
                        "--no-deps",
                        "--force-recreate",
                        "retrieval-indexer",
                        profile="rag",
                        env_overrides=old_runtime_overrides,
                    )
                self._compose(
                    old_image,
                    "up",
                    "--detach",
                    "--no-deps",
                    "--force-recreate",
                    "api",
                    env_overrides=old_runtime_overrides,
                )
                self._wait_ready("http://127.0.0.1:18000/health/ready")
            except Exception as error:  # noqa: BLE001 - retain outage on uncertain rollback
                errors.append(type(error).__name__)
        else:
            try:
                self._stop_api_if_running()
            except Exception as error:  # noqa: BLE001
                errors.append(type(error).__name__)
        success = not errors
        if success:
            try:
                self._maintenance_off()
            except Exception as error:  # noqa: BLE001
                errors.append(type(error).__name__)
                success = False
        self._journal(
            "rolled_back" if success else "recovery_required",
            failed_release_id=release_id,
            rollback_error_types=errors,
            database_restored=False,
        )
        return success

    def deploy(self, release_id: str) -> None:
        if not RELEASE_ID.fullmatch(release_id):
            raise DeploymentError(
                "release id must be a full commit SHA followed by a run id"
            )
        self._require_root_and_trusted_inputs()
        with operation_lock(self.paths.operation_lock):
            self._check_no_incomplete_journal()
            if (self.paths.root / "maintenance").exists():
                raise DeploymentError("maintenance mode is already active")
            inputs, payload = load_release_inputs(
                self.paths.root / "incoming" / "releases", release_id
            )
            release_dir = self._copy_incoming_to_stage(
                release_id, inputs.release, payload
            )
            old_release = self._active_release()
            old_current = _pointer_target(self.paths.root / "current", "releases/")
            old_previous = _pointer_target(self.paths.root / "previous", "releases/")
            old_model = _pointer_target(self.paths.root / "models" / "current", "")
            if old_release is not None:
                active_mode = self._active_api_retrieval_mode()
                _, old_runtime_overrides, _ = self._runtime_overrides(
                    old_release[0], force_mode=active_mode
                )
            else:
                old_runtime_overrides = None
            self._active_journal = {
                "schema_version": 1,
                "release_id": release_id,
                "previous_release_id": old_release[0] if old_release else None,
                "image": inputs.release.image,
                "model_id": inputs.model_id,
                "model_revision": inputs.model_revision,
                # Save every rollback input before any model, pointer, service, or
                # maintenance mutation. A power loss can then be recovered from
                # this root-owned journal without guessing the prior release.
                "candidate_image": inputs.release.image,
                "candidate_model_id": inputs.model_id,
                "candidate_model_revision": inputs.model_revision,
                "candidate_preflight_container": f"sanaebi-preflight-{release_id}",
                "candidate_preflight_data": f".preflight-{release_id}",
                "old_current_target": old_current,
                "old_previous_target": old_previous,
                "old_model_target": old_model,
                "old_release_image": old_release[1] if old_release else None,
                "old_retrieval_mode": (
                    old_runtime_overrides.get("SANAEBI_RETRIEVAL_MODE")
                    if old_runtime_overrides
                    else "full"
                ),
                "started_at": datetime.now(UTC).isoformat(),
            }
            self._journal("release_validated")
            maintenance_started = False
            try:
                self._journal("pulling_image")
                self._run("API image pull", ["docker", "pull", inputs.release.image])
                model_path = self._download_model(inputs.release, inputs, release_dir)
                embedding_path = self._download_embedding(
                    inputs.release, inputs, release_dir
                )
                retrieval_binding = None
                if inputs.retrieval_release is not None:
                    if embedding_path is None:
                        raise DeploymentError(
                            "retrieval embedding model was not prepared"
                        )
                    # The immutable host source is created from the image only on
                    # first deployment. Prepare it before deriving the RAG bundle.
                    self._copy_baseline_from_image(inputs.release.image)
                    retrieval_binding = self._prepare_retrieval_baseline(
                        inputs.release.image,
                        release_id,
                        inputs.retrieval_release,
                        embedding_path,
                    )
                new_mode, new_runtime_overrides, _ = self._runtime_overrides(
                    release_id, prepared=retrieval_binding
                )
                self._journal("model_ready")
                self._initialize_database_if_missing(inputs.release.image)
                self._preflight_candidate(
                    inputs.release.image,
                    model_path,
                    release_id,
                    retrieval_binding=retrieval_binding,
                )
                # Ensure Docker Compose can render the exact root-owned production file.
                self._compose(
                    inputs.release.image,
                    "config",
                    "--quiet",
                    env_overrides=new_runtime_overrides,
                )
                self._publish_static_assets(release_dir)
                self._journal("candidate_ready")

                self._maintenance_on(release_id)
                maintenance_started = True
                self._journal("maintenance_enabled")
                if old_release is not None:
                    self._compose(
                        old_release[1],
                        "stop",
                        "--timeout",
                        str(STOP_TIMEOUT_SECONDS),
                        "api",
                        timeout=STOP_TIMEOUT_SECONDS + 30,
                        env_overrides=old_runtime_overrides,
                    )
                self._stop_indexer_if_running()
                self._journal("previous_api_stopped")
                if self.paths.database.exists():
                    backup = create_database_backup(
                        self.paths.database,
                        self.paths.backups / "deploy",
                        label=f"pre-deploy-{release_id[:12]}",
                    )
                    self._active_journal["database_backup"] = str(backup)
                self._journal("database_backed_up")
                self._set_model_pointer(inputs)
                if new_mode == "rag":
                    if retrieval_binding is None:
                        raise DeploymentError(
                            "rag mode has no prepared retrieval binding"
                        )
                    self._index_current_documents_once(
                        inputs.release.image, retrieval_binding, new_runtime_overrides
                    )
                    self._compose(
                        inputs.release.image,
                        "up",
                        "--detach",
                        "--no-deps",
                        "--force-recreate",
                        "retrieval-indexer",
                        profile="rag",
                        env_overrides=new_runtime_overrides,
                    )
                self._compose(
                    inputs.release.image,
                    "up",
                    "--detach",
                    "--no-deps",
                    "--force-recreate",
                    "api",
                    env_overrides=new_runtime_overrides,
                )
                self._journal("new_api_started")
                self._wait_ready("http://127.0.0.1:18000/health/ready")
                self._journal("new_api_ready")
                self._promote_web(release_id)
                self._journal("web_switched")
                self._maintenance_off()
                maintenance_started = False
                self._journal("complete", finished_at=datetime.now(UTC).isoformat())
            except BaseException:
                if maintenance_started:
                    recovered = self._rollback(
                        old_release=old_release,
                        old_current=old_current,
                        old_previous=old_previous,
                        old_model=old_model,
                        release_id=release_id,
                        old_runtime_overrides=old_runtime_overrides,
                    )
                    if not recovered:
                        raise DeploymentError(
                            "deployment failed; maintenance remains enabled for manual recovery"
                        ) from None
                else:
                    self._journal("rolled_back", database_restored=False)
                raise


def _require_trusted_helper() -> None:
    if os.geteuid() != 0:
        raise DeploymentError("deployment helper must run as root")
    _secure_file(Path(__file__), private=False)


def _term_as_interrupt():
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    return previous


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    deploy_parser = subparsers.add_parser(
        "deploy", help="deploy a validated release id"
    )
    deploy_parser.add_argument("release_id")
    subparsers.add_parser(
        "recover", help="root-only recovery after an interrupted deployment"
    )
    args = parser.parse_args(argv)
    try:
        _require_trusted_helper()
        if args.command == "recover":
            status = DeploymentEngine().recover()
            print(json.dumps({"status": status, "database_restored": False}))
            return 0
        previous = _term_as_interrupt()
        try:
            DeploymentEngine().deploy(args.release_id)
        finally:
            signal.signal(signal.SIGTERM, previous)
        print(json.dumps({"status": "success", "release_id": args.release_id}))
    except (
        OSError,
        DeploymentError,
        MaintenanceError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print(
            json.dumps(
                {"status": "interrupted", "recovery": "inspect deployment journal"}
            ),
            file=sys.stderr,
        )
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
