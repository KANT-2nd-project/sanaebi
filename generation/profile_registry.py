"""Registry of supported runtime prompt profiles."""

from types import MappingProxyType

from generation.profile_texts import (
    _ANSWER_SCOPE_V1,
    _ANSWER_SCOPE_V3,
    _CONCISE_RULES,
    _RAG_SERVICE_RULES,
    _SERVICE_SCOPE_V5,
    _USER_FACING_EXAMPLES_V5,
    _USER_FACING_V4,
    DEFAULT_PROMPT_PROFILE,
    RAG_PROMPT_PROFILE,
)

_PROFILE_SUFFIXES = {
    "examples_answer_scope_v5": f"{_CONCISE_RULES}\n\n{_USER_FACING_EXAMPLES_V5}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}\n\n{_USER_FACING_V4}\n\n{_SERVICE_SCOPE_V5}",
}
_PROFILE_SUFFIXES[RAG_PROMPT_PROFILE] = (
    f"{_PROFILE_SUFFIXES[DEFAULT_PROMPT_PROFILE]}\n\n{_RAG_SERVICE_RULES}"
)

PROFILE_SUFFIXES = MappingProxyType(_PROFILE_SUFFIXES)
