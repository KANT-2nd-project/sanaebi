import unittest

from app.answering.output import (
    LLM_RESPONSE_ERROR,
    LLMResponseError,
    extract_answer_text,
)

FAILURE_BODY = {"ok": False, "text": "", "reason": LLM_RESPONSE_ERROR}


class ExtractAnswerTextTests(unittest.TestCase):
    def test_returns_only_text_from_result(self):
        result = {"text": "  연차는 그룹웨어에서 신청합니다.  ", "model": "m"}
        self.assertEqual(extract_answer_text(result), "연차는 그룹웨어에서 신청합니다.")

    def test_parses_json_string(self):
        self.assertEqual(extract_answer_text('{"text": "답변"}'), "답변")

    def test_rejects_unusable_results(self):
        cases = [
            "답변",
            '{"text": "답변"',
            "[]",
            {},
            {"text": None},
            {"text": "   "},
            {"text": "잘린 답변", "error": "TruncatedOutput"},
        ]
        for result in cases:
            with self.subTest(result=result), self.assertRaises(LLMResponseError):
                extract_answer_text(result)
