import unittest
from unittest.mock import Mock

from app.services.document_context import DocumentContextSnapshot
from app.services.question_service import QuestionResult, handle_question


class QuestionServiceTests(unittest.TestCase):
    def setUp(self):
        self.question = "연차 신청 방법을 알려주세요."
        self.documents = DocumentContextSnapshot((Mock(),))
        self.classify = Mock(return_value="SEARCH_KNOWLEDGE")
        self.read_documents = Mock(return_value=self.documents)
        self.answer = Mock(return_value="사내 시스템에서 신청하세요.")

    def handle(self):
        return handle_question(
            self.question,
            classify=self.classify,
            read_documents=self.read_documents,
            answer=self.answer,
        )

    def test_clarify_requests_more_information_without_documents_or_llm(self):
        self.classify.return_value = "CLARIFY"

        result = self.handle()

        self.assertIsInstance(result, QuestionResult)
        self.assertIn("알려주세요", result.text)
        self.classify.assert_called_once_with(self.question)
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_unsupported_explains_scope_without_documents_or_llm(self):
        self.classify.return_value = "UNSUPPORTED"

        result = self.handle()

        self.assertIn("지원 범위", result.text)
        self.classify.assert_called_once_with(self.question)
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_search_passes_question_and_documents_to_answerer(self):
        result = self.handle()

        self.assertEqual(result, QuestionResult(text="사내 시스템에서 신청하세요."))
        self.classify.assert_called_once_with(self.question)
        self.read_documents.assert_called_once_with()
        self.answer.assert_called_once_with(self.question, self.documents)

    def test_missing_documents_returns_notice_without_llm(self):
        self.read_documents.return_value = DocumentContextSnapshot(())

        result = self.handle()

        self.assertIn("문서가 없어", result.text)
        self.classify.assert_called_once_with(self.question)
        self.read_documents.assert_called_once_with()
        self.answer.assert_not_called()

    def test_unknown_label_fails_before_reading_documents(self):
        self.classify.return_value = "UNKNOWN"

        with self.assertRaises(ValueError):
            self.handle()

        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_classifier_failure_stops_processing(self):
        error = RuntimeError("분류기 실행 실패")
        self.classify.side_effect = error

        with self.assertRaises(RuntimeError) as raised:
            self.handle()

        self.assertIs(raised.exception, error)
        self.read_documents.assert_not_called()
        self.answer.assert_not_called()

    def test_document_failure_is_not_reported_as_missing_documents(self):
        error = OSError("문서 읽기 실패")
        self.read_documents.side_effect = error

        with self.assertRaises(OSError) as raised:
            self.handle()

        self.assertIs(raised.exception, error)
        self.answer.assert_not_called()

    def test_answer_failure_is_not_returned_as_success(self):
        error = RuntimeError("답변 생성 실패")
        self.answer.side_effect = error

        with self.assertRaises(RuntimeError) as raised:
            self.handle()

        self.assertIs(raised.exception, error)
        self.answer.assert_called_once_with(self.question, self.documents)


if __name__ == "__main__":
    unittest.main()
