"""RAG belongs after one snapshot and before generation, for both routing modes."""

import unittest
from unittest.mock import Mock

from app.classification.errors import ClassificationUnavailable
from app.documents.context import DocumentContextSnapshot
from app.questions.service import handle_classified_question, handle_question


class RagQuestionServiceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = DocumentContextSnapshot((Mock(),))
        self.read = Mock(return_value=self.snapshot)
        self.context = Mock(evidence=(Mock(),))
        self.retrieve = Mock(return_value=self.context)
        self.answer = Mock(return_value="선택 근거 답변")

    def call(self, label="SEARCH_KNOWLEDGE", mode="shadow", classifier=None):
        return handle_question(
            "정책 질문",
            classify=classifier or Mock(return_value=label),
            read_documents=self.read,
            answer=self.answer,
            retrieve=self.retrieve,
            routing_mode=mode,
        )

    def test_selected_context_not_full_snapshot_reaches_answer(self):
        self.assertEqual(self.call().text, "선택 근거 답변")
        self.read.assert_called_once_with()
        self.retrieve.assert_called_once_with("정책 질문", self.snapshot)
        self.answer.assert_called_once_with("정책 질문", self.context)

    def test_shadow_all_labels_and_known_failure_retrieve(self):
        for label in ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"):
            with self.subTest(label=label):
                self.retrieve.reset_mock()
                self.call(label)
                self.retrieve.assert_called_once()
        self.retrieve.reset_mock()
        self.call(classifier=Mock(side_effect=ClassificationUnavailable("secret")))
        self.retrieve.assert_called_once()

    def test_gate_nonsearch_and_empty_snapshot_never_retrieve(self):
        for label in ("CLARIFY", "UNSUPPORTED"):
            self.call(label, "gate")
        self.read.assert_not_called()
        self.retrieve.assert_not_called()
        self.read.return_value = DocumentContextSnapshot(())
        self.call()
        self.retrieve.assert_not_called()
        self.answer.assert_not_called()

    def test_retrieval_failure_never_generates(self):
        self.retrieve.side_effect = RuntimeError("retrieval unavailable")
        with self.assertRaises(RuntimeError):
            self.call()
        self.answer.assert_not_called()

    def test_assistant_uses_same_snapshot_and_retrieval(self):
        handle_classified_question(
            "정책 질문",
            "CLARIFY",
            routing_mode="shadow",
            read_documents=self.read,
            answer=self.answer,
            retrieve=self.retrieve,
        )
        self.retrieve.assert_called_once_with("정책 질문", self.snapshot)
        self.answer.assert_called_once_with("정책 질문", self.context)
