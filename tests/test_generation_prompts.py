import unittest

from generation.prompts import build_prompt
from generation.types import GenerationPrompt


class GenerationPromptTests(unittest.TestCase):
    def test_request_content_stays_in_user_message(self):
        question = "질문 전용 식별자 Q42"
        documents = ["첫 문서 D17", "둘째 문서 D29"]
        original = documents.copy()
        prompt = build_prompt(question, documents)

        self.assertIsInstance(prompt, GenerationPrompt)
        self.assertTrue(prompt.system.strip())
        for text in [question, *documents]:
            self.assertIn(text, prompt.user)
            self.assertNotIn(text, prompt.system)
        self.assertLess(
            prompt.user.index(documents[0]), prompt.user.index(documents[1])
        )
        self.assertEqual(documents, original)

    def test_system_policy_is_independent_of_request(self):
        first = build_prompt("첫 질문", ["첫 문서"])
        second = build_prompt("둘째 질문", ["둘째 문서"])
        self.assertEqual(first.system, second.system)
        self.assertNotEqual(first.user, second.user)

    def test_missing_documents_are_explicit(self):
        prompt = build_prompt("신청 방법은?", [])
        self.assertIn("제공된 문서 없음", prompt.user)
        self.assertIn("신청 방법은?", prompt.user)
