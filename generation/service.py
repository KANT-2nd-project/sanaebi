from collections.abc import Callable

from generation.types import GenerationPrompt, GenerationResult, GenerationStatus
from generation.validation import parse_generation


def generate(
    prompt: GenerationPrompt,
    model_call: Callable[[GenerationPrompt], str],
) -> GenerationResult:
    try:
        raw_text = model_call(prompt)
    except TimeoutError:
        return GenerationResult(
            status=GenerationStatus.TIMEOUT, raw_text=None, answer=None
        )

    return parse_generation(raw_text)
