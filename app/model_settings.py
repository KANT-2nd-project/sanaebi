"""서버 모델 선택. 상대 모델 경로는 저장소 루트 기준이다."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLASSIFIER_PATH = (
    PROJECT_ROOT
    / "artifacts/experiments/learning-comparison-2026-10-15/koelectra_base/model"
)


def get_classifier_path() -> Path:
    value = os.getenv("SANAEBI_CLASSIFIER_PATH")
    path = Path(value).expanduser() if value else DEFAULT_CLASSIFIER_PATH
    return path if path.is_absolute() else PROJECT_ROOT / path


def get_answer_provider() -> str:
    provider = os.getenv("SANAEBI_ANSWER_PROVIDER", "ollama")
    if provider not in ("ollama", "openai"):
        raise ValueError("SANAEBI_ANSWER_PROVIDER must be ollama or openai")
    return provider
