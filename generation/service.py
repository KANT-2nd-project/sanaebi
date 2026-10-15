"""Named LCEL generation pipeline and compatibility entrypoints."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from httpx import TimeoutException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from openai import APITimeoutError

from generation.advisory import ClassificationContext, compose_advisory
from generation.evidence import compose_evidence_state
from generation.profiles import DEFAULT_PROMPT_PROFILE, build_profile_prompt
from generation.providers import model_response_from_ai_message
from generation.types import (
    GenerationPrompt,
    GenerationResult,
    GenerationStatus,
    ModelResponse,
)
from generation.validation import parse_generation


def _build_prompt_values(values: Mapping[str, Any]) -> dict[str, str]:
    prompt = build_profile_prompt(
        str(values["question"]),
        values["documents"],
        str(values["prompt_profile"]),
    )
    prompt = compose_advisory(prompt, values.get("classification_context"))
    evidence_state = values.get("evidence_state")
    if evidence_state is not None:
        prompt = compose_evidence_state(prompt, evidence_state)
    return {"system": prompt.system, "user": prompt.user}


def _normalize_response(value: object) -> ModelResponse:
    if isinstance(value, ModelResponse):
        return value
    return model_response_from_ai_message(value)


def _validate_response(response: ModelResponse) -> GenerationResult:
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


def _trace_config(name: str, stage: str, role: str) -> dict[str, Any]:
    return {
        "run_name": name,
        "tags": [f"trace_stage:{stage}", f"trace_role:{role}"],
        "metadata": {
            "sanaebi_trace_run_name": name,
            "sanaebi_trace_stage": stage,
            "sanaebi_trace_role": role,
        },
    }


def _named(runnable: Runnable, name: str, stage: str, role: str) -> Runnable:
    return runnable.with_config(**_trace_config(name, stage, role))


def build_generation_pipeline(
    model: Runnable,
    *,
    before_model: Callable[[PromptValue], PromptValue] | None = None,
) -> Runnable:
    """Build a named render → prompt → model → normalize → validate sequence."""
    pipeline = _named(
        RunnableLambda(_build_prompt_values),
        "generation_profile",
        "generation_profile",
        "transform",
    ) | _named(
        ChatPromptTemplate.from_messages([("system", "{system}"), ("human", "{user}")]),
        "generation_chat_prompt",
        "generation_prompt",
        "transform",
    )
    if before_model is None:
        model_input = _named(
            RunnablePassthrough(),
            "generation_model_input",
            "generation_model_input",
            "transform",
        )
    else:
        model_input = _named(
            RunnableLambda(before_model),
            "generation_model_input",
            "generation_model_input",
            "transform",
        )
    return (
        pipeline
        | model_input
        | _named(model, "generation_model", "generation_model", "model")
        | _named(
            RunnableLambda(_normalize_response),
            "generation_normalize_response",
            "generation_normalize",
            "transform",
        )
        | _named(
            RunnableLambda(_validate_response),
            "generation_validate_result",
            "generation_validate",
            "transform",
        )
    ).with_config(
        run_name="generation_answer",
        tags=["trace_stage:generation", "trace_role:answer"],
    )


class CallableModelAdapter:
    """Adapt the stable GenerationPrompt callback API to a prompt-value input."""

    def __init__(self, model_call: Callable[[GenerationPrompt], ModelResponse]):
        self.model_call = model_call

    def __call__(self, prompt_value: PromptValue) -> ModelResponse:
        messages = prompt_value.to_messages()
        if (
            len(messages) != 2
            or not isinstance(messages[0], SystemMessage)
            or not isinstance(messages[1], HumanMessage)
            or not isinstance(messages[0].content, str)
            or not isinstance(messages[1].content, str)
        ):
            raise TypeError("생성 프롬프트는 system/user 문자열 메시지여야 합니다.")
        return self.model_call(
            GenerationPrompt(system=messages[0].content, user=messages[1].content)
        )


def generate(
    prompt: GenerationPrompt,
    model_call: Callable[[GenerationPrompt], ModelResponse],
) -> GenerationResult:
    try:
        response = model_call(prompt)
    except (TimeoutError, TimeoutException, APITimeoutError):
        return GenerationResult(
            status=GenerationStatus.TIMEOUT,
            raw_text=None,
            answer=None,
        )
    return _validate_response(response)


def run_generation_pipeline(
    *,
    question: str,
    documents: Sequence[str],
    model: Runnable,
    prompt_profile: str = DEFAULT_PROMPT_PROFILE,
    classification_context: ClassificationContext | None = None,
    evidence_state: str | None = None,
    before_model: Callable[[PromptValue], PromptValue] | None = None,
) -> GenerationResult:
    pipeline = build_generation_pipeline(model, before_model=before_model)
    try:
        return pipeline.invoke(
            {
                "question": question,
                "documents": documents,
                "prompt_profile": prompt_profile,
                "classification_context": classification_context,
                "evidence_state": evidence_state,
            }
        )
    except (TimeoutError, TimeoutException, APITimeoutError):
        return GenerationResult(
            status=GenerationStatus.TIMEOUT,
            raw_text=None,
            answer=None,
        )


def generate_from_documents(
    question: str,
    documents: list[str],
    model_call: Callable[[GenerationPrompt], ModelResponse],
    *,
    prompt_profile: str = DEFAULT_PROMPT_PROFILE,
    classification_context: ClassificationContext | None = None,
    evidence_state: str | None = None,
) -> GenerationResult:
    return run_generation_pipeline(
        question=question,
        documents=documents,
        model=RunnableLambda(CallableModelAdapter(model_call)),
        prompt_profile=prompt_profile,
        classification_context=classification_context,
        evidence_state=evidence_state,
    )
