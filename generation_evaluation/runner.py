from collections.abc import Callable
from time import perf_counter

from generation.config import GenerationConfig
from generation.service import generate_from_documents
from generation.types import GenerationPrompt
from generation_evaluation.types import GenerationRun


def run_case(
    case_id: str,
    config: GenerationConfig,
    question: str,
    documents: list[str],
    model_call: Callable[[GenerationPrompt], str],
) -> GenerationRun:
    start_time = perf_counter()

    result = None
    error_type = None

    try:
        result = generate_from_documents(
            question=question,
            documents=documents,
            model_call=model_call,
        )
    except Exception as exc:  # noqa: BLE001
        error_type = type(exc).__name__
    elapsed_seconds = perf_counter() - start_time
    return GenerationRun(
        case_id=case_id,
        config=config,
        result=result,
        elapsed_seconds=elapsed_seconds,
        error_type=error_type,
    )
