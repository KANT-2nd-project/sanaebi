import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.answer_text import LLM_RESPONSE_ERROR, LLMResponseError, extract_answer_text
from app.fastapi_main import app
from app.routers import questions

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


class AskEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_returns_stripped_question_until_chain_is_connected(self):
        response = self.client.post("/ask", json={"question": "  휴가 신청  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "휴가 신청", "reason": ""}
        )

    def test_returns_text_field_of_llm_result(self):
        result = {"text": "답변 본문", "model": "m", "usage": {}, "error": None}
        with patch.object(questions, "generate_answer", return_value=result):
            response = self.client.post("/ask", json={"question": "질문"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "답변 본문", "reason": ""}
        )

    def test_unusable_llm_result_returns_502(self):
        with patch.object(questions, "generate_answer", return_value="{깨진 JSON"):
            response = self.client.post("/ask", json={"question": "질문"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), FAILURE_BODY)


if __name__ == "__main__":
    unittest.main()
