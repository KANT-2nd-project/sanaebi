import json
import unittest

from generation.profiles import build_profile_prompt
from generation.prompts import build_prompt


class GenerationProfileTests(unittest.TestCase):
    def test_baseline_is_identical_to_existing_prompt_builder(self):
        question = "휴가 신청은 어디서 하나요?"
        documents = ["문서 하나", "문서 둘"]
        self.assertEqual(
            build_profile_prompt(question, documents, "baseline"),
            build_prompt(question, documents),
        )

    def test_concise_adds_only_rules_and_keeps_user_input(self):
        prompt = build_profile_prompt("질문", ["문서"], "concise")
        baseline = build_prompt("질문", ["문서"])
        self.assertEqual(prompt.user, baseline.user)
        for rule in (
            "다른 업무의 절차를 가져오지 마세요.",
            "조회 권한이나 조회 경로를 추정하지 마세요.",
            "문의 창구를 실제 처리 메뉴나 처리 절차로 바꾸지 마세요.",
        ):
            self.assertIn(rule, prompt.system)

    def test_examples_are_synthetic_and_do_not_mutate_documents(self):
        documents = ["실제 입력 문서"]
        original = documents.copy()
        prompt = build_profile_prompt("질문", documents, "examples")
        self.assertIn("합성 예시", prompt.system)
        self.assertIn("개인 교육과 외부 강사 등록", prompt.system)
        self.assertIn("개인 교육비 신청", prompt.system)
        self.assertNotIn("공급업체 지급 계좌", prompt.system)
        self.assertIn("AND 조건", prompt.system)
        self.assertNotIn("실제 입력 문서", prompt.system)
        self.assertEqual(documents, original)

    def test_followup_profiles_preserve_documents_and_reference(self):
        reference = build_profile_prompt("질문", ["실제 문서"], "examples")
        for profile in ("examples_coverage", "examples_conditions"):
            prompt = build_profile_prompt("질문", ["실제 문서"], profile)
            self.assertEqual(prompt.user, reference.user)
            self.assertTrue(prompt.system.startswith(reference.system.rstrip()))
            self.assertNotIn("실제 문서", prompt.system)

    def test_json_examples_change_only_example_serialization(self):
        reference = build_profile_prompt("질문", ["문서"], "examples")
        candidate = build_profile_prompt("질문", ["문서"], "examples_json")
        restored = []
        count = 0
        for line in candidate.system.splitlines():
            if line.startswith("답변: "):
                value = json.loads(line.removeprefix("답변: "))
                self.assertEqual(set(value), {"answer"})
                restored.append("답변: " + value["answer"])
                count += 1
            else:
                restored.append(line)
        self.assertEqual(count, 6)
        self.assertEqual("\n".join(restored), reference.system.rstrip("\n"))
        self.assertEqual(candidate.user, reference.user)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            build_profile_prompt("질문", [], "unknown")
