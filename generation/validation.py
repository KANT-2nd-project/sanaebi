import json

from generation.types import GenerationResult, GenerationStatus


def parse_generation(raw_text: str) -> GenerationResult:
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError:
        return GenerationResult(
            status=GenerationStatus.PARSE_ERROR, raw_text=raw_text, answer=None
        )

    if not isinstance(value, dict):
        return GenerationResult(
            status=GenerationStatus.PARSE_ERROR, raw_text=raw_text, answer=None
        )

    answer = value.get("answer")

    if answer is None or type(answer) != str:
        return GenerationResult(
            status=GenerationStatus.PARSE_ERROR, raw_text=raw_text, answer=None
        )

    answer = answer.strip()

    if answer == "":
        return GenerationResult(
            status=GenerationStatus.EMPTY_ANSWER, raw_text=raw_text, answer=None
        )

    return GenerationResult(
        status=GenerationStatus.COMPLETED, raw_text=raw_text, answer=answer
    )
