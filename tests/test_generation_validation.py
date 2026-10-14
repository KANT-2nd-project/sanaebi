import unittest

from generation.types import GenerationResult, GenerationStatus
from generation.validation import parse_generation


class GenerationValidationTests(unittest.TestCase):
    def test_invalid_json_or_answer_structure(self):
        for raw_text in (
            "안녕하세요",
            "",
            "[]",
            "null",
            "123",
            '"문자열"',
            "{}",
            '{"answer": null}',
            '{"answer": 123}',
            '{"answer": true}',
            '{"answer": []}',
            '{"answer": {}}',
        ):
            with self.subTest(raw_text=raw_text):
                self.assertEqual(
                    parse_generation(raw_text),
                    GenerationResult(GenerationStatus.PARSE_ERROR, raw_text, None),
                )

    def test_empty_answers(self):
        for raw_text in ('{"answer": ""}', '{"answer": " \\n\\t "}'):
            with self.subTest(raw_text=raw_text):
                self.assertEqual(
                    parse_generation(raw_text),
                    GenerationResult(GenerationStatus.EMPTY_ANSWER, raw_text, None),
                )

    def test_completed_preserves_raw_text_and_strips_answer(self):
        raw_text = '{"answer": " 안내입니다. "}'
        self.assertEqual(
            parse_generation(raw_text),
            GenerationResult(GenerationStatus.COMPLETED, raw_text, "안내입니다."),
        )

    def test_insufficient_evidence_message_is_a_completed_answer(self):
        raw_text = '{"answer": "문서에서 기준을 확인할 수 없습니다."}'
        self.assertEqual(parse_generation(raw_text).status, GenerationStatus.COMPLETED)
