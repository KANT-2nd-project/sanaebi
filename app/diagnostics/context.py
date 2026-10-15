"""Request-local callback context inherited by LangChain Runnable calls."""

from contextvars import ContextVar
from typing import Any

from langchain_core.tracers.context import register_configure_hook

_current_trace: ContextVar[Any | None] = ContextVar("sanaebi_trace", default=None)
register_configure_hook(_current_trace, inheritable=True)
