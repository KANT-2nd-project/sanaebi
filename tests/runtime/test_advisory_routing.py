"""Only successful server predictions may influence the generation prompt."""

import unittest
from unittest.mock import Mock

from app.documents.context import DocumentContextSnapshot
from app.questions.service import handle_question
from generation.advisory import ClassificationContext


class AdvisoryRoutingTests(unittest.TestCase):
    def test_server_labels_reach_answerer_with_identical_snapshot(self):
        snapshot = DocumentContextSnapshot((Mock(),))
        for label in ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"):
            with self.subTest(label=label):
                reader = Mock(return_value=snapshot)
                answer = Mock(return_value="답변")
                result = handle_question(
                    "질문",
                    classify=Mock(return_value=label),
                    read_documents=reader,
                    answer=answer,
                    routing_mode="advisory",
                )
                self.assertEqual(result.text, "답변")
                reader.assert_called_once_with()
                answer.assert_called_once_with(
                    "질문",
                    snapshot,
                    classification_context=ClassificationContext(label),
                )

    def test_known_failures_and_client_labels_preserve_two_argument_fallback(self):
        from app.classification.errors import (
            ClassificationInferenceError,
            ClassificationUnavailable,
        )
        from app.questions.service import handle_classified_question

        snapshot = DocumentContextSnapshot((Mock(),))
        for error in (ClassificationUnavailable, ClassificationInferenceError):
            answer = Mock(return_value="답변")
            handle_question(
                "질문",
                classify=Mock(side_effect=error("private")),
                read_documents=lambda: snapshot,
                answer=answer,
                routing_mode="advisory",
            )
            answer.assert_called_once_with("질문", snapshot)
        for label in ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"):
            answer = Mock(return_value="답변")
            handle_classified_question(
                "질문",
                label,
                read_documents=lambda: snapshot,
                answer=answer,
                routing_mode="advisory",
            )
            answer.assert_called_once_with("질문", snapshot)

    def test_unexpected_errors_and_invalid_labels_never_read_documents(self):
        for classifier, error in (
            (Mock(side_effect=RuntimeError("bug")), RuntimeError),
            (Mock(return_value="unknown"), ValueError),
        ):
            reader = Mock()
            with self.assertRaises(error):
                handle_question(
                    "질문",
                    classify=classifier,
                    read_documents=reader,
                    answer=Mock(),
                    routing_mode="advisory",
                )
            reader.assert_not_called()

    def test_retrieval_receives_no_label_and_empty_evidence_never_generates(self):
        snapshot = DocumentContextSnapshot((Mock(),))
        selected = Mock(evidence=(Mock(),))
        retrieve = Mock(return_value=selected)
        answer = Mock(return_value="답변")
        args = {
            "classify": lambda _: "UNSUPPORTED",
            "read_documents": lambda: snapshot,
            "answer": answer,
            "retrieve": retrieve,
            "routing_mode": "advisory",
        }
        handle_question("질문", **args)
        retrieve.assert_called_once_with("질문", snapshot)
        answer.assert_called_once_with(
            "질문",
            selected,
            classification_context=ClassificationContext("UNSUPPORTED"),
        )
        answer.reset_mock()
        selected.evidence = ()
        self.assertIn("근거를 찾지 못", handle_question("질문", **args).text)
        answer.assert_not_called()
