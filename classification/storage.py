"""로컬 모델 묶음의 무결성·재사용 조건·잠금·복구 가능한 교체.

학습이나 모델 로딩은 하지 않는다. 완료 manifest는 호출자가 재로딩 검증 후 쓴다.
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from .artifacts import ROOT, read_json

DEFAULT_ROOT = ROOT.parent / "artifacts"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_text(path, content):
    """같은 파일시스템에서 완성한 단일 파일만 게시한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def environment():
    import torch

    cpu_model = platform.processor()
    if not cpu_model:
        try:
            cpu_model = next(
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            )
        except (OSError, StopIteration):
            cpu_model = None
    driver = None
    if torch.cuda.is_available():
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                check=False,
            )
            driver = result.stdout.strip() if result.returncode == 0 else None
        except OSError:
            pass  # 드라이버 CLI가 없는 환경은 미확인으로 기록한다.
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": cpu_model,
        "logical_cpus": os.cpu_count(),
        "thread_environment": {
            key: os.environ.get(key)
            for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "CUBLAS_WORKSPACE_CONFIG")
        },
        "matmul_precision": torch.get_float32_matmul_precision(),
        "cuda_matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
        "libraries": {
            name: version(name)
            for name in (
                "torch",
                "transformers",
                "scikit-learn",
                "numpy",
                "joblib",
                "scipy",
                "tokenizers",
                "safetensors",
                "huggingface-hub",
            )
        },
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "driver": driver,
        "deterministic": torch.are_deterministic_algorithms_enabled(),
        "cudnn_deterministic": torch.backends.cudnn.deterministic,
        "cudnn_benchmark": torch.backends.cudnn.benchmark,
    }


def request_conditions(config, data):
    # 출처 commit/lock은 별도 기록한다. UI/HTML 변경은 학습 조건이 아니다.
    sources = [
        "dataset.py",
        "types.py",
        "workflows/train.py",
        "evaluation/metrics.py",
        "models/transformer.py" if hasattr(config, "model_name") else "models/tfidf.py",
    ]
    runtime = environment()
    if not hasattr(config, "model_name"):
        runtime["device"] = "cpu"
    return json.loads(
        json.dumps(
            {
                "config": asdict(config),
                "data_split": data.record,
                "source_hashes": {name: file_hash(ROOT / name) for name in sources},
                "labels_hash": file_hash(ROOT.parent / "contracts/classification.py"),
                "environment": runtime,
            }
        )
    )


def provenance(kind, **extra):
    result = subprocess.run(
        ["git", "-C", str(ROOT.parent), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "kind": kind,
        "recorded_at": datetime.now(UTC).isoformat(),
        "commit_at_recording": result.stdout.strip() or None,
        "lock_hash_at_recording": file_hash(ROOT.parent / "uv.lock"),
        **extra,
    }


def complete_manifest(bundle, name, conditions, origin):
    files = {
        str(p.relative_to(bundle)): file_hash(p)
        for p in sorted(bundle.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "name": name,
        "files": files,
        "model_id": digest(files),
        "conditions": conditions,
        "fingerprint": digest(conditions),
        "provenance": origin,
    }
    atomic_json(bundle / "manifest.json", manifest)
    return manifest


def validate_bundle(bundle, name):
    try:
        manifest = read_json(bundle / "manifest.json")
        if not isinstance(manifest, dict):
            raise TypeError("manifest는 JSON 객체여야 합니다.")
        if (
            manifest.get("schema_version") != 1
            or manifest.get("status") != "complete"
            or manifest.get("name") != name
        ):
            raise ValueError("완료 manifest가 아닙니다.")
        if manifest.get("provenance", {}).get("kind") not in {"trained", "adopted"}:
            raise ValueError("학습·채택 출처가 누락됐습니다.")
        files = manifest["files"]
        if not isinstance(files, dict) or not isinstance(
            manifest.get("conditions"), dict
        ):
            raise TypeError("파일 목록 또는 재사용 조건 형식이 잘못됐습니다.")
        actual = {
            str(p.relative_to(bundle))
            for p in bundle.rglob("*")
            if p.is_file() and p != bundle / "manifest.json"
        }
        if actual != set(files):
            raise ValueError("manifest와 실제 파일 목록이 다릅니다.")
        required = (
            {"training_summary.json", "model.joblib"}
            if name == "tfidf"
            else {"training_summary.json", "config.json", "tokenizer_config.json"}
        )
        if not required <= files.keys():
            raise ValueError("필수 파일 목록이 누락됐습니다.")
        if name != "tfidf" and (
            not any(k.endswith(".safetensors") for k in files)
            or not any(
                k in files
                for k in (
                    "tokenizer.json",
                    "vocab.txt",
                    "spiece.model",
                    "tokenizer.model",
                )
            )
        ):
            raise ValueError("가중치 또는 토크나이저가 누락됐습니다.")
        for relative, expected in files.items():
            path = Path(relative)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not (bundle / path).is_file()
                or file_hash(bundle / path) != expected
            ):
                raise ValueError(f"파일 누락 또는 해시 불일치: {relative}")
        if (
            digest(files) != manifest["model_id"]
            or digest(manifest["conditions"]) != manifest["fingerprint"]
        ):
            raise ValueError("manifest 해시 불일치")
        return manifest
    except (
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError(f"모델 묶음이 불완전합니다: {bundle}: {error}") from error


@contextmanager
def lock(root, name):
    """OS 잠금은 프로세스 종료 시 해제된다. 남은 잠금 파일 자체는 진행 상태가 아니다."""
    path = root / ".locks" / (name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt

                if path.stat().st_size == 0:
                    file.write(b"0")
                    file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as error:
            raise ValueError(
                f"{name} 작업이 진행 중입니다. 완료 후 다시 실행하세요."
            ) from error
        try:
            yield
        finally:
            if acquired:
                if os.name == "nt":
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def stage(root, name):
    path = root / ".staging" / (name + "-" + uuid4().hex)
    path.mkdir(parents=True)
    return path


def recover(root, category, name):
    """호출자는 모델 잠금을 보유한다. journal이 있으면 완료하거나 구형 묶음을 복원한다."""
    journal = root / ".staging" / f"{category}-{name}.json"
    if not journal.exists():
        return
    record = read_json(journal)
    target, temporary, old = (
        root / record[key] for key in ("target", "temporary", "old")
    )
    if any(
        not path.resolve().is_relative_to(root.resolve())
        for path in (target, temporary, old)
    ):
        raise ValueError("교체 기록의 경로가 저장소 밖을 가리킵니다.")
    backup = root / ".backup" / category / name
    if target.exists() and not temporary.exists():  # 새 묶음 게시 완료
        if old.exists() and record.get("backup_old", True):
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(old, backup)
    elif old.exists():  # 구형 묶음 이동 후 중단
        os.replace(old, target)
    journal.unlink()


def publish(root, category, name, temporary, *, backup_old=True):
    """검증된 임시 묶음을 교체. 실패 시 journal로 이전 상태 복구."""
    target = root / category / name
    target.parent.mkdir(parents=True, exist_ok=True)
    old = root / ".staging" / ("previous-" + uuid4().hex)
    journal = root / ".staging" / f"{category}-{name}.json"
    atomic_json(
        journal,
        {
            "backup_old": backup_old,
            **{
                key: str(path.relative_to(root))
                for key, path in [
                    ("target", target),
                    ("temporary", temporary),
                    ("old", old),
                ]
            },
        },
    )
    try:
        if target.exists():
            os.replace(target, old)
        os.replace(temporary, target)
    finally:
        recover(root, category, name)
    return target
