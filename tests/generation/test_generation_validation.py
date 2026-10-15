import json
import unittest

from generation.types import GenerationResult, GenerationStatus
from generation.validation import parse_generation


class GenerationValidationTests(unittest.TestCase):
    def test_markdown_paragraphs_and_lists_survive_json_parsing(self):
        answer = "안내입니다.\n\n- 첫 항목\n- 둘째 항목\n\n조건은 유지합니다."
        raw = json.dumps({"answer": answer}, ensure_ascii=False)
        result = parse_generation(raw)
        self.assertEqual(result.status, GenerationStatus.COMPLETED)
        self.assertEqual(result.answer, answer)
        self.assertEqual(result.raw_text, raw)

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

    def test_extra_json_keys_are_parse_errors(self):
        raw_text = '{"answer":"안내", "extra":true}'
        self.assertEqual(
            parse_generation(raw_text),
            GenerationResult(GenerationStatus.PARSE_ERROR, raw_text, None),
        )

    def test_insufficient_evidence_message_is_a_completed_answer(self):
        raw_text = '{"answer": "문서에서 기준을 확인할 수 없습니다."}'
        self.assertEqual(parse_generation(raw_text).status, GenerationStatus.COMPLETED)
