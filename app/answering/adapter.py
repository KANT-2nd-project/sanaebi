"""Serve generated answers from one immutable full or retrieved input."""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import partial
from inspect import getattr_static
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING

from httpx import HTTPError
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import RunnableLambda
from openai import OpenAIError

from app.answering.input import AnswerInput
from app.answering.output import LLMResponseError
from app.diagnostics.trace import record_generation
from app.documents.context import DocumentContextSnapshot
from app.public_limits import (
    GenerationBudgetExceeded,
    GenerationBudgetUnavailable,
)
from generation.advisory import ClassificationContext
from generation.presets import RuntimeSettings
from generation.profiles import RAG_SUPPORTED_PROFILES
from generation.providers import (
    GenerationProviderResponseError,
    ManagedGenerationClient,
    build_managed_model_call,
)
from generation.service import (
    CallableModelAdapter,
    run_generation_pipeline,
)
from generation.types import GenerationStatus

if TYPE_CHECKING:
    from app.retrieval.types import RetrievedContext

logger = logging.getLogger("uvicorn.error")


@dataclass
class _GenerationAttempt:
    metadata: dict[str, object]
    reserve_generation: Callable[[], None] | None
    provider_attempted: bool = False


def _prepare_model_call(
    prompt_value: PromptValue, attempt: _GenerationAttempt
) -> PromptValue:
    messages = prompt_value.to_messages()
    if (
        len(messages) != 2
        or not isinstance(messages[0].content, str)
        or not isinstance(messages[1].content, str)
    ):
        raise TypeError("생성 프롬프트는 system/user 문자열 메시지여야 합니다.")
    attempt.metadata["prompt_roles_sha256"] = hashlib.sha256(
        json.dumps(
            {"system": messages[0].content, "user": messages[1].content},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if attempt.reserve_generation is not None:
        attempt.reserve_generation()
    attempt.provider_attempted = True
    return prompt_value


def _client_runnable(client):
    try:
        getattr_static(client, "runnable")
    except AttributeError:
        return RunnableLambda(CallableModelAdapter(client))
    return client.runnable


class GenerationAnswerer:
    def __init__(
        self,
        settings: RuntimeSettings,
        reserve_generation: Callable[[], None] | None = None,
    ):
        self.settings = settings
        self.reserve_generation = reserve_generation
        self._client: ManagedGenerationClient | None = None
        self._lock = Lock()
        self._closed = False

    @property
    def supports_empty_retrieval(self):
        return self.settings.prompt_profile in RAG_SUPPORTED_PROFILES

    def _get_client(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("Generation answerer is closed")
            if self._client is None:
                self._client = build_managed_model_call(self.settings.config)
            return self._client

    async def aclose(self):
        with self._lock:
            self._closed = True
            client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def answer(
        self,
        question: str,
        snapshot: DocumentContextSnapshot,
        *,
        classification_context: ClassificationContext | None = None,
    ) -> str:
        answer_input = AnswerInput.from_snapshot(
            question,
            snapshot,
            classification_context=classification_context,
        )
        if not answer_input.documents:
            raise ValueError("The question service must handle empty snapshots")
        return self.answer_input(answer_input)

    def answer_retrieved(
        self,
        question: str,
        context: "RetrievedContext",
        *,
        classification_context: ClassificationContext | None = None,
    ) -> str:
        answer_input = AnswerInput.from_retrieved(
            question,
            context,
            classification_context=classification_context,
        )
        if not answer_input.documents and not self.supports_empty_retrieval:
            raise ValueError("Retrieval must provide at least one evidence item")
        evidence_state = (
            answer_input.evidence_state if self.supports_empty_retrieval else None
        )
        return self._generate(answer_input, evidence_state=evidence_state)

    def answer_input(self, answer_input: AnswerInput) -> str:
        if not answer_input.documents and not self.supports_empty_retrieval:
            raise ValueError("The question service must handle empty evidence")
        evidence_state = (
            answer_input.evidence_state if self.supports_empty_retrieval else None
        )
        return self._generate(answer_input, evidence_state=evidence_state)

    def _generate(
        self,
        answer_input: AnswerInput,
        *,
        evidence_state: str | None = None,
    ) -> str:
        started = perf_counter()
        metadata: dict[str, object] = {
            "model": self.settings.config.model_name,
            "profile": self.settings.prompt_profile,
            "config": asdict(self.settings.config),
            "snapshot_fingerprint": answer_input.snapshot_fingerprint,
            "evidence_state": evidence_state,
        }
        attempt = _GenerationAttempt(metadata, self.reserve_generation)

        try:
            client = self._get_client()
            result = run_generation_pipeline(
                question=answer_input.question,
                documents=answer_input.documents,
                model=_client_runnable(client),
                prompt_profile=self.settings.prompt_profile,
                classification_context=answer_input.classification_context,
                evidence_state=evidence_state,
                before_model=partial(_prepare_model_call, attempt=attempt),
            )
        except (OpenAIError, HTTPError, GenerationProviderResponseError) as exc:
            metadata.update(status="execution_error", error_type=type(exc).__name__)
            raise LLMResponseError("Generation provider failed") from exc
        except GenerationBudgetExceeded:
            metadata.update(status="budget_exhausted")
            raise
        except GenerationBudgetUnavailable:
            metadata.update(status="budget_unavailable")
            raise
        except Exception as exc:
            # Preserve unexpected programming errors as 500, with safe metadata.
            metadata.update(status="internal_error", error_type=type(exc).__name__)
            raise
        else:
            metadata.update(
                status=result.status.value,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                finish_reason=result.finish_reason,
            )
            if result.status is not GenerationStatus.COMPLETED:
                raise LLMResponseError(f"Generation status: {result.status.value}")
            return result.answer
        finally:
            metadata["seconds"] = perf_counter() - started
            record_generation(metadata)
            safe_log = {
                "event": "generation_result",
                "status": metadata.get("status", "internal_error"),
                "provider_attempted": attempt.provider_attempted,
                "input_tokens": metadata.get("input_tokens"),
                "output_tokens": metadata.get("output_tokens"),
                "seconds": metadata["seconds"],
            }
            try:
                logger.info(
                    "%s",
                    json.dumps(safe_log, ensure_ascii=False, separators=(",", ":")),
                )
            except Exception:  # noqa: BLE001 - observability must not alter answers
                logger.warning("generation_result_log_failed")
