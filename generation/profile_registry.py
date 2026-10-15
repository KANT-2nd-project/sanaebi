"""Explicit registry for runtime and historical generation prompt profiles."""

from types import MappingProxyType

from generation.profile_texts import (
    _ANSWER_SCOPE_V1,
    _ANSWER_SCOPE_V2,
    _ANSWER_SCOPE_V3,
    _COMPLETENESS_V7_RULES,
    _CONCISE_RULES,
    _CONDITION_LINK,
    _COVERAGE_CHECK,
    _JSON_EXAMPLES,
    _RAG_SERVICE_RULES,
    _READABILITY_V6,
    _READABILITY_V7_EXAMPLES,
    _READABILITY_V7_RULES,
    _SERVICE_SCOPE_V5,
    _SYNTHETIC_EXAMPLES,
    _USER_FACING_EXAMPLES_V5,
    _USER_FACING_V4,
    DEFAULT_PROMPT_PROFILE,
    RAG_PROMPT_PROFILE,
)

_PROFILE_SUFFIXES = {
    "examples_answer_scope_v5": f"{_CONCISE_RULES}\n\n{_USER_FACING_EXAMPLES_V5}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}\n\n{_USER_FACING_V4}\n\n{_SERVICE_SCOPE_V5}",
    "examples_answer_scope_v4": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}\n\n{_USER_FACING_V4}",
    "examples_answer_scope_v3": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}",
    "examples_answer_scope_v2": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V2}",
    "examples_answer_scope_v1": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}\n\n{_ANSWER_SCOPE_V1}",
    "examples_coverage": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}\n\n{_COVERAGE_CHECK}",
    "examples_conditions": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}\n\n{_CONDITION_LINK}",
    "examples_json": f"{_CONCISE_RULES}\n\n{_JSON_EXAMPLES}",
    "baseline": "",
    "concise": _CONCISE_RULES,
    "examples": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}",
    "examples_answer_scope_v6": f"{_CONCISE_RULES}\n\n{_USER_FACING_EXAMPLES_V5}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}\n\n{_USER_FACING_V4}\n\n{_SERVICE_SCOPE_V5}\n\n{_READABILITY_V6}",
    "examples_answer_scope_v7_readability": f"{_CONCISE_RULES}\n\n{_USER_FACING_EXAMPLES_V5}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}\n\n{_USER_FACING_V4}\n\n{_SERVICE_SCOPE_V5}\n\n{_READABILITY_V7_RULES}\n\n{_READABILITY_V7_EXAMPLES}",
    "examples_answer_scope_v7_completeness": f"{_CONCISE_RULES}\n\n{_USER_FACING_EXAMPLES_V5}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}\n\n{_USER_FACING_V4}\n\n{_SERVICE_SCOPE_V5}\n\n{_COMPLETENESS_V7_RULES}",
    "examples_answer_scope_v7_combined": f"{_CONCISE_RULES}\n\n{_USER_FACING_EXAMPLES_V5}\n\n{_ANSWER_SCOPE_V1}\n\n{_ANSWER_SCOPE_V3}\n\n{_USER_FACING_V4}\n\n{_SERVICE_SCOPE_V5}\n\n{_READABILITY_V7_RULES}\n\n{_READABILITY_V7_EXAMPLES}\n\n{_COMPLETENESS_V7_RULES}",
}
_PROFILE_SUFFIXES[RAG_PROMPT_PROFILE] = (
    f"{_PROFILE_SUFFIXES[DEFAULT_PROMPT_PROFILE]}\n\n{_RAG_SERVICE_RULES}"
)

PROFILE_SUFFIXES = MappingProxyType(_PROFILE_SUFFIXES)
