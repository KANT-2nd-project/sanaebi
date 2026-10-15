"""실제 데이터를 사용하지 않고 현재 API 계약을 검증한다."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import fastapi_main
from app.classification.predictor import (
    ClassificationInferenceError,
    ClassificationUnavailable,
)
from app.dependencies import get_classifier
from app.documents.context import DocumentContextSnapshot, DocumentStorageError


class ApiTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(Path(directory) / "managed.sqlite3"),
                    "SANAEBI_ROUTING_MODE": "gate",
                },
            )
        )
        self.document_file = Path(directory) / "documents.jsonl"
        self.classifier = Mock()
        self.classifier.predict.return_value = "SEARCH_KNOWLEDGE"
        self.question_classifier = self.classifier.predict
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: self.classifier
        self.addCleanup(fastapi_main.app.dependency_overrides.clear)
        self.question_generator = self.enterContext(
            patch(
                "app.answering.adapter.GenerationAnswerer.answer",
                return_value="가상 답변",
            )
        )
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
        )

        self.snapshot = DocumentContextSnapshot((Mock(),))
        self.reader = self.enterContext(
            patch.object(
                fastapi_main.app.state.document_provider,
                "snapshot",
                return_value=self.snapshot,
            )
        )

    def assert_validation_error(self, response):
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {
                "ok": False,
                "text": "",
                "reason": "요청 형식이 올바르지 않습니다. 필수 항목과 입력값을 확인해주세요.",
            },
        )

    def test_non_search_does_not_call_documents_or_generator(self):
        for label in ("CLARIFY", "UNSUPPORTED"):
            self.question_classifier.return_value = label
            with patch.object(
                fastapi_main.app.state.document_provider, "snapshot"
            ) as read:
                response = self.client.post("/ask", json={"question": "질문"})
                self.assertEqual(response.status_code, 200)
                read.assert_not_called()
                self.question_generator.assert_not_called()

    def test_both_routes_use_same_classifier_dependency(self):
        self.question_classifier.return_value = "CLARIFY"
        for route in ("/ask", "/classify/koelectra-base"):
            self.assertEqual(
                self.client.post(route, json={"question": "질문"}).status_code, 200
            )
        self.assertEqual(self.question_classifier.call_count, 2)

    def test_classifier_errors_are_safe_503_in_both_routes(self):
        for error in (ClassificationUnavailable, ClassificationInferenceError):
            self.question_classifier.side_effect = error("private path")
            for route in ("/ask", "/classify/koelectra-base"):
                response = self.client.post(route, json={"question": "질문"})
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private", response.text)
        self.reader.assert_not_called()
        self.question_generator.assert_not_called()

    def test_empty_documents_skip_generation(self):
        self.reader.return_value = DocumentContextSnapshot(())
        response = self.client.post("/ask", json={"question": "질문"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("문서가 없어", response.json()["text"])
        self.question_generator.assert_not_called()

    def test_document_failure_is_503_not_empty_result(self):
        self.reader.side_effect = DocumentStorageError("private path")
        response = self.client.post("/ask", json={"question": "질문"})
        self.assertEqual(response.status_code, 503)
        self.question_generator.assert_not_called()

    def test_home(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "FastAPI 서버가 실행 중입니다."})

    def test_ask_forwards_trimmed_question_and_returns_generated_answer(self):
        response = self.client.post("/ask", json={"question": " 휴가 안내\n "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "가상 답변", "reason": ""}
        )
        self.question_classifier.assert_called_once_with("휴가 안내")
        self.question_generator.assert_called_once_with("휴가 안내", self.snapshot)
        self.reader.assert_called_once_with()
        self.assertFalse(self.document_file.exists())

    def test_ask_ignores_extra_fields(self):
        response = self.client.post("/ask", json={"question": "안내", "unused": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "가상 답변", "reason": ""}
        )

    def test_invalid_inputs_do_not_write_documents(self):
        for route, field in (("/ask", "question"), ("/regist-docs", "doc")):
            for payload in ({}, {field: ""}, {field: " \n\t "}, {field: 7}):
                with self.subTest(route=route, payload=payload):
                    self.assert_validation_error(self.client.post(route, json=payload))
                    self.assertFalse(self.document_file.exists())

    def test_malformed_json_uses_validation_envelope(self):
        for route in ("/ask", "/regist-docs"):
            with self.subTest(route=route):
                response = self.client.post(
                    route, content="{", headers={"Content-Type": "application/json"}
                )
                self.assert_validation_error(response)
        self.assertFalse(self.document_file.exists())

    def test_legacy_registration_creates_sqlite_draft_and_preserves_jsonl(self):
        original = '{"doc": "기존 가상 문서"}\n'
        self.document_file.write_text(original)
        response = self.client.post(
            "/regist-docs", json={"doc": " 가상 안내\n둘째 줄 "}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "text": "문서가 등록되었습니다.", "reason": ""},
        )
        repo = fastapi_main.app.state.document_repository
        item = repo.list()["items"][0]
        self.assertEqual(item["status"], "draft")
        self.assertEqual(repo.get(item["id"])["draft"]["body"], "가상 안내\n둘째 줄")
        self.assertEqual(self.document_file.read_text(), original)
        duplicate = self.client.post(
            "/regist-docs", json={"doc": " 가상 안내\n둘째 줄 "}
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.headers["cache-control"], "no-store")
        self.assertEqual(repo.list()["total"], 1)
        self.assertEqual(
            self.client.post("/regist-docs", json={"doc": "a" * 50001}).status_code, 422
        )
        self.assertEqual(
            self.client.post("/regist-docs", content=b" " * 524289).status_code, 413
        )

    def test_document_write_failure_is_not_reported_as_success(self):
        repo = fastapi_main.app.state.document_repository
        with patch.object(
            repo,
            "create_in_transaction",
            side_effect=sqlite3.OperationalError("locked"),
        ):
            response = self.client.post("/regist-docs", json={"doc": "가상 문서"})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])

    def test_routing_errors_keep_http_status(self):
        for path, status, detail in (
            ("/missing", 404, "Not Found"),
            ("/ask", 405, "Method Not Allowed"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), {"detail": detail})

    def test_openapi_contract_and_no_legacy_routes(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertEqual(
            set(schema["paths"]),
            {
                "/",
                "/ask",
                "/regist-docs",
                "/classify/koelectra-base",
                "/assistant",
                "/documents",
                "/documents/capabilities",
                "/documents/{document_id}",
                "/documents/{document_id}/publish",
                "/documents/{document_id}/withdraw",
            },
        )
        for route in ("/ask", "/regist-docs", "/assistant"):
            for status in ("200", "422"):
                with self.subTest(route=route, status=status):
                    model = schema["paths"][route]["post"]["responses"][status][
                        "content"
                    ]["application/json"]["schema"]
                    self.assertEqual(
                        model["$ref"], "#/components/schemas/AnswerResponse"
                    )
        self.assertEqual(
            set(schema["components"]["schemas"]["AnswerResponse"]["properties"]),
            {"ok", "text", "reason"},
        )

    def test_assistant_uses_same_answer_contract_without_reclassification(self):
        payload = {
            "response": {"ok": True, "text": " 출장비 절차 알려줘 ", "reason": ""},
            "classification_label": "SEARCH_KNOWLEDGE",
        }
        response = self.client.post("/assistant", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "가상 답변", "reason": ""}
        )
        self.question_generator.assert_called_once_with(
            "출장비 절차 알려줘", self.snapshot
        )
        self.question_classifier.assert_not_called()
        self.reader.assert_called_once_with()

    def test_assistant_rejects_invalid_category_without_llm_call(self):
        self.assert_validation_error(
            self.client.post(
                "/assistant",
                json={
                    "response": {"ok": True, "text": "질문", "reason": ""},
                    "classification_label": "HR",
                },
            )
        )
        self.question_generator.assert_not_called()

    def test_assistant_failed_input_and_nonsearch_skip_dependencies(self):
        result = self.client.post(
            "/assistant",
            json={
                "response": {"ok": False, "text": "", "reason": "private"},
                "classification_label": "SEARCH_KNOWLEDGE",
            },
        )
        self.assertEqual(
            result.json(),
            {
                "ok": False,
                "text": "",
                "reason": "이전 단계에서 요청을 처리하지 못했습니다.",
            },
        )
        for label in ("CLARIFY", "UNSUPPORTED"):
            response = self.client.post(
                "/assistant",
                json={
                    "response": {"ok": True, "text": "질문", "reason": ""},
                    "classification_label": label,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])
        self.reader.assert_not_called()
        self.question_classifier.assert_not_called()
        self.question_generator.assert_not_called()

    def test_assistant_empty_successful_question_is_422(self):
        self.assert_validation_error(
            self.client.post(
                "/assistant",
                json={
                    "response": {"ok": True, "text": "  ", "reason": ""},
                    "classification_label": "SEARCH_KNOWLEDGE",
                },
            )
        )
        self.reader.assert_not_called()
        self.question_generator.assert_not_called()

    def test_classification_returns_category_without_answer_generation(self):
        for label in ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"):
            with self.subTest(label=label):
                with patch.object(
                    self.classifier, "predict", return_value=label
                ) as predict:
                    response = self.client.post(
                        "/classify/koelectra-base", json={"question": "  휴가 안내  "}
                    )
                predict.assert_called_once_with("휴가 안내")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"category": label})

    def test_invalid_classification_input_does_not_call_model(self):
        with patch.object(self.classifier, "predict") as predict:
            for payload in (
                {},
                {"question": ""},
                {"question": " \n "},
                {"question": 7},
            ):
                with self.subTest(payload=payload):
                    self.assert_validation_error(
                        self.client.post("/classify/koelectra-base", json=payload)
                    )
            predict.assert_not_called()

    def test_missing_classification_model_returns_503(self):
        with patch.object(
            self.classifier, "predict", side_effect=ClassificationUnavailable
        ):
            response = self.client.post(
                "/classify/koelectra-base", json={"question": "휴가 안내"}
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"ok": False, "text": "", "reason": "분류 모델을 사용할 수 없습니다."},
        )


if __name__ == "__main__":
    unittest.main()
