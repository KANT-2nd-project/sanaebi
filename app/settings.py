"""서버 모델·문서 경로 설정. 기존 환경변수와 경로 해석을 유지한다."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCUMENTS_PATH = PROJECT_ROOT / "data" / "company-knowledge" / "documents.jsonl"


def get_documents_path() -> Path:
    """IEUM_WORKS_PATH가 있으면 사용하고, 없으면 정책 데이터 경로를 반환한다."""
    configured_path = os.getenv("IEUM_WORKS_PATH")
    return Path(configured_path) if configured_path else DEFAULT_DOCUMENTS_PATH


def get_document_database_path() -> Path:
    """One runtime database path shared by HTTP, CLI and migration tools."""
    value = os.getenv("SANAEBI_DOCUMENT_DB")
    return (
        Path(value).expanduser().resolve()
        if value
        else PROJECT_ROOT / "var" / "documents.sqlite3"
    )


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
