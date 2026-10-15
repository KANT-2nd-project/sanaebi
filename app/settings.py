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
    provider = os.getenv("SANAEBI_ANSWER_PROVIDER", "openai")
    if provider != "openai":
        raise ValueError(
            "SANAEBI_ANSWER_PROVIDER must be unset or openai; the server uses the adopted Luna model"
        )
    return provider


def get_routing_mode() -> str:
    """Return the request-routing behavior, defaulting to the adopted shadow policy."""
    mode = os.getenv("SANAEBI_ROUTING_MODE", "shadow")
    if mode not in {"gate", "shadow"}:
        raise ValueError("SANAEBI_ROUTING_MODE must be gate or shadow")
    return mode


def get_retrieval_mode() -> str:
    mode = os.getenv("SANAEBI_RETRIEVAL_MODE", "rag")
    if mode not in {"full", "rag"}:
        raise ValueError("SANAEBI_RETRIEVAL_MODE must be full or rag")
    return mode


def _root_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def get_embedding_path() -> Path:
    return _root_path(
        "SANAEBI_EMBEDDING_PATH",
        "artifacts/embeddings/nlpai-lab--KURE-v1/8b418a58414668e75532ed045c22d9ca018ae2b2",
    )


def get_retrieval_root() -> Path:
    return _root_path("SANAEBI_RETRIEVAL_ROOT", "var/retrieval")


def get_retrieval_baseline() -> Path | None:
    if not os.getenv("SANAEBI_RETRIEVAL_BASELINE"):
        return None
    return _root_path("SANAEBI_RETRIEVAL_BASELINE", "")


def get_retrieval_source() -> Path:
    return _root_path(
        "SANAEBI_RETRIEVAL_SOURCE", "data/company-knowledge/documents.jsonl"
    )
