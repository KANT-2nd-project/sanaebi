"""실제 데이터를 사용하지 않고 현재 API 계약을 검증한다."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import fastapi_main
from app.routers import assistant, classification, documents


class ApiTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.document_file = Path(directory) / "documents.jsonl"
        self.enterContext(patch.object(documents, "DOCUMENT_FILE", self.document_file))
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
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

    def test_home(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "FastAPI 서버가 실행 중입니다."})

    def test_ask_returns_trimmed_question(self):
        response = self.client.post("/ask", json={"question": " 휴가 안내\n "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "휴가 안내", "reason": ""}
        )
        self.assertFalse(self.document_file.exists())

    def test_ask_ignores_extra_fields(self):
        response = self.client.post("/ask", json={"question": "안내", "unused": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "text": "안내", "reason": ""})

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

    def test_documents_append_and_preserve_existing_rows(self):
        original = '{"doc": "기존 가상 문서"}\n'
        self.document_file.write_text(original, encoding="utf-8")
        response = self.client.post(
            "/regist-docs", json={"doc": " 가상 안내\n둘째 줄 "}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "text": "문서가 등록되었습니다.", "reason": ""},
        )
        content = self.document_file.read_text(encoding="utf-8")
        self.assertTrue(content.startswith(original))
        self.assertEqual(
            [json.loads(line) for line in content.splitlines()],
            [{"doc": "기존 가상 문서"}, {"doc": "가상 안내\n둘째 줄"}],
        )
        self.assert_validation_error(
            self.client.post("/regist-docs", json={"doc": " "})
        )
        self.assertEqual(self.document_file.read_text(encoding="utf-8"), content)

    def test_document_write_failure_is_not_reported_as_success(self):
        missing_parent = self.document_file.parent / "missing" / "documents.jsonl"
        with patch.object(documents, "DOCUMENT_FILE", missing_parent):
            response = self.client.post("/regist-docs", json={"doc": "가상 문서"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.text, "Internal Server Error")
        self.assertFalse(missing_parent.exists())

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
                "/ask/langchain",
            },
        )
        for route in ("/ask", "/regist-docs"):
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

    def test_assistant_preserves_langchain_input_and_output(self):
        payload = {
            "response": {"ok": True, "text": "출장비 절차 알려줘", "reason": ""},
            "classification_label": "SEARCH_KNOWLEDGE",
        }
        result = {
            "ollama": {"output": {"ok": True, "text": "가상 답변", "reason": ""}},
            "openai": {"output": None, "success": False, "error": "가상 호출 오류"},
        }
        with patch.object(
            assistant, "generate_assistant_response", return_value=result
        ) as generate:
            response = self.client.post("/assistant", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), result)
            generate.assert_called_once_with(
                response=payload["response"], category=payload["classification_label"]
            )

    def test_assistant_rejects_invalid_category_without_llm_call(self):
        with patch.object(assistant, "generate_assistant_response") as generate:
            self.assert_validation_error(
                self.client.post(
                    "/assistant",
                    json={
                        "response": {"ok": True, "text": "질문", "reason": ""},
                        "classification_label": "HR",
                    },
                )
            )
            generate.assert_not_called()

    def test_question_is_classified_then_forwarded_to_langchain(self):
        for label in ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"):
            with self.subTest(label=label):
                events = []

                def classify(question, events=events, label=label):
                    events.append(("classify", question))
                    return label

                def generate(response, category, events=events):
                    events.append(("generate", response, category))
                    return {"ollama": {"output": {"text": "가상 답변"}}}

                with (
                    patch.object(assistant, "classify_question", side_effect=classify),
                    patch.object(
                        assistant, "generate_assistant_response", side_effect=generate
                    ),
                ):
                    response = self.client.post(
                        "/ask/langchain", json={"question": "  출장비 안내  "}
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(), {"ollama": {"output": {"text": "가상 답변"}}}
                )
                self.assertEqual(
                    events,
                    [
                        ("classify", "출장비 안내"),
                        (
                            "generate",
                            {"ok": True, "text": "출장비 안내", "reason": ""},
                            label,
                        ),
                    ],
                )

    def test_automatic_answer_stops_before_llm_if_model_is_missing(self):
        with (
            patch.object(assistant, "classify_question", side_effect=FileNotFoundError),
            patch.object(assistant, "generate_assistant_response") as generate,
        ):
            response = self.client.post("/ask/langchain", json={"question": "질문"})
            generate.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"ok": False, "text": "", "reason": "분류 모델이 없습니다."},
        )

    def test_automatic_answer_rejects_blank_before_model_calls(self):
        with (
            patch.object(assistant, "classify_question") as classify,
            patch.object(assistant, "generate_assistant_response") as generate,
        ):
            self.assert_validation_error(
                self.client.post("/ask/langchain", json={"question": " \n "})
            )
            classify.assert_not_called()
            generate.assert_not_called()

    def test_classification_returns_category_without_answer_generation(self):
        for label in ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"):
            with self.subTest(label=label):
                with patch.object(
                    classification, "classify_question", return_value=label
                ) as predict:
                    response = self.client.post(
                        "/classify/koelectra-base", json={"question": "  휴가 안내  "}
                    )
                predict.assert_called_once_with("휴가 안내")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"category": label})

    def test_invalid_classification_input_does_not_call_model(self):
        with patch.object(classification, "classify_question") as predict:
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
            classification, "classify_question", side_effect=FileNotFoundError
        ):
            response = self.client.post(
                "/classify/koelectra-base", json={"question": "휴가 안내"}
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"ok": False, "text": "", "reason": "분류 모델이 없습니다."},
        )


if __name__ == "__main__":
    unittest.main()
