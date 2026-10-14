"""이음웍스 정책 문서의 기본 경로."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCUMENTS_PATH = PROJECT_ROOT / "data" / "company-knowledge" / "documents.jsonl"


def get_documents_path() -> Path:
    """IEUM_WORKS_PATH가 있으면 사용하고, 없으면 정책 데이터 경로를 반환한다."""
    configured_path = os.getenv("IEUM_WORKS_PATH")
    return Path(configured_path) if configured_path else DEFAULT_DOCUMENTS_PATH
