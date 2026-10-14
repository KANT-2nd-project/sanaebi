import unittest
from unittest.mock import Mock

from generation.prompts import build_prompt
from generation.service import generate, generate_from_documents
from generation.types import (
    GenerationPrompt,
    GenerationResult,
    GenerationStatus,
    ModelResponse,
)


class GenerationServiceTests(unittest.TestCase):
    def test_length_stop_overrides_valid_invalid_and_empty_json(self):
        for raw in ('{"answer":"안내"}', '{"answer":', ""):
            with self.subTest(raw=raw):
                response = ModelResponse(raw, 100, 512, "length")
                result = generate(self.prompt, Mock(return_value=response))
                self.assertEqual(
                    result,
                    GenerationResult(
                        GenerationStatus.TRUNCATED, raw, None, 100, 512, "length"
                    ),
                )

    def test_metadata_survives_parsing_success_and_failure(self):
        for raw, status in (
            ('{"answer":"안내"}', GenerationStatus.COMPLETED),
            ('{"answer":" "}', GenerationStatus.EMPTY_ANSWER),
            ("bad JSON", GenerationStatus.PARSE_ERROR),
        ):
            with self.subTest(status=status):
                response = ModelResponse(raw, 25, 0, "stop")
                result = generate(self.prompt, Mock(return_value=response))
                self.assertEqual(result.status, status)
                self.assertEqual(
                    (result.input_tokens, result.output_tokens, result.finish_reason),
                    (25, 0, "stop"),
                )

    def test_document_entrypoint_builds_prompt_and_preserves_result(self):
        documents = ["예약은 사내 포털에서 합니다.", "승인자는 팀장입니다."]
        original = documents.copy()
        raw = ' {"answer": " 포털에서 예약하세요. "}\n'
        model_call = Mock(return_value=ModelResponse(raw))

        result = generate_from_documents("어디서 예약하나요?", documents, model_call)

        model_call.assert_called_once()
        prompt = model_call.call_args.args[0]
        self.assertIsInstance(prompt, GenerationPrompt)
        self.assertIn("사내비", prompt.system)
        self.assertIn("어디서 예약하나요?", prompt.user)
        for document in documents:
            self.assertIn(document, prompt.user)
        self.assertEqual(documents, original)
        self.assertEqual(
            result,
            GenerationResult(GenerationStatus.COMPLETED, raw, "포털에서 예약하세요."),
        )

    def test_document_entrypoint_preserves_failure_contract(self):
        for raw, status in (
            ("bad JSON", GenerationStatus.PARSE_ERROR),
            ('{"answer":" "}', GenerationStatus.EMPTY_ANSWER),
        ):
            with self.subTest(status=status):
                result = generate_from_documents(
                    "질문", ["문서"], Mock(return_value=ModelResponse(raw))
                )
                self.assertEqual(result, GenerationResult(status, raw, None))
        self.assertEqual(
            generate_from_documents("질문", ["문서"], Mock(side_effect=TimeoutError)),
            GenerationResult(GenerationStatus.TIMEOUT, None, None),
        )
        error = RuntimeError("provider failed")
        with self.assertRaises(RuntimeError) as caught:
            generate_from_documents("질문", ["문서"], Mock(side_effect=error))
        self.assertIs(caught.exception, error)

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
                model_call = Mock(return_value=ModelResponse(raw_text))
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

        def fake_model(received: GenerationPrompt) -> ModelResponse:
            self.assertIs(received, prompt)
            self.assertIn("사내비", received.system)
            self.assertIn("연차 신청은?", received.user)
            self.assertIn("인사 시스템에서 신청합니다.", received.user)
            return ModelResponse('{"answer": " 인사 시스템에서 신청하세요. "}')

        result = generate(prompt, fake_model)
        self.assertEqual(result.status, GenerationStatus.COMPLETED)
        self.assertEqual(result.answer, "인사 시스템에서 신청하세요.")
