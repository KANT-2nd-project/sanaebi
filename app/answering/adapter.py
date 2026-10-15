"""Serve the adopted generation pipeline from one immutable published snapshot."""

import hashlib
import json
from dataclasses import asdict
from threading import Lock
from time import perf_counter

from httpx import HTTPError
from openai import OpenAIError

from app.answering.output import LLMResponseError
from app.diagnostics.trace import record_generation
from app.documents.context import DocumentContextSnapshot
from generation.documents import render_document
from generation.presets import RuntimeSettings
from generation.providers import (
    GenerationProviderResponseError,
    build_managed_model_call,
)
from generation.service import generate_from_documents
from generation.types import GenerationPrompt, GenerationStatus


class GenerationAnswerer:
    def __init__(self, settings: RuntimeSettings):
        self.settings = settings
        self._client = None
        self._lock = Lock()
        self._closed = False

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

    def answer(self, question: str, snapshot: DocumentContextSnapshot) -> str:
        # Keep the full snapshot at this boundary. Render only once, in order.
        documents = [
            render_document(d.knowledge_id, d.title, d.body, d.revision)
            for d in snapshot.documents
        ]
        if not documents:
            raise ValueError("The question service must handle empty snapshots")
        started = perf_counter()
        metadata = {
            "model": self.settings.config.model_name,
            "profile": self.settings.prompt_profile,
            "config": asdict(self.settings.config),
            "snapshot_fingerprint": snapshot.fingerprint,
        }

        def call(prompt: GenerationPrompt):
            metadata["prompt_roles_sha256"] = hashlib.sha256(
                json.dumps(
                    {"system": prompt.system, "user": prompt.user},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            return self._get_client()(prompt)

        try:
            result = generate_from_documents(
                question,
                documents,
                call,
                prompt_profile=self.settings.prompt_profile,
            )
        except (OpenAIError, HTTPError, GenerationProviderResponseError) as exc:
            metadata.update(status="execution_error", error_type=type(exc).__name__)
            raise LLMResponseError("Generation provider failed") from exc
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
