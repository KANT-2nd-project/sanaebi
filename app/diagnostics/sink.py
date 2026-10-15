"""Trace serialization and the append-only JSONL sink."""

import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_MAX_CHARS = 2000
_write_lock = threading.Lock()


def trace_directory() -> Path | None:
    """기록 폴더. TRACE_DIR이 비어 있으면 기록하지 않는다."""
    configured = os.environ.get("TRACE_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


def _max_chars() -> int:
    try:
        return max(int(os.environ.get("TRACE_MAX_CHARS", DEFAULT_MAX_CHARS)), 0)
    except ValueError:
        return DEFAULT_MAX_CHARS


def _full_prompt() -> bool:
    return os.environ.get("TRACE_FULL_PROMPT", "").strip() == "1"


def clip_text(text: str, limit: int | None = None) -> str | dict:
    """긴 문자열은 앞부분과 전체 길이·sha256만 남긴다."""
    limit = _max_chars() if limit is None else limit
    if len(text) <= limit:
        return text
    return {
        "head": text[:limit],
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def to_record(value: Any, limit: int | None = None) -> Any:
    """콜백 값을 JSON으로 쓸 수 있는 형태로 바꾼다. 모르는 객체는 문자열로 남긴다."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return clip_text(value, limit)
    if isinstance(value, dict):
        return {str(key): to_record(item, limit) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_record(item, limit) for item in value]
    for name in ("model_dump", "dict"):
        dump = getattr(value, name, None)
        if callable(dump):
            try:
                return to_record(dump(), limit)
            except Exception:  # noqa: BLE001
                break
    return clip_text(repr(value), limit)


def _body_record(chunks: list[bytes]) -> Any:
    body = b"".join(chunks).decode("utf-8", errors="replace")
    if not body:
        return None
    try:
        return to_record(json.loads(body))
    except json.JSONDecodeError:
        return clip_text(body)


def write_trace(directory: Path, record: dict) -> Path:
    """기록 1건을 날짜별 JSONL 파일 끝에 추가한다."""
    path = directory / f"{datetime.now().astimezone():%Y-%m-%d}.jsonl"
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _write_lock:
        directory.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n")
    return path
