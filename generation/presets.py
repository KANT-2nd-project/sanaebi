"""Shared independent CLI configuration; no server or document loading."""

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


def load_preset(
    root: Path,
    experiment: str = DEFAULT_EXPERIMENT,
    model: str = DEFAULT_MODEL,
) -> RuntimePreset:
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
    return RuntimePreset(
        config=config_from_dict(models[model]),
        documents_path=root / preset["documents"],
        prompt_profile=profile,
    )
