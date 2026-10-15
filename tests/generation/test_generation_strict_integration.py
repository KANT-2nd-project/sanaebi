"""Exercise the strict OpenAI adapter through the actual answer pipeline."""

import asyncio
import json
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from app.answering.adapter import GenerationAnswerer
from app.answering.input import AnswerInput
from generation.config import GenerationConfig, GenerationOutputMode, GenerationProvider
from generation.output_schema import OPENAI_ANSWER_RESPONSE_FORMAT
from generation.presets import RuntimeSettings


class StrictGenerationIntegrationTests(unittest.TestCase):
    def test_answerer_runs_prompt_value_through_public_sdk_once(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "gpt-6-luna",
            30,
            output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA,
        )
        settings = RuntimeSettings(config, "examples_answer_scope_v5")
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-6-luna",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"answer":"인사 포털에서 신청합니다."}',
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
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=body, request=request)

        http_client = httpx.Client(transport=httpx.MockTransport(respond))
        sdk_client = OpenAI(
            api_key="test-key",
            timeout=config.timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )
        reserve = Mock()
        answerer = GenerationAnswerer(settings, reserve)
        self.addCleanup(lambda: asyncio.run(answerer.aclose()))

        with patch("generation.providers.OpenAI", return_value=sdk_client):
            answer = answerer.answer_input(
                AnswerInput(
                    question="휴가 신청은 어디서 하나요?",
                    documents=("문서: 휴가\n본문: 인사 포털에서 신청합니다.",),
                    snapshot_fingerprint="snapshot-test",
                )
            )

        self.assertEqual(answer, "인사 포털에서 신청합니다.")
        reserve.assert_called_once()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/v1/chat/completions")
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["response_format"], OPENAI_ANSWER_RESPONSE_FORMAT)
        self.assertEqual(
            [message["role"] for message in payload["messages"]], ["system", "user"]
        )
        self.assertIn("휴가 신청은 어디서 하나요?", payload["messages"][1]["content"])
        self.assertIn("인사 포털에서 신청합니다.", payload["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
