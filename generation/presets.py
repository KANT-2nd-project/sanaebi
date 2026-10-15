"""Shared model and prompt configuration; CLI presets add document snapshots."""

import json
from dataclasses import dataclass
from pathlib import Path

from generation.config import GenerationConfig, config_from_dict
from generation.profiles import DEFAULT_PROMPT_PROFILE, build_profile_prompt

DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_EXPERIMENT = "company-final-v1"


@dataclass(frozen=True)
class RuntimePreset:
    config: GenerationConfig
    documents_path: Path
    prompt_profile: str


@dataclass(frozen=True)
class RuntimeSettings:
    """Model and prompt settings that do not depend on a document source."""

    config: GenerationConfig
    prompt_profile: str


def load_runtime_settings(
    root: Path,
    experiment: str = DEFAULT_EXPERIMENT,
    model: str = DEFAULT_MODEL,
) -> RuntimeSettings:
    directory = root / "generation"
    models = json.loads((directory / "models.json").read_text(encoding="utf-8"))
    experiments = json.loads(
        (directory / "experiments.json").read_text(encoding="utf-8")
    )
    if experiment not in experiments:
        raise ValueError(f"등록되지 않은 실험입니다: {experiment}")
    if model not in models:
        raise ValueError(f"등록되지 않은 모델입니다: {model}")
    preset = experiments[experiment]
    if model not in preset["models"]:
        raise ValueError(f"{experiment} 실험에 등록되지 않은 모델입니다: {model}")
    profile = preset.get("prompt_profile", DEFAULT_PROMPT_PROFILE)
    build_profile_prompt("설정 검사", [], profile)
    return RuntimeSettings(
        config=config_from_dict(models[model]),
        prompt_profile=profile,
    )


def load_preset(
    root: Path,
    experiment: str = DEFAULT_EXPERIMENT,
    model: str = DEFAULT_MODEL,
) -> RuntimePreset:
    """Load CLI settings and the explicitly exported JSONL snapshot path."""
    settings = load_runtime_settings(root, experiment, model)
    experiments = json.loads(
        (root / "generation" / "experiments.json").read_text(encoding="utf-8")
    )
    return RuntimePreset(
        config=settings.config,
        documents_path=root / experiments[experiment]["documents"],
        prompt_profile=settings.prompt_profile,
    )
