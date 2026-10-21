"""Exercise the strict OpenAI adapter through the actual answer pipeline."""

import asyncio
import json
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from app.answering.adapter import GenerationAnswerer
from app.answering.input import AnswerInput
from app.answering.output import LLMResponseError
from generation.config import GenerationOutputMode
from generation.output_schema import OPENAI_ANSWER_RESPONSE_FORMAT
from generation.presets import load_preset, load_runtime_settings
from tests.support.paths import ROOT


class StrictGenerationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_runtime_settings(ROOT)
        self.assertIs(
            self.settings.config.output_mode, GenerationOutputMode.STRICT_JSON_SCHEMA
        )
        self.assertEqual(self.settings.config, load_preset(ROOT).config)
        self.answer = "인사 포털에서 신청합니다.\n\n1. 날짜를 선택합니다.\n2. **신청**을 누릅니다."
        self.status_code = 200
        self.body = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-6-luna",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {"answer": self.answer}, ensure_ascii=False
                        ),
                        "refusal": None,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        self.requests = []

        def respond(request):
            self.requests.append(request)
            return httpx.Response(self.status_code, json=self.body, request=request)

        http_client = httpx.Client(transport=httpx.MockTransport(respond))
        self.sdk_client = OpenAI(
            api_key="test-key",
            timeout=self.settings.config.timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )
        self.addCleanup(self.sdk_client.close)
        self.reserve = Mock()
        self.answerer = GenerationAnswerer(self.settings, self.reserve)
        self.addCleanup(lambda: asyncio.run(self.answerer.aclose()))
        provider = patch("generation.providers.OpenAI", return_value=self.sdk_client)
        provider.start()
        self.addCleanup(provider.stop)

    def answer_once(self):
        return self.answerer.answer_input(
            AnswerInput(
                question="휴가 신청은 어디서 하나요?",
                documents=("문서: 휴가\n본문: 인사 포털에서 신청합니다.",),
                snapshot_fingerprint="snapshot-test",
            )
        )

    def assert_single_strict_call_and_close(self):
        self.reserve.assert_called_once()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].url.path, "/v1/chat/completions")
        payload = json.loads(self.requests[0].content)
        self.assertEqual(payload["response_format"], OPENAI_ANSWER_RESPONSE_FORMAT)
        self.assertEqual(payload["model"], self.settings.config.model_name)
        self.assertEqual(
            payload["max_completion_tokens"], self.settings.config.max_output_tokens
        )
        self.assertEqual(payload["reasoning_effort"], "xhigh")
        self.assertNotIn("temperature", payload)
        self.assertEqual(
            [message["role"] for message in payload["messages"]], ["system", "user"]
        )
        self.assertIn("휴가 신청은 어디서 하나요?", payload["messages"][1]["content"])
        self.assertIn("인사 포털에서 신청합니다.", payload["messages"][1]["content"])
        self.assertFalse(self.sdk_client.is_closed())
        asyncio.run(self.answerer.aclose())
        self.assertTrue(self.sdk_client.is_closed())
        asyncio.run(self.answerer.aclose())

    def test_active_preset_sends_strict_schema_and_preserves_markdown(self):
        self.assertEqual(self.answer_once(), self.answer)
        self.assert_single_strict_call_and_close()

    def test_refusal_is_preserved_without_retry(self):
        self.body["choices"][0]["message"].update(
            content=None, refusal="private refusal"
        )
        with self.assertRaisesRegex(LLMResponseError, "Generation status: refusal"):
            self.answer_once()
        self.assert_single_strict_call_and_close()

    def test_length_stop_rejects_even_complete_json_without_retry(self):
        self.body["choices"][0]["finish_reason"] = "length"
        with self.assertRaisesRegex(LLMResponseError, "Generation status: truncated"):
            self.answer_once()
        self.assert_single_strict_call_and_close()

    def test_provider_failure_does_not_retry_or_fall_back(self):
        self.status_code = 503
        self.body = {"error": {"message": "private provider error"}}
        with self.assertRaisesRegex(LLMResponseError, "Generation provider failed"):
            self.answer_once()
        self.assert_single_strict_call_and_close()


if __name__ == "__main__":
    unittest.main()
