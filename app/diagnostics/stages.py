"""Explicit Runnable labels and allowlisted diagnostic metadata."""

import math
from collections.abc import Mapping
from typing import Any

from contracts.classification import LABELS

from .sink import clip_text

_TRACE_STAGE_TAG = "trace_stage:"
_TRACE_ROLE_TAG = "trace_role:"

_STAGE_STRING_FIELDS = frozenset(
    {
        "snapshot_fingerprint",
        "spec_id",
        "retrieval_spec_id",
        "search_config_id",
        "status",
        "finish_reason",
        "provider",
        "model_name",
        "served_model",
        "prompt_sha256",
        "profile",
        "model",
        "role",
        "source",
    }
)
_STAGE_INTEGER_FIELDS = frozenset(
    {
        "candidate_count",
        "selected_count",
        "document_count",
        "chunk_count",
        "input_tokens",
        "output_tokens",
    }
)
_STAGE_NUMBER_FIELDS = frozenset(
    {"seconds", "elapsed_seconds", "classification_elapsed_seconds", "prompt_chars"}
)
_STAGE_LIST_FIELDS = frozenset(
    {"selected_chunk_ids", "expanded_chunk_ids", "scores", "ranks"}
)
_STAGE_ENUM_FIELDS = frozenset({"classification_label"})
_STAGE_METADATA_FIELDS = (
    _STAGE_STRING_FIELDS
    | _STAGE_INTEGER_FIELDS
    | _STAGE_NUMBER_FIELDS
    | _STAGE_LIST_FIELDS
    | _STAGE_ENUM_FIELDS
    | {"source_ranges"}
)


def _safe_stage_metadata(value: Any) -> dict[str, Any]:
    """Keep only scalar retrieval/generation metadata from Runnable state."""
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in _STAGE_METADATA_FIELDS:
            continue
        if key == "source_ranges":
            if not isinstance(item, (list, tuple)):
                continue
            ranges = []
            for span in item[:100]:
                if not isinstance(span, Mapping):
                    continue
                if (
                    span.get("kind") not in {"original", "expanded"}
                    or type(span.get("start")) is not int
                    or type(span.get("end")) is not int
                    or not 0 <= span["start"] < span["end"]
                    or not isinstance(span.get("document_id"), str)
                    or not isinstance(span.get("revision_id"), str)
                ):
                    continue
                ranges.append(
                    {
                        "document_id": clip_text(span["document_id"], limit=160),
                        "revision_id": clip_text(span["revision_id"], limit=160),
                        "kind": span["kind"],
                        "start": span["start"],
                        "end": span["end"],
                    }
                )
            safe[key] = ranges
        elif key in _STAGE_ENUM_FIELDS:
            if isinstance(item, str) and item in LABELS:
                safe[key] = item
        elif key in _STAGE_STRING_FIELDS:
            if isinstance(item, str):
                safe[key] = clip_text(item, limit=160)
        elif key in _STAGE_INTEGER_FIELDS:
            if isinstance(item, int) and not isinstance(item, bool):
                safe[key] = max(item, 0)
        elif key in _STAGE_NUMBER_FIELDS:
            if isinstance(item, int | float) and not isinstance(item, bool):
                numeric = float(item)
                if math.isfinite(numeric):
                    safe[key] = max(numeric, 0.0)
        elif key in _STAGE_LIST_FIELDS and isinstance(item, (list, tuple)):
            if key in {"selected_chunk_ids", "expanded_chunk_ids"}:
                safe[key] = [
                    clip_text(entry, limit=160)
                    for entry in item[:20]
                    if isinstance(entry, str)
                ]
            elif key == "ranks":
                safe[key] = [
                    int(entry)
                    for entry in item[:20]
                    if isinstance(entry, int | float)
                    and not isinstance(entry, bool)
                    and math.isfinite(float(entry))
                    and float(entry).is_integer()
                ]
            else:
                safe[key] = [
                    float(entry)
                    for entry in item[:20]
                    if isinstance(entry, int | float)
                    and not isinstance(entry, bool)
                    and math.isfinite(float(entry))
                ]
    return safe


def named_trace_config(*, run_name: str, stage: str, role: str) -> dict[str, Any]:
    """Return explicit LangChain config labels consumed by ``TraceCallback``.

    Use with ``runnable.with_config(**named_trace_config(...))``. ``stage`` and
    ``role`` are static application labels; user text belongs in the Runnable
    input and is intentionally excluded from generic stage rows.
    """
    labels = (run_name, stage, role)
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("run_name, stage, and role must be non-empty strings")
    return {
        "run_name": run_name,
        "tags": [f"{_TRACE_STAGE_TAG}{stage}", f"{_TRACE_ROLE_TAG}{role}"],
        "metadata": {
            "sanaebi_trace_run_name": run_name,
            "sanaebi_trace_stage": stage,
            "sanaebi_trace_role": role,
        },
    }
