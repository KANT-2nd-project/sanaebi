import asyncio
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage
from openai import AsyncOpenAI, OpenAI

from generation.config import GenerationConfig, GenerationProvider
from generation.documents import load_documents, render_document
from generation.presets import (
    DEFAULT_EXPERIMENT,
    DEFAULT_MODEL,
    RuntimePreset,
    RuntimeSettings,
    load_preset,
    load_runtime_settings,
)
from generation.providers import (
    GenerationProviderResponseError,
    ManagedGenerationClient,
    build_managed_model_call,
    invoke_model,
    to_messages,
)
from generation.types import GenerationPrompt, ModelResponse
from tests.support.paths import ROOT


class GenerationServerSharedTests(unittest.TestCase):
    def test_runtime_settings_exclude_document_path_and_preset_stays_compatible(self):
        settings = load_runtime_settings(ROOT)
        preset = load_preset(ROOT)

        self.assertEqual(
            (DEFAULT_EXPERIMENT, DEFAULT_MODEL), ("company-final-v1", "gpt-6-luna")
        )
        self.assertIsInstance(settings, RuntimeSettings)
        self.assertFalse(hasattr(settings, "documents_path"))
        self.assertEqual(settings.config, preset.config)
        self.assertEqual(settings.prompt_profile, preset.prompt_profile)
        self.assertIsInstance(preset, RuntimePreset)
        self.assertEqual(
            preset.documents_path, ROOT / "tmp/generation-cli-documents.jsonl"
        )

    def test_document_renderer_matches_existing_jsonl_output(self):
        rendered = render_document(
            "knowledge-17", " 휴가 안내 ", "신청 방법\n담당자", 4
        )
        self.assertEqual(
            rendered,
            "문서 ID: knowledge-17\n개정: 4\n"
            "제목:  휴가 안내 \n본문:\n신청 방법\n담당자",
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "document_id": "knowledge-17",
                        "revision_number": 4,
                        "title": " 휴가 안내 ",
                        "document": "신청 방법\n담당자",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(load_documents(path), [rendered])

    def test_managed_factory_rejects_ollama_before_client_creation(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "local", 30)
        with patch("generation.providers.ChatOpenAI") as constructor:
            with self.assertRaisesRegex(ValueError, "OpenAI"):
                build_managed_model_call(config)
            constructor.assert_not_called()

    def test_installed_openai_clients_payload_omission_call_and_closure(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "gpt-6-luna",
            180,
            max_output_tokens=4096,
            reasoning_effort="xhigh",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            managed = ManagedGenerationClient(config)

        sync_client = managed._model.root_client
        async_client = managed._model.root_async_client
        self.assertIsInstance(sync_client, OpenAI)
        self.assertIsInstance(async_client, AsyncOpenAI)

        prompt = GenerationPrompt("최종 시스템 지침", "문서\n\n질문")
        payload = managed._model._get_request_payload(to_messages(prompt))
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertEqual(payload["reasoning_effort"], "xhigh")
        self.assertEqual(payload["max_completion_tokens"], 4096)
        self.assertNotIn("temperature", payload)

        raw = '{"answer":"안내합니다."}'
        with patch(
            "generation.providers.invoke_openai_message",
            return_value=AIMessage(content=raw),
        ) as invoke:
            self.assertEqual(managed(prompt), ModelResponse(raw))
        invoke.assert_called_once_with(config, managed._model, to_messages(prompt))

        self.assertFalse(sync_client._client.is_closed)
        self.assertFalse(async_client._client.is_closed)
        asyncio.run(managed.aclose())
        self.assertTrue(sync_client._client.is_closed)
        self.assertTrue(async_client._client.is_closed)
        asyncio.run(managed.aclose())
        with self.assertRaisesRegex(RuntimeError, "종료된"):
            managed(prompt)

    def test_managed_generation_surfaces_provider_response_error(self):
        config = GenerationConfig(GenerationProvider.OPENAI, "gpt-6-luna", 30)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            managed = ManagedGenerationClient(config)
        with (
            patch(
                "generation.providers.invoke_openai_message",
                return_value=AIMessage(content=[]),
            ),
            self.assertRaises(GenerationProviderResponseError),
        ):
            managed(GenerationPrompt("규칙", "질문"))
        asyncio.run(managed.aclose())

    def test_provider_response_error_remains_type_error_compatible(self):
        self.assertTrue(issubclass(GenerationProviderResponseError, TypeError))

    def test_provider_response_shape_and_refusal_errors_are_explicit(self):
        prompt = GenerationPrompt("규칙", "질문")
        with self.assertRaises(GenerationProviderResponseError):
            invoke_model(prompt, lambda _messages: "잘못된 응답")
        with self.assertRaises(GenerationProviderResponseError):
            invoke_model(
                prompt,
                lambda _messages: AIMessage(
                    content="거절", additional_kwargs={"refusal": ["잘못된 값"]}
                ),
            )


if __name__ == "__main__":
    unittest.main()
