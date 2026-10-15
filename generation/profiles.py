"""Build prompts from the explicit runtime and experiment profile registry."""

from collections.abc import Sequence

from generation.profile_registry import PROFILE_SUFFIXES
from generation.profile_texts import DEFAULT_PROMPT_PROFILE, RAG_PROMPT_PROFILE
from generation.prompts import build_prompt
from generation.types import GenerationPrompt

# Retain the historical private name for in-repository experiment scripts.
_PROFILE_SUFFIXES = PROFILE_SUFFIXES

__all__ = ["DEFAULT_PROMPT_PROFILE", "RAG_PROMPT_PROFILE", "build_profile_prompt"]


def build_profile_prompt(
    question: str,
    documents: Sequence[str],
    profile: str,
) -> GenerationPrompt:
    """Build a named prompt profile while preserving the baseline unchanged."""
    try:
        suffix = PROFILE_SUFFIXES[profile]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"알 수 없는 프롬프트 프로필입니다: {profile!r}") from exc

    prompt = build_prompt(question, documents)
    if not suffix:
        return prompt

    return GenerationPrompt(
        system=f"{prompt.system.rstrip()}\n\n{suffix}\n",
        user=prompt.user,
    )
