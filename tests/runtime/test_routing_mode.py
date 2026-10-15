import json
import os
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
from app.documents.context import DocumentContextSnapshot
from app.questions.service import handle_question
from app.settings import get_routing_mode


class RoutingModeSettingsTests(unittest.TestCase):
    def test_routing_mode_defaults_to_advisory(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_routing_mode(), "advisory")

    def test_gate_remains_an_explicit_rollback(self):
        with patch.dict(os.environ, {"SANAEBI_ROUTING_MODE": "gate"}):
            self.assertEqual(get_routing_mode(), "gate")

    def test_routing_mode_accepts_shadow(self):
        with patch.dict(os.environ, {"SANAEBI_ROUTING_MODE": "shadow"}):
            self.assertEqual(get_routing_mode(), "shadow")

    def test_routing_mode_rejects_unknown_values(self):
        with (
            patch.dict(os.environ, {"SANAEBI_ROUTING_MODE": "observe"}),
            self.assertRaises(ValueError),
        ):
            get_routing_mode()


class RoutingModeServiceTests(unittest.TestCase):
    def setUp(self):
        self.documents = DocumentContextSnapshot((Mock(),))
        self.read_documents = Mock(return_value=self.documents)
        self.answer = Mock(return_value="문서 기반 답변")
        self.classify = Mock(return_value="UNSUPPORTED")

    def test_shadow_continues_for_non_search_labels_without_passing_label(self):
        for label in ("CLARIFY", "UNSUPPORTED"):
            with self.subTest(label=label):
                self.classify.return_value = label
                result = handle_question(
                    "회사 안내를 알려줘",
                    classify=self.classify,
                    read_documents=self.read_documents,
                    answer=self.answer,
                    routing_mode="shadow",
                )

                self.assertEqual(result.text, "문서 기반 답변")
                self.read_documents.assert_called_once_with()
                self.answer.assert_called_once_with(
                    "회사 안내를 알려줘", self.documents
                )
                self.read_documents.reset_mock()
                self.answer.reset_mock()

    def test_shadow_continues_after_known_classifier_errors(self):
        for error in (ClassificationUnavailable, ClassificationInferenceError):
            with self.subTest(error=error.__name__):
                self.classify.side_effect = error("private classifier detail")
                result = handle_question(
                    "회사 안내를 알려줘",
                    classify=self.classify,
                    read_documents=self.read_documents,
                    answer=self.answer,
                    routing_mode="shadow",
                )

                self.assertEqual(result.text, "문서 기반 답변")
                self.read_documents.assert_called_once_with()
                self.answer.assert_called_once_with(
                    "회사 안내를 알려줘", self.documents
                )
                self.read_documents.reset_mock()
                self.answer.reset_mock()

    def test_gate_reraises_known_classifier_errors_without_reading_documents(self):
        self.classify.side_effect = ClassificationUnavailable("private detail")
        with self.assertRaises(ClassificationUnavailable):
            handle_question(
                "회사 안내를 알려줘",
                classify=self.classify,
                read_documents=self.read_documents,
                answer=self.answer,
                routing_mode="gate",
            )
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_shadow_does_not_hide_unexpected_classifier_errors(self):
        error = RuntimeError("programming error")
        self.classify.side_effect = error
        with self.assertRaises(RuntimeError) as raised:
            handle_question(
                "회사 안내를 알려줘",
                classify=self.classify,
                read_documents=self.read_documents,
                answer=self.answer,
                routing_mode="shadow",
            )
        self.assertIs(raised.exception, error)
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_invalid_internal_label_is_rejected_in_shadow(self):
        self.classify.return_value = "INVALID"
        with self.assertRaises(ValueError):
            handle_question(
                "회사 안내를 알려줘",
                classify=self.classify,
                read_documents=self.read_documents,
                answer=self.answer,
                routing_mode="shadow",
            )
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()


class RoutingModeApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        env = {
            "SANAEBI_DOCUMENT_DB": str(Path(self.directory) / "managed.sqlite3"),
            "SANAEBI_RETRIEVAL_MODE": "full",
            "SANAEBI_ROUTING_MODE": "shadow",
        }
        self.enterContext(patch.dict(os.environ, env))
        self.classifier = Mock()
        self.classifier.predict.return_value = "UNSUPPORTED"
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: self.classifier
        self.addCleanup(fastapi_main.app.dependency_overrides.clear)
        self.answer = self.enterContext(
            patch(
                "app.answering.adapter.GenerationAnswerer.answer",
                return_value="문서 기반 답변",
            )
        )
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
        )
        self.snapshot = DocumentContextSnapshot((Mock(),))
        self.read_documents = self.enterContext(
            patch.object(
                fastapi_main.app.state.document_provider,
                "snapshot",
                return_value=self.snapshot,
            )
        )

    def test_lifespan_loads_shadow_and_ask_generates_for_unsupported(self):
        self.assertEqual(fastapi_main.app.state.routing_mode, "shadow")
        response = self.client.post("/ask", json={"question": "김치찌개 만드는 법"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "문서 기반 답변")
        self.classifier.predict.assert_called_once_with("김치찌개 만드는 법")
        self.read_documents.assert_called_once_with()
        self.answer.assert_called_once_with("김치찌개 만드는 법", self.snapshot)

    def test_assistant_shadow_uses_client_label_without_reclassification(self):
        trace_directory = Path(self.directory) / "trace-assistant"
        with patch.dict(os.environ, {"TRACE_DIR": str(trace_directory)}):
            response = self.client.post(
                "/assistant",
                json={
                    "response": {"ok": True, "text": "질문", "reason": ""},
                    "classification_label": "CLARIFY",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "문서 기반 답변")
        self.classifier.predict.assert_not_called()
        self.answer.assert_called_once_with("질문", self.snapshot)
        trace_path = next(trace_directory.glob("*.jsonl"))
        [record] = [
            json.loads(line) for line in trace_path.read_text("utf-8").splitlines()
        ]
        classification = record["steps"][0]
        self.assertEqual(classification["label_source"], "client")
        self.assertEqual(classification["classification_status"], "provided")
        self.assertEqual(classification["output"], "CLARIFY")

    def test_invalid_question_is_rejected_before_classification_in_shadow(self):
        response = self.client.post("/ask", json={"question": "  "})
        self.assertEqual(response.status_code, 422)
        self.classifier.predict.assert_not_called()
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_assistant_failed_upstream_response_stays_unprocessed_in_shadow(self):
        trace_directory = Path(self.directory) / "trace-upstream-failure"
        with patch.dict(os.environ, {"TRACE_DIR": str(trace_directory)}):
            response = self.client.post(
                "/assistant",
                json={
                    "response": {"ok": False, "text": "", "reason": "private"},
                    "classification_label": "SEARCH_KNOWLEDGE",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.classifier.predict.assert_not_called()
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()
        trace_path = next(trace_directory.glob("*.jsonl"))
        [record] = [
            json.loads(line) for line in trace_path.read_text("utf-8").splitlines()
        ]
        classification = record["steps"][0]
        self.assertEqual(classification["status"], "skipped")
        self.assertEqual(classification["routing_mode"], "shadow")
        self.assertEqual(classification["label_source"], "client")
        self.assertEqual(classification["classification_status"], "not_run")
        self.assertEqual(classification["processing_path"], "upstream_failure")
        self.assertFalse(classification["generation_attempted"])

    def test_shadow_classifier_unavailable_continues_safely(self):
        self.classifier.predict.side_effect = ClassificationUnavailable(
            "private model path"
        )
        response = self.client.post("/ask", json={"question": "회사 안내"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "문서 기반 답변")
        self.assertNotIn("private", response.text)
        self.answer.assert_called_once_with("회사 안내", self.snapshot)

    def test_shadow_unexpected_classifier_error_remains_500(self):
        self.classifier.predict.side_effect = RuntimeError("private code detail")
        response = self.client.post("/ask", json={"question": "회사 안내"})
        self.assertEqual(response.status_code, 500)
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_shadow_invalid_classifier_label_remains_500(self):
        self.classifier.predict.return_value = "UNKNOWN"
        response = self.client.post("/ask", json={"question": "회사 안내"})
        self.assertEqual(response.status_code, 500)
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_invalid_routing_mode_fails_during_startup(self):
        self.client.close()
        with (
            patch.dict(os.environ, {"SANAEBI_ROUTING_MODE": "invalid"}),
            self.assertRaises(ValueError),
            TestClient(fastapi_main.app),
        ):
            pass

    def test_trace_contains_safe_routing_metadata_and_trace_header(self):
        trace_directory = Path(self.directory) / "trace"
        with patch.dict(os.environ, {"TRACE_DIR": str(trace_directory)}):
            response = self.client.post("/ask", json={"question": "회사 안내"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("x-trace-id", response.headers)
        trace_path = next(trace_directory.glob("*.jsonl"))
        [record] = [
            json.loads(line) for line in trace_path.read_text("utf-8").splitlines()
        ]
        classification = record["steps"][0]
        self.assertEqual(classification["routing_mode"], "shadow")
        self.assertEqual(classification["label_source"], "model")
        self.assertEqual(classification["classification_status"], "ok")
        self.assertGreaterEqual(classification["classification_elapsed_seconds"], 0)
        self.assertEqual(classification["processing_path"], "generation")
        self.assertTrue(classification["generation_attempted"])
        self.assertNotIn("prompt", classification)
        self.assertNotIn("private", json.dumps(classification))

    def test_trace_marks_known_classifier_failure_when_shadow_continues(self):
        self.classifier.predict.side_effect = ClassificationInferenceError(
            "private classifier details"
        )
        trace_directory = Path(self.directory) / "trace-failure"
        with patch.dict(os.environ, {"TRACE_DIR": str(trace_directory)}):
            response = self.client.post("/ask", json={"question": "회사 안내"})

        self.assertEqual(response.status_code, 200)
        trace_path = next(trace_directory.glob("*.jsonl"))
        [record] = [
            json.loads(line) for line in trace_path.read_text("utf-8").splitlines()
        ]
        classification = record["steps"][0]
        self.assertEqual(classification["status"], "error")
        self.assertEqual(classification["classification_status"], "inference_error")
        self.assertEqual(classification["processing_path"], "generation")
        self.assertTrue(classification["generation_attempted"])
        self.assertNotIn("private", json.dumps(classification))


if __name__ == "__main__":
    unittest.main()
