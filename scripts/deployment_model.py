"""Download and verify the pinned Sanaebi classifier release."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import snapshot_download

EXPECTED_REPO_ID = "js2923/sanaebi-koelectra-base"
EXPECTED_REVISION = "4a1d0c7964072535a52a66efe29389a6470dd6f4"
EXPECTED_MODEL_ID = "9f51682d82d4455d8296077c339afd58"
EXPECTED_LABELS = ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED")
EXPECTED_FILES = (
    "config.json",
    "metadata.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
)
MANIFEST_KEYS = {"schema_version", "repo_id", "revision", "model_id", "labels", "files"}


class ReleaseError(Exception):
    """A safe-to-display deployment model error."""


@dataclass(frozen=True)
class FileRecord:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    files: tuple[FileRecord, ...]


def _read_json(path: Path) -> dict[str, object]:
    _check_path_components(path.parent)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReleaseError("JSON input path is not a regular file")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            value = json.loads(source.read())
    except ReleaseError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ReleaseError("release manifest is unreadable or invalid JSON") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise ReleaseError("JSON input must contain an object")
    return value


def _load_release(path: Path) -> Release:
    document = _read_json(path)
    if set(document) != MANIFEST_KEYS:
        raise ReleaseError("release manifest has unsupported fields")
    if (
        type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
    ):
        raise ReleaseError("release manifest has an unsupported schema version")
    if document.get("repo_id") != EXPECTED_REPO_ID:
        raise ReleaseError(
            "release manifest repository does not match the pinned model"
        )
    if document.get("revision") != EXPECTED_REVISION:
        raise ReleaseError("release manifest revision does not match the pinned commit")
    if document.get("model_id") != EXPECTED_MODEL_ID:
        raise ReleaseError(
            "release manifest model id does not match the selected model"
        )
    if document.get("labels") != list(EXPECTED_LABELS):
        raise ReleaseError(
            "release manifest labels do not match the selected classifier"
        )

    raw_files = document.get("files")
    if not isinstance(raw_files, list) or len(raw_files) != len(EXPECTED_FILES):
        raise ReleaseError("release manifest file inventory is invalid")

    records: list[FileRecord] = []
    for raw_record in raw_files:
        if not isinstance(raw_record, dict) or set(raw_record) != {
            "name",
            "bytes",
            "sha256",
        }:
            raise ReleaseError("release manifest file record is invalid")
        name = raw_record.get("name")
        size = raw_record.get("bytes")
        digest = raw_record.get("sha256")
        if (
            not isinstance(name, str)
            or name not in EXPECTED_FILES
            or Path(name).name != name
            or type(size) is not int
            or size < 1
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ReleaseError("release manifest file record is invalid")
        records.append(FileRecord(name=name, size=size, sha256=digest))

    if tuple(record.name for record in records) != EXPECTED_FILES:
        raise ReleaseError(
            "release manifest file inventory is missing, extra, or out of order"
        )
    return Release(files=tuple(records))


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _check_path_components(path: Path) -> None:
    absolute = _absolute(path)
    components = [*reversed(absolute.parents), absolute]
    for component in components:
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ReleaseError(f"model path contains a symlink: {component.name}")
        if not stat.S_ISDIR(mode):
            raise ReleaseError(
                f"model path component is not a directory: {component.name}"
            )


def _ensure_directory(path: Path) -> None:
    _check_path_components(path)
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        raise ReleaseError("model directory could not be prepared") from None
    _check_path_components(path)


@contextmanager
def _deployment_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".model-release.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError:
        raise ReleaseError("model release lock could not be opened safely") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReleaseError("model release lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _remove_stale_staging(root: Path) -> None:
    try:
        candidates = list(root.iterdir())
        for candidate in candidates:
            if not candidate.name.startswith(".staging-"):
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                candidate.unlink()
            else:
                shutil.rmtree(candidate)
    except OSError:
        raise ReleaseError("stale model staging data could not be cleared") from None


def _assert_regular_tree(path: Path) -> None:
    try:
        entries = list(path.iterdir())
    except OSError:
        raise ReleaseError("download cache metadata is unreadable") from None
    for entry in entries:
        try:
            mode = entry.lstat().st_mode
        except OSError:
            raise ReleaseError("download cache metadata is unreadable") from None
        if stat.S_ISLNK(mode):
            raise ReleaseError("download contains a symlink")
        if stat.S_ISDIR(mode):
            _assert_regular_tree(entry)
        elif not stat.S_ISREG(mode):
            raise ReleaseError("download contains an unsupported filesystem entry")


def _file_digest(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ReleaseError(f"payload file is missing or unsafe: {path.name}") from None
    digest = hashlib.sha256()
    size = 0
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReleaseError(f"payload file is not regular: {path.name}")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return size, digest.hexdigest()


def _validate_metadata(directory: Path) -> None:
    config = _read_json(directory / "config.json")
    metadata = _read_json(directory / "metadata.json")
    id2label = {str(index): label for index, label in enumerate(EXPECTED_LABELS)}
    label2id = {label: index for index, label in enumerate(EXPECTED_LABELS)}

    actual_id2label = config.get("id2label")
    actual_label2id = config.get("label2id")
    if (
        not isinstance(actual_id2label, dict)
        or actual_id2label != id2label
        or not isinstance(actual_label2id, dict)
        or actual_label2id != label2id
    ):
        raise ReleaseError(
            "classifier config label metadata does not match the release"
        )
    if "num_labels" in config:
        count = config["num_labels"]
        if type(count) is not int or count != len(EXPECTED_LABELS):
            raise ReleaseError(
                "classifier config label count does not match the release"
            )
    if (
        type(metadata.get("schema_version")) is not int
        or metadata.get("schema_version") != 1
        or metadata.get("model_id") != EXPECTED_MODEL_ID
        or metadata.get("labels") != list(EXPECTED_LABELS)
    ):
        raise ReleaseError("classifier metadata does not match the selected model")


def _verify_payload(
    directory: Path, release: Release, *, downloaded: bool = False
) -> None:
    if directory.is_symlink():
        raise ReleaseError("model payload path is a symlink")
    try:
        mode = directory.lstat().st_mode
    except OSError:
        raise ReleaseError("model payload directory is missing") from None
    if not stat.S_ISDIR(mode):
        raise ReleaseError("model payload path is not a directory")

    try:
        entries = list(directory.iterdir())
    except OSError:
        raise ReleaseError("model payload directory is unreadable") from None
    names = {entry.name for entry in entries}
    expected_names = set(EXPECTED_FILES)
    allowed_names = expected_names | ({".cache"} if downloaded else set())
    if not expected_names.issubset(names) or not names.issubset(allowed_names):
        raise ReleaseError("model payload has missing or extra files")

    if downloaded and ".cache" in names:
        cache_path = directory / ".cache"
        if cache_path.is_symlink() or not cache_path.is_dir():
            raise ReleaseError("download cache metadata path is unsafe")
        _assert_regular_tree(cache_path)

    expected_by_name = {record.name: record for record in release.files}
    for name in EXPECTED_FILES:
        file_path = directory / name
        size, digest = _file_digest(file_path)
        record = expected_by_name[name]
        if size != record.size or digest != record.sha256:
            raise ReleaseError(f"payload hash or size mismatch: {name}")
    _validate_metadata(directory)


def _prepare_release(root: Path, release: Release) -> Path:
    absolute_root = _absolute(root)
    _ensure_directory(absolute_root)
    with _deployment_lock(absolute_root):
        _remove_stale_staging(absolute_root)
        model_directory = absolute_root / EXPECTED_MODEL_ID
        _check_path_components(model_directory)
        target = model_directory / EXPECTED_REVISION
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise ReleaseError("cached release path is a symlink")
            try:
                _verify_payload(target, release)
            except ReleaseError:
                raise ReleaseError(
                    "cached release is invalid; refusing to overwrite it"
                ) from None
            return target

        token = os.environ.get("HF_TOKEN")
        if not token:
            raise ReleaseError(
                "HF_TOKEN is required to download the private model release"
            )

        _ensure_directory(model_directory)
        try:
            staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=absolute_root))
        except OSError:
            raise ReleaseError("model staging directory could not be created") from None

        try:
            download_directory = staging / "download"
            try:
                returned_path = snapshot_download(
                    repo_id=EXPECTED_REPO_ID,
                    repo_type="model",
                    revision=EXPECTED_REVISION,
                    local_dir=download_directory,
                    allow_patterns=list(EXPECTED_FILES),
                    token=token,
                )
            except Exception:  # noqa: BLE001 - sanitize third-party errors that may expose auth details
                raise ReleaseError("Hugging Face model download failed") from None

            if _absolute(Path(returned_path)) != _absolute(download_directory):
                raise ReleaseError("Hugging Face download returned an unexpected path")
            _verify_payload(download_directory, release, downloaded=True)

            payload_directory = staging / "payload"
            payload_directory.mkdir(mode=0o700)
            for name in EXPECTED_FILES:
                shutil.copyfile(download_directory / name, payload_directory / name)
            _verify_payload(payload_directory, release)

            if target.exists() or target.is_symlink():
                raise ReleaseError("cached release appeared during model preparation")
            try:
                os.rename(payload_directory, target)
            except OSError:
                raise ReleaseError(
                    "verified model could not be published atomically"
                ) from None
            return target
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def prepare_model(manifest: Path, root: Path) -> Path:
    release = _load_release(manifest)
    return _prepare_release(root, release)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", required=True, type=Path, help="pinned model release JSON"
    )
    parser.add_argument(
        "--root", required=True, type=Path, help="model cache root directory"
    )
    arguments = parser.parse_args(argv)

    try:
        model_path = prepare_model(arguments.manifest, arguments.root)
    except ReleaseError as exc:
        print(f"deployment model: {exc}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - never print unexpected errors that may include secrets
        print(
            "deployment model: operation failed (details suppressed)", file=sys.stderr
        )
        return 1

    print(model_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
