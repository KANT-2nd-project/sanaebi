"""Download and verify the pinned KoEn-E5-Tiny deployment model."""

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

EXPECTED_MODEL_ID = "exp-models/dragonkue-KoEn-E5-Tiny"
EXPECTED_REVISION = "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9"
EXPECTED_FILES = (
    "config.json",
    "model.safetensors",
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
EMBEDDING_KEYS = {
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


class ReleaseError(RuntimeError):
    """A safe-to-display deployment embedding error."""


@dataclass(frozen=True)
class FileRecord:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class EmbeddingModel:
    model_id: str
    revision: str
    dimension: int
    max_length: int
    pooling: str
    normalization: str
    query_prefix: str
    passage_prefix: str
    dtype: str
    files: tuple[FileRecord, ...]


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
    if not isinstance(raw_model, dict) or set(raw_model) != EMBEDDING_KEYS:
        raise ReleaseError("embedding model descriptor has unsupported fields")
    expected_contract = {
        "model_id": EXPECTED_MODEL_ID,
        "revision": EXPECTED_REVISION,
        "dimension": 384,
        "max_length": 512,
        "pooling": "attention-mask-mean",
        "normalization": "l2",
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "dtype": "float32",
    }
    if any(
        raw_model.get(key) != expected for key, expected in expected_contract.items()
    ):
        raise ReleaseError("embedding descriptor does not match the pinned model")
    if (
        type(raw_model.get("dimension")) is not int
        or type(raw_model.get("max_length")) is not int
    ):
        raise ReleaseError("embedding dimensions must be integers")

    raw_files = raw_model.get("files")
    if not isinstance(raw_files, list) or len(raw_files) != len(EXPECTED_FILES):
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
        files.append(FileRecord(name, size, digest))
    if tuple(item.name for item in files) != EXPECTED_FILES:
        raise ReleaseError("embedding file inventory is missing, extra, or reordered")

    return RetrievalRelease(
        default_mode=value["default_mode"],
        baseline_schema_version=value["baseline_schema_version"],
        index_schema_version=value["index_schema_version"],
        model=EmbeddingModel(**{**expected_contract, "files": tuple(files)}),
    )


def model_sidecar(model: EmbeddingModel) -> dict[str, object]:
    """Return the exact runtime contract consumed by TinyEmbedder."""
    return {
        "model_id": model.model_id,
        "revision": model.revision,
        "dimension": model.dimension,
        "pooling": model.pooling,
        "normalization": model.normalization,
        "query_prefix": model.query_prefix,
        "passage_prefix": model.passage_prefix,
        "dtype": model.dtype,
    }


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
        entries = list(path.iterdir())
    except OSError:
        raise ReleaseError(
            "embedding model directory is missing or unreadable"
        ) from None
    if not stat.S_ISDIR(info.st_mode) or {entry.name for entry in entries} != {
        *EXPECTED_FILES,
        "retrieval-model.json",
    }:
        raise ReleaseError("embedding model directory inventory is invalid")
    for record in release.model.files:
        size, digest = _sha256(path / record.name)
        if size != record.size or digest != record.sha256:
            raise ReleaseError(f"embedding payload verification failed: {record.name}")
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
            snapshot = Path(
                downloader(
                    repo_id=release.model.model_id,
                    revision=release.model.revision,
                    allow_patterns=list(EXPECTED_FILES),
                    local_dir=str(download_directory),
                    token=False,
                )
            )
            if os.path.abspath(snapshot) != os.path.abspath(download_directory):
                raise ReleaseError("embedding download returned an unexpected path")
            for record in release.model.files:
                source = snapshot / record.name
                size, digest = _sha256(source)
                if size != record.size or digest != record.sha256:
                    raise ReleaseError(
                        f"downloaded embedding file does not match pin: {record.name}"
                    )
                shutil.copyfile(source, output / record.name)
            (output / "retrieval-model.json").write_text(
                json.dumps(model_sidecar(release.model), sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            validate_model_directory(output, release)
            for path in output.iterdir():
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
