"""로컬 실험 저장: 최소 메타데이터, 잠금, 검증 후 교체와 예외 복원."""

import hashlib
import json
import os
import platform
import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.metadata import version
from uuid import uuid4

from .artifacts import ROOT, read_json

DEFAULT_ROOT = ROOT.parents[1] / "artifacts"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


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
    """실험 해석용 기록이며 재사용 여부를 결정하지 않는다."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libraries": {
            name: version(name)
            for name in ("torch", "transformers", "scikit-learn", "numpy", "mlflow")
        },
    }


def complete_manifest(bundle, name, *, model_id, training_run_id):
    manifest = {
        "schema_version": 2,
        "status": "complete",
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
        "model_id": model_id,
        "training_run_id": training_run_id,
    }
    atomic_json(bundle / "manifest.json", manifest)
    return manifest


def validate_bundle(bundle, name):
    """v1도 변경 없이 읽는다. 파일 존재·메타데이터만 검사하며 가중치를 해싱하지 않는다."""
    try:
        manifest = read_json(bundle / "manifest.json")
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") not in (1, 2)
            or manifest.get("status") != "complete"
            or manifest.get("name") != name
            or not isinstance(manifest.get("model_id"), str)
            or not manifest["model_id"]
        ):
            raise ValueError("완료된 모델 메타데이터가 아닙니다.")
        if manifest["schema_version"] == 2 and (
            not isinstance(manifest.get("training_run_id"), str)
            or not manifest["training_run_id"]
            or not isinstance(manifest.get("created_at"), str)
        ):
            raise ValueError("학습 run 또는 생성 시각이 누락됐습니다.")
        required = {"training_summary.json"}
        if name == "tfidf":
            required.add("model.joblib")
        else:
            required.update(("config.json", "tokenizer_config.json"))
            if not any(bundle.glob("*.safetensors")) or not any(
                (bundle / filename).is_file()
                for filename in (
                    "tokenizer.json",
                    "vocab.txt",
                    "spiece.model",
                    "tokenizer.model",
                )
            ):
                raise ValueError("가중치 또는 토크나이저가 누락됐습니다.")
        if any(not (bundle / filename).is_file() for filename in required):
            raise ValueError("필수 모델 파일이 누락됐습니다.")
        if not isinstance(read_json(bundle / "training_summary.json"), dict):
            raise TypeError("학습 요약은 JSON 객체여야 합니다.")
        return manifest
    except (OSError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"모델을 읽을 수 없습니다: {bundle}: {error}") from error


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


def check_pending(root, name):
    """중단 흔적은 자동 수정하지 않는다. 파일을 보존하고 수동 확인을 요구한다."""
    staging = root / ".staging"
    candidates = []
    if staging.exists():
        for path in staging.iterdir():
            if path.name.startswith(
                (name + "-", "eval-" + name + "-", "previous-")
            ) or path.name in {
                f"models-{name}.json",
                f"results-{name}.json",
                f"results-{name}",
            }:
                candidates.append(path)
    if candidates:
        raise ValueError(
            "중단된 저장 흔적이 있습니다: "
            + ", ".join(str(p) for p in candidates)
            + ". 실행 중인 작업이 없는지 확인하고, 기존 모델과 .backup을 확인한 뒤 "
            "보존할 폴더를 별도 위치로 옮기세요. 자동 복구·삭제하지 않습니다."
        )


def stage(root, name):
    path = root / ".staging" / (name + "-" + uuid4().hex)
    path.mkdir(parents=True)
    return path


def publish(root, category, name, temporary):
    """검증된 묶음을 교체한다. 프로세스 내 실패는 복원하며 강제 종료는 수동 복구한다."""
    target = root / category / name
    target.parent.mkdir(parents=True, exist_ok=True)
    old = (
        root
        / ".staging"
        / ("previous-" + category + "-" + name.replace("/", "-") + "-" + uuid4().hex)
    )
    try:
        if target.exists():
            os.replace(target, old)
        os.replace(temporary, target)
    except OSError:
        if old.exists():
            os.replace(old, target)
        raise
    if old.exists():
        backup = root / ".backup" / category / name
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(old, backup)
        except OSError as error:
            raise RuntimeError(
                f"새 묶음 저장 완료: {target}. 직전 백업 정리 실패: {old}. "
                "자동 재실행하지 말고 두 폴더를 확인하세요."
            ) from error
    return target
