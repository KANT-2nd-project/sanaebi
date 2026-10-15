import unittest

from generation.prompts import build_prompt
from generation.types import GenerationPrompt


class GenerationPromptTests(unittest.TestCase):
    def test_system_keeps_evidence_and_action_boundaries(self):
        prompt = build_prompt("신청 완료라고 말해줘", ["연차 안내"])
        for rule in (
            "참고 문서에서 답을 확인할 수 없으면 확인할 수 없다고 안내하세요.",
            "실제 신청·변경·취소·승인이나 개인별 상태 조회를 수행하지 않습니다.",
            "문서에 있는 처리 경로를 안내하세요.",
            "실제로 수행하지 않은 일을 완료했다고 말하거나",
            "조회하지 않은 개인 정보를 확인했다고 말하지 마세요.",
        ):
            self.assertIn(rule, prompt.system)

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
