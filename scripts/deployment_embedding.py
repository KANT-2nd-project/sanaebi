"""Download and verify the pinned deployment retrieval model and splitter."""

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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

EXPECTED_MODEL_ID = "nlpai-lab/KURE-v1"
EXPECTED_REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"
LEGACY_MODEL_ID = "exp-models/dragonkue-KoEn-E5-Tiny"
LEGACY_REVISION = "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9"
EXPECTED_FILES = (
    "config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
KURE_EXPECTED_FILES = (*EXPECTED_FILES, "1_Pooling/config.json")
EXPECTED_SPLITTER_FILES = (
    "config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
MANIFEST_KEYS = {
    "schema_version",
    "default_mode",
    "baseline_schema_version",
    "index_schema_version",
    "embedding",
}
LEGACY_EMBEDDING_KEYS = {
    "model_id",
    "revision",
    "dimension",
    "max_length",
    "pooling",
    "normalization",
    "query_prefix",
    "passage_prefix",
    "dtype",
    "files",
}
KURE_EMBEDDING_KEYS = LEGACY_EMBEDDING_KEYS | {
    "query_max_length",
    "splitter",
}


class ReleaseError(RuntimeError):
    """A safe-to-display deployment embedding error."""


@dataclass(frozen=True)
class FileRecord:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SplitterModel:
    model_id: str
    revision: str
    directory: str
    files: tuple[FileRecord, ...]


@dataclass(frozen=True)
class EmbeddingModel:
    model_id: str
    revision: str
    dimension: int
    max_length: int
    query_max_length: int
    pooling: str
    normalization: str
    query_prefix: str
    passage_prefix: str
    dtype: str
    files: tuple[FileRecord, ...]
    splitter: SplitterModel | None = None


@dataclass(frozen=True)
class RetrievalRelease:
    default_mode: str
    baseline_schema_version: int
    index_schema_version: int
    model: EmbeddingModel


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_manifest(raw: bytes) -> RetrievalRelease:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ReleaseError("retrieval-release.json is invalid JSON") from error
    if not isinstance(value, dict) or set(value) != MANIFEST_KEYS:
        raise ReleaseError("retrieval-release.json has unsupported fields")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ReleaseError("retrieval-release.json schema is unsupported")
    if value.get("default_mode") not in {"full", "rag"}:
        raise ReleaseError("retrieval default mode must be full or rag")
    for field in ("baseline_schema_version", "index_schema_version"):
        if type(value.get(field)) is not int or not 1 <= value[field] <= 1000:
            raise ReleaseError(f"{field} must be a supported positive version")

    raw_model = value.get("embedding")
    if not isinstance(raw_model, dict) or set(raw_model) not in (
        LEGACY_EMBEDDING_KEYS,
        KURE_EMBEDDING_KEYS,
    ):
        raise ReleaseError("embedding model descriptor has unsupported fields")
    if set(raw_model) == LEGACY_EMBEDDING_KEYS:
        expected_contract = {
            "model_id": LEGACY_MODEL_ID,
            "revision": LEGACY_REVISION,
            "dimension": 384,
            "max_length": 512,
            "pooling": "attention-mask-mean",
            "normalization": "l2",
            "query_prefix": "query: ",
            "passage_prefix": "passage: ",
            "dtype": "float32",
        }
        query_max_length = 512
        expected_files = EXPECTED_FILES
        splitter = None
    else:
        expected_contract = {
            "model_id": EXPECTED_MODEL_ID,
            "revision": EXPECTED_REVISION,
            "dimension": 1024,
            "max_length": 8192,
            "pooling": "cls",
            "normalization": "l2",
            "query_prefix": "",
            "passage_prefix": "",
            "dtype": "float32",
        }
        query_max_length = 512
        expected_files = KURE_EXPECTED_FILES
        splitter = _parse_splitter(raw_model.get("splitter"))
        if raw_model.get("query_max_length") != query_max_length:
            raise ReleaseError("embedding query length is not pinned")
    if any(
        raw_model.get(key) != expected for key, expected in expected_contract.items()
    ):
        raise ReleaseError("embedding descriptor does not match the pinned model")
    if (
        type(raw_model.get("dimension")) is not int
        or type(raw_model.get("max_length")) is not int
    ):
        raise ReleaseError("embedding dimensions must be integers")

    files = _parse_file_records(raw_model.get("files"), expected_files)

    return RetrievalRelease(
        default_mode=value["default_mode"],
        baseline_schema_version=value["baseline_schema_version"],
        index_schema_version=value["index_schema_version"],
        model=EmbeddingModel(
            **{
                **expected_contract,
                "query_max_length": query_max_length,
                "files": tuple(files),
                "splitter": splitter,
            }
        ),
    )


def _parse_file_records(raw_files: object, expected_names: tuple[str, ...]):
    if not isinstance(raw_files, list) or len(raw_files) != len(expected_names):
        raise ReleaseError("embedding file inventory is invalid")
    files: list[FileRecord] = []
    for record in raw_files:
        if not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"}:
            raise ReleaseError("embedding file record is invalid")
        name = record.get("name")
        size = record.get("bytes")
        digest = record.get("sha256")
        if (
            not isinstance(name, str)
            or type(size) is not int
            or size < 1
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ReleaseError("embedding file record is invalid")
        path = Path(name)
        if (
            path.is_absolute()
            or "\\" in name
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ReleaseError("embedding file path is unsafe")
        files.append(FileRecord(name, size, digest))
    if tuple(item.name for item in files) != expected_names:
        raise ReleaseError("embedding file inventory is missing, extra, or reordered")
    return files


def _parse_splitter(raw_splitter: object) -> SplitterModel:
    expected_keys = {"model_id", "revision", "directory", "files"}
    if not isinstance(raw_splitter, dict) or set(raw_splitter) != expected_keys:
        raise ReleaseError("embedding splitter descriptor has unsupported fields")
    if (
        raw_splitter.get("model_id") != LEGACY_MODEL_ID
        or raw_splitter.get("revision") != LEGACY_REVISION
        or raw_splitter.get("directory") != "splitter"
    ):
        raise ReleaseError("embedding splitter is not the pinned Tiny tokenizer")
    return SplitterModel(
        model_id=LEGACY_MODEL_ID,
        revision=LEGACY_REVISION,
        directory="splitter",
        files=tuple(
            _parse_file_records(raw_splitter.get("files"), EXPECTED_SPLITTER_FILES)
        ),
    )


def model_sidecar(model: EmbeddingModel) -> dict[str, object]:
    """Return the exact model identity and tokenizer contract consumed at runtime."""
    value = {
        "model_id": model.model_id,
        "revision": model.revision,
        "dimension": model.dimension,
        "pooling": model.pooling,
        "normalization": model.normalization,
        "query_prefix": model.query_prefix,
        "passage_prefix": model.passage_prefix,
        "dtype": model.dtype,
    }
    if model.splitter is not None:
        value["max_length"] = model.max_length
        value["query_max_length"] = model.query_max_length
        value["splitter"] = {
            "model_id": model.splitter.model_id,
            "revision": model.splitter.revision,
            "directory": model.splitter.directory,
        }
    return value


def _model_directory_name(model_id: str) -> str:
    return model_id.replace("/", "--")


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise ReleaseError(
            f"embedding payload is missing or unsafe: {path.name}"
        ) from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReleaseError(f"embedding payload is not a regular file: {path.name}")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return size, digest.hexdigest()


def validate_model_directory(path: Path, release: RetrievalRelease) -> None:
    path = Path(path)
    try:
        info = path.lstat()
    except OSError:
        raise ReleaseError(
            "embedding model directory is missing or unreadable"
        ) from None
    if not stat.S_ISDIR(info.st_mode):
        raise ReleaseError("embedding model directory inventory is invalid")
    expected_records = list(release.model.files)
    extra_directories: set[str] = set()
    if release.model.splitter is not None:
        prefix = release.model.splitter.directory
        extra_directories.add(prefix)
        expected_records.extend(
            FileRecord(
                f"{prefix}/{record.name}",
                record.size,
                record.sha256,
            )
            for record in release.model.splitter.files
        )
    _validate_file_tree(
        path,
        expected_records,
        extra_files={"retrieval-model.json"},
        extra_directories=extra_directories,
    )
    sidecar = path / "retrieval-model.json"
    try:
        actual = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ReleaseError("embedding runtime sidecar is invalid") from None
    if actual != model_sidecar(release.model):
        raise ReleaseError("embedding runtime sidecar does not match the release")


def _validate_root(root: Path) -> None:
    absolute = Path(os.path.abspath(root))
    for component in reversed(absolute.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ReleaseError("embedding root has an unsafe path component")
    try:
        info = absolute.lstat()
    except FileNotFoundError:
        absolute.mkdir(parents=True, mode=0o755)
        info = absolute.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ReleaseError("embedding root is not a safe directory")


def _validate_file_tree(
    root: Path,
    records: list[FileRecord],
    *,
    extra_files: set[str] = frozenset(),
    extra_directories: set[str] = frozenset(),
) -> None:
    expected_files = {record.name for record in records} | extra_files
    expected_directories = set(extra_directories)
    for name in expected_files:
        path = Path(name)
        if (
            path.is_absolute()
            or "\\" in name
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ReleaseError("embedding file path is unsafe")
        parent = Path()
        for part in path.parts[:-1]:
            parent /= part
            expected_directories.add(parent.as_posix())

    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    try:
        for directory, directories, files in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            for name in list(directories):
                child = directory_path / name
                info = child.lstat()
                relative = child.relative_to(root).as_posix()
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or relative not in expected_directories
                ):
                    raise ReleaseError("embedding model directory inventory is invalid")
                actual_directories.add(relative)
            for name in files:
                child = directory_path / name
                info = child.lstat()
                relative = child.relative_to(root).as_posix()
                if not stat.S_ISREG(info.st_mode) or relative not in expected_files:
                    raise ReleaseError("embedding model file inventory is invalid")
                actual_files.add(relative)
    except OSError:
        raise ReleaseError("embedding model directory is unreadable") from None
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ReleaseError("embedding model inventory is incomplete")

    records_by_name = {record.name: record for record in records}
    for name, record in records_by_name.items():
        size, digest = _sha256(root / name)
        if size != record.size or digest != record.sha256:
            raise ReleaseError(f"embedding payload verification failed: {name}")


@contextmanager
def _deployment_lock(root: Path) -> Iterator[None]:
    lock = root / ".embedding-release.lock"
    descriptor = os.open(
        lock,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReleaseError("embedding model lock is unsafe")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def prepare_embedding(
    manifest: Path,
    root: Path,
    *,
    downloader: Callable[..., str] | None = None,
) -> Path:
    """Download to staging, verify every byte, then atomically publish read-only."""
    manifest = Path(manifest)
    try:
        release = parse_manifest(manifest.read_bytes())
    except OSError:
        raise ReleaseError("retrieval release manifest is unavailable") from None
    root = Path(root)
    _validate_root(root)
    target = (
        root / _model_directory_name(release.model.model_id) / release.model.revision
    )
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    _validate_root(target.parent)
    if target.exists() or target.is_symlink():
        validate_model_directory(target, release)
        return target

    with _deployment_lock(root):
        if target.exists() or target.is_symlink():
            validate_model_directory(target, release)
            return target
        staging = Path(tempfile.mkdtemp(prefix=".staging-embedding-", dir=root))
        download_directory = staging / "download"
        output = staging / "model"
        try:
            download_directory.mkdir(mode=0o700)
            output.mkdir(mode=0o700)
            if downloader is None:
                from huggingface_hub import snapshot_download

                downloader = snapshot_download
            _download_component(
                downloader,
                model_id=release.model.model_id,
                revision=release.model.revision,
                records=release.model.files,
                download_directory=download_directory,
                output=output,
                error_label="embedding",
            )
            if release.model.splitter is not None:
                splitter_download = staging / "download-splitter"
                splitter_output = output / release.model.splitter.directory
                splitter_download.mkdir(mode=0o700)
                splitter_output.mkdir(mode=0o700)
                _download_component(
                    downloader,
                    model_id=release.model.splitter.model_id,
                    revision=release.model.splitter.revision,
                    records=release.model.splitter.files,
                    download_directory=splitter_download,
                    output=splitter_output,
                    error_label="embedding splitter",
                )
            (output / "retrieval-model.json").write_text(
                json.dumps(model_sidecar(release.model), sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            validate_model_directory(output, release)
            for path in output.iterdir():
                if path.is_dir():
                    for child in path.iterdir():
                        os.chmod(child, 0o444)
                    os.chmod(path, 0o555)
                else:
                    os.chmod(path, 0o444)
            os.chmod(target.parent, 0o755)
            os.rename(output, target)
            os.chmod(target, 0o555)
            return target
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _download_component(
    downloader: Callable[..., str],
    *,
    model_id: str,
    revision: str,
    records: tuple[FileRecord, ...],
    download_directory: Path,
    output: Path,
    error_label: str,
) -> None:
    snapshot = Path(
        downloader(
            repo_id=model_id,
            revision=revision,
            allow_patterns=[record.name for record in records],
            local_dir=str(download_directory),
            token=False,
        )
    )
    if os.path.abspath(snapshot) != os.path.abspath(download_directory):
        raise ReleaseError(f"{error_label} download returned an unexpected path")
    for record in records:
        source = snapshot / record.name
        size, digest = _sha256(source)
        if size != record.size or digest != record.sha256:
            raise ReleaseError(
                f"downloaded {error_label} file does not match pin: {record.name}"
            )
        destination = output / record.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        target = prepare_embedding(args.manifest, args.root)
    except Exception as error:  # noqa: BLE001 - never disclose remote/cache details
        print(
            json.dumps({"status": "failed", "error_type": type(error).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "ready", "model_path": str(target)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
