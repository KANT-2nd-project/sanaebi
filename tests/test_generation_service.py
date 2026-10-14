import unittest
from unittest.mock import Mock

from generation.prompts import build_prompt
from generation.service import generate
from generation.types import GenerationPrompt, GenerationResult, GenerationStatus


class GenerationServiceTests(unittest.TestCase):
    def setUp(self):
        self.prompt = GenerationPrompt(system="고정 규칙", user="테스트 질문")

    def test_response_contract_and_prompt_forwarding(self):
        cases = [
            ('{"answer": " 안내입니다. "}', GenerationStatus.COMPLETED, "안내입니다."),
            ("잘못된 JSON", GenerationStatus.PARSE_ERROR, None),
            ('{"answer": "   "}', GenerationStatus.EMPTY_ANSWER, None),
        ]
        for raw_text, status, answer in cases:
            with self.subTest(raw_text=raw_text):
                model_call = Mock(return_value=raw_text)
                result = generate(self.prompt, model_call)
                model_call.assert_called_once_with(self.prompt)
                self.assertIs(model_call.call_args.args[0], self.prompt)
                self.assertEqual(result, GenerationResult(status, raw_text, answer))

    def test_timeout_has_no_response(self):
        model_call = Mock(side_effect=TimeoutError)
        self.assertEqual(
            generate(self.prompt, model_call),
            GenerationResult(GenerationStatus.TIMEOUT, None, None),
        )
        model_call.assert_called_once_with(self.prompt)

    def test_unexpected_error_is_not_hidden(self):
        error = RuntimeError("unexpected failure")
        with self.assertRaises(RuntimeError) as caught:
            generate(self.prompt, Mock(side_effect=error))
        self.assertIs(caught.exception, error)

    def test_built_prompt_reaches_model_with_both_roles(self):
        prompt = build_prompt("연차 신청은?", ["인사 시스템에서 신청합니다."])

        def fake_model(received: GenerationPrompt) -> str:
            self.assertIs(received, prompt)
            self.assertIn("사내비", received.system)
            self.assertIn("연차 신청은?", received.user)
            self.assertIn("인사 시스템에서 신청합니다.", received.user)
            return '{"answer": " 인사 시스템에서 신청하세요. "}'

        result = generate(prompt, fake_model)
        self.assertEqual(result.status, GenerationStatus.COMPLETED)
        self.assertEqual(result.answer, "인사 시스템에서 신청하세요.")
