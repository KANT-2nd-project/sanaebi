import hashlib
import json
import sys
from collections.abc import Callable
from time import perf_counter

from generation.config import GenerationConfig
from generation.profiles import DEFAULT_PROMPT_PROFILE
from generation.service import generate_from_documents
from generation.types import GenerationPrompt, ModelResponse
from generation_evaluation.types import GenerationRun


def run_case(
    case_id: str,
    config: GenerationConfig,
    question: str,
    documents: list[str],
    model_call: Callable[[GenerationPrompt], ModelResponse],
    *,
    prompt_profile: str = DEFAULT_PROMPT_PROFILE,
) -> GenerationRun:
    # Input identity is prepared before the generation timing interval.
    documents_sha256 = hashlib.sha256(
        json.dumps(documents, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    prompt_sha256 = None

    def recorded_model_call(prompt: GenerationPrompt) -> ModelResponse:
        nonlocal prompt_sha256
        # Hash the exact role-separated messages passed to the provider adapter.
        prompt_sha256 = hashlib.sha256(
            json.dumps(
                {"system": prompt.system, "user": prompt.user},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return model_call(prompt)

    start_time = perf_counter()

    result = None
    error_type = None

    try:
        result = generate_from_documents(
            question=question,
            documents=documents,
            model_call=recorded_model_call,
            prompt_profile=prompt_profile,
        )
    except Exception as exc:  # noqa: BLE001
        error_type = type(exc).__name__
        print(f"[{case_id}] {error_type}", file=sys.stderr)
    elapsed_seconds = perf_counter() - start_time
    return GenerationRun(
        case_id=case_id,
        config=config,
        result=result,
        elapsed_seconds=elapsed_seconds,
        error_type=error_type,
        documents_sha256=documents_sha256,
        document_count=len(documents),
        prompt_sha256=prompt_sha256,
        prompt_profile=prompt_profile,
    )
