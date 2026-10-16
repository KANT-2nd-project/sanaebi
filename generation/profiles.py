"""Build prompts from the explicit runtime and experiment profile registry."""

import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from generation.profile_registry import PROFILE_SUFFIXES
from generation.profile_texts import DEFAULT_PROMPT_PROFILE, RAG_PROMPT_PROFILE
from generation.prompts import build_prompt
from generation.rag_readability import (
    EXPERIMENT_PROFILE_SUFFIXES,
    RAG_READABILITY_V6_PROFILE,
    RAG_READABILITY_V7_PROFILE,
    RAG_SUPPORTED_PROFILES,
)
from generation.types import GenerationPrompt

# Retain the historical private name for in-repository experiment scripts.
_PROFILE_SUFFIXES = PROFILE_SUFFIXES

__all__ = [
    "DEFAULT_PROMPT_PROFILE",
    "RAG_PROMPT_PROFILE",
    "RAG_READABILITY_V6_PROFILE",
    "RAG_READABILITY_V7_PROFILE",
    "RAG_SUPPORTED_PROFILES",
    "build_profile_prompt",
]


def build_profile_prompt(
    question: str,
    documents: Sequence[str],
    profile: str,
) -> GenerationPrompt:
    """Build a named prompt profile while preserving the baseline unchanged."""
    try:
        suffix = (
            PROFILE_SUFFIXES[profile]
            if profile in PROFILE_SUFFIXES
            else EXPERIMENT_PROFILE_SUFFIXES[profile]
            if profile in EXPERIMENT_PROFILE_SUFFIXES
            else _archived_suffixes()[profile]
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"알 수 없는 프롬프트 프로필입니다: {profile!r}") from exc

    prompt = build_prompt(question, documents)
    if not suffix:
        return prompt

    return GenerationPrompt(
        system=f"{prompt.system.rstrip()}\n\n{suffix}\n",
        user=prompt.user,
    )


@lru_cache(maxsize=1)
def _archived_suffixes() -> dict[str, str]:
    """Load retired candidates only for explicitly named historical runs."""
    path = Path(__file__).parent / "archive" / "prompt_profiles.json"
    return json.loads(path.read_text(encoding="utf-8"))
