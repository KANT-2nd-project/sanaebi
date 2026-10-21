"""Explicit output-format fixture for frozen prompt_json experiment tests."""

from dataclasses import replace

from generation.config import GenerationOutputMode
from generation.presets import load_runtime_settings
from tests.support.paths import ROOT


def historical_prompt_json_settings(root=ROOT):
    settings = load_runtime_settings(root)
    return replace(
        settings,
        config=replace(settings.config, output_mode=GenerationOutputMode.PROMPT_JSON),
    )
