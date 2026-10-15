"""Compatibility exports for server and archived trace consumers."""

import logging

from .callback import (
    GENERATION_STAGE,
    MODEL_STAGE,
    ROOT_STAGE,
    StageResolver,
    TraceCallback,
    stage_of,
)
from .context import _current_trace
from .events import (
    record_classification,
    record_generation,
    record_retrieval,
    record_routing,
)
from .middleware import TRACE_HEADER, TRACED_PATHS, TraceMiddleware
from .sink import DEFAULT_MAX_CHARS, clip_text, to_record, trace_directory, write_trace
from .stages import named_trace_config

logger = logging.getLogger("app.diagnostics.trace")

__all__ = [
    "DEFAULT_MAX_CHARS",
    "GENERATION_STAGE",
    "MODEL_STAGE",
    "ROOT_STAGE",
    "TRACED_PATHS",
    "TRACE_HEADER",
    "StageResolver",
    "TraceCallback",
    "TraceMiddleware",
    "_current_trace",
    "clip_text",
    "named_trace_config",
    "record_classification",
    "record_generation",
    "record_retrieval",
    "record_routing",
    "stage_of",
    "to_record",
    "trace_directory",
    "write_trace",
]
