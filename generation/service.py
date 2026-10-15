from collections.abc import Callable
from dataclasses import replace

from generation.prompts import build_prompt
from generation.types import (
    GenerationPrompt,
    GenerationResult,
    GenerationStatus,
    ModelResponse,
)
from generation.validation import parse_generation


def generate(
    prompt: GenerationPrompt,
    model_call: Callable[[GenerationPrompt], ModelResponse],
) -> GenerationResult:
    try:
        response = model_call(prompt)
    except TimeoutError:
        return GenerationResult(
            status=GenerationStatus.TIMEOUT,
            raw_text=None,
            answer=None,
        )

    if response.refusal is not None and response.refusal.strip():
        return GenerationResult(
            status=GenerationStatus.REFUSAL,
            raw_text=response.raw_text,
            answer=None,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            finish_reason=response.finish_reason,
            refusal=response.refusal,
        )

    if response.finish_reason == "length":
        return GenerationResult(
            status=GenerationStatus.TRUNCATED,
            raw_text=response.raw_text,
            answer=None,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            finish_reason=response.finish_reason,
        )

    if response.raw_text is None:
        raise ValueError("거절 정보가 없는 모델 응답에는 raw_text가 필요합니다.")

    parsed = parse_generation(response.raw_text)

    return replace(
        parsed,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        finish_reason=response.finish_reason,
    )


def generate_from_documents(
    question: str,
    documents: list[str],
    model_call: Callable[[GenerationPrompt], ModelResponse],
) -> GenerationResult:
    prompt = build_prompt(question, documents)
    return generate(prompt=prompt, model_call=model_call)
