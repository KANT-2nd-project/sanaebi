"""로컬에서 만든 모델을 임시 저장·재로딩 검증 후 새 경로에 보관한다."""

import hashlib
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

import joblib


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def split_id(question_ids):
    content = json.dumps(question_ids, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@contextmanager
def new_destination(destination):
    """기존 경로와 동시에 실행되는 동일 목적지 쓰기를 거부한다."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name(f".{destination.name}.lock")
    # 강제 종료로 남은 lock은 자동 삭제하지 않는다.
    with lock.open("x"):
        try:
            if destination.exists():
                raise FileExistsError(f"기존 경로를 보존합니다: {destination}")
            yield destination
        finally:
            lock.unlink()


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def save_bundle(model, destination, metadata, check_texts):
    if not check_texts:
        raise ValueError("재로딩 확인에 사용할 질문이 필요합니다.")
    # 목적지와 같은 파일시스템에서 완성한 뒤 폴더를 이동한다.
    with (
        new_destination(destination) as target,
        tempfile.TemporaryDirectory(dir=target.parent, prefix=".staging-") as temp,
    ):
        stage = Path(temp) / "bundle"
        stage.mkdir()
        joblib.dump(model, stage / "model.joblib")
        restored = joblib.load(stage / "model.joblib")
        if (
            restored.predict(check_texts).tolist()
            != model.predict(check_texts).tolist()
        ):
            raise ValueError("저장 전후 예측이 다릅니다.")
        write_json(stage / "metadata.json", {**metadata, "complete": True})
        stage.rename(target)


def read_metadata(bundle):
    metadata = json.loads((Path(bundle) / "metadata.json").read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("complete") is not True:
        raise ValueError("완료된 모델 기록이 아닙니다.")
    return metadata


def save_evaluation(destination, metrics, predictions):
    with (
        new_destination(destination) as target,
        tempfile.TemporaryDirectory(dir=target.parent, prefix=".staging-") as temp,
    ):
        stage = Path(temp) / "evaluation"
        stage.mkdir()
        write_json(stage / "metrics.json", metrics)
        write_json(stage / "predictions.json", predictions)
        stage.rename(target)
