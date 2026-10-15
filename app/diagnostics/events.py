"""Request-local diagnostic events, separate from callback and HTTP capture."""

import json
import logging
from collections.abc import Mapping
from typing import Any

from .context import _current_trace
from .stages import _safe_stage_metadata

logger = logging.getLogger("app.diagnostics.trace")


def record_classification(label: str) -> None:
    """Record the classification result for the current request, if enabled."""
    callback = _current_trace.get()
    if callback is not None:
        try:
            callback.record_classification(label)
        except Exception:  # noqa: BLE001 - diagnostics must not alter responses
            logger.warning("분류 trace 메타데이터 기록 실패")


def record_generation(fields: Mapping[str, Any]) -> None:
    """Record allowlisted generation outcome metadata for the current request."""
    callback = _current_trace.get()
    if callback is not None:
        try:
            callback.record_generation(fields)
        except Exception:  # noqa: BLE001 - omit exception text from safe logs
            logger.warning("생성 trace 메타데이터 기록 실패")


def record_routing(fields: Mapping[str, Any]) -> None:
    """Record safe routing state for the current request, if enabled."""
    callback = _current_trace.get()
    if callback is not None:
        try:
            callback.record_routing(fields)
        except Exception:  # noqa: BLE001 - diagnostics must not alter responses
            logger.warning("라우팅 trace 메타데이터 기록 실패")


def record_retrieval(
    *,
    status: str,
    seconds: float,
    selected_count: int,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Content-free summary; no user or model-provided strings are accepted."""
    if status not in {"ok", "failed"}:
        return
    safe = _safe_stage_metadata(metadata or {})
    safe.update(
        {
            "status": status,
            "seconds": round(max(seconds, 0.0), 6),
            "selected_count": max(int(selected_count), 0),
        }
    )
    try:
        callback = _current_trace.get()
        if callback is not None:
            callback.record_retrieval(safe)
        logger.info("%s", json.dumps({"event": "retrieval_result", **safe}))
    except Exception:  # noqa: BLE001 - observability never changes a response
        logger.warning("retrieval_result_log_failed")
