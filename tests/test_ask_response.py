import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.answering.output import (
    LLM_RESPONSE_ERROR,
    LLMResponseError,
    extract_answer_text,
)
from app.classification.predictor import ClassificationUnavailable
from app.dependencies import get_classifier
from app.documents.context import DocumentContextSnapshot
from app.fastapi_main import app

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
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(
            patch.dict(
                os.environ,
                {"SANAEBI_DOCUMENT_DB": str(Path(directory) / "documents.db")},
            )
        )
        classifier = Mock()
        classifier.predict.return_value = "SEARCH_KNOWLEDGE"
        self.classify = classifier.predict
        app.dependency_overrides[get_classifier] = lambda: classifier
        self.addCleanup(app.dependency_overrides.clear)
        self.generate = self.enterContext(patch("app.answering.adapter.execute"))
        self.client = self.enterContext(TestClient(app))
        self.snapshot = DocumentContextSnapshot((Mock(),))
        self.reader = self.enterContext(
            patch.object(
                app.state.document_provider, "snapshot", return_value=self.snapshot
            )
        )

    def test_provider_variable_selects_only_that_models_answer(self):
        self.generate.return_value = {
            name: {
                "success": True,
                "output": {
                    "ok": True,
                    "text": f"{name} 답변",
                    "reason": "SEARCH_KNOWLEDGE",
                },
            }
            for name in ("ollama", "openai")
        }
        for provider in ("ollama", "openai"):
            with (
                self.subTest(provider=provider),
                patch.object(app.state, "answer_provider", provider),
            ):
                response = self.client.post("/ask", json={"question": "질문"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {"ok": True, "text": f"{provider} 답변", "reason": ""},
                )
                self.assertEqual(self.generate.call_args.kwargs["provider"], provider)
                self.assertIs(
                    self.generate.call_args.kwargs["document_snapshot"], self.snapshot
                )

    def test_returns_text_from_json_inside_langchain_output(self):
        self.generate.return_value = {
            "ollama": {
                "success": True,
                "output": {
                    "ok": True,
                    "text": '{"text": "답변 본문", "reason": "근거 설명"}',
                    "reason": "SEARCH_KNOWLEDGE",
                },
            }
        }
        response = self.client.post("/ask", json={"question": "질문"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "답변 본문", "reason": ""}
        )

    def test_failed_model_call_returns_502(self):
        self.generate.return_value = {
            "ollama": {
                "success": False,
                "output": None,
                "error": "가상 호출 오류",
            }
        }
        response = self.client.post("/ask", json={"question": "질문"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), FAILURE_BODY)

    def test_unusable_llm_result_returns_502(self):
        for output in ({"text": ""}, {"text": "{깨진 JSON"}):
            self.generate.return_value = {"ollama": {"success": True, "output": output}}
            response = self.client.post("/ask", json={"question": "질문"})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json(), FAILURE_BODY)

    def test_missing_classifier_stops_before_langchain(self):
        self.classify.side_effect = ClassificationUnavailable
        response = self.client.post("/ask", json={"question": "질문"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"ok": False, "text": "", "reason": "분류 모델을 사용할 수 없습니다."},
        )
        self.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
