import json
import unittest
from pathlib import Path

from generation.profiles import build_profile_prompt


class PromptV7ProfileTests(unittest.TestCase):
    def test_frozen_v5_and_v6_system_prompts_are_byte_identical(self):
        cases = {
            "examples_answer_scope_v5": Path(
                "generation_evaluation/reports/2026-10-15-readability-v6/"
                "examples_answer_scope_v5.txt"
            ),
            "examples_answer_scope_v6": Path(
                "generation_evaluation/reports/2026-10-15-readability-v6/"
                "examples_answer_scope_v6.txt"
            ),
        }
        for profile, snapshot_path in cases.items():
            with self.subTest(profile=profile):
                actual = build_profile_prompt("Q", ["D"], profile).system.encode()
                self.assertEqual(actual, snapshot_path.read_bytes())

    def test_v7_profiles_append_to_v5_and_preserve_user_input(self):
        question = "실제 질문"
        documents = ["실제 참고 문서"]
        v5 = build_profile_prompt(question, documents, "examples_answer_scope_v5")
        profiles = (
            "examples_answer_scope_v7_readability",
            "examples_answer_scope_v7_completeness",
            "examples_answer_scope_v7_combined",
        )

        for profile in profiles:
            with self.subTest(profile=profile):
                candidate = build_profile_prompt(question, documents, profile)
                self.assertEqual(candidate.user, v5.user)
                self.assertTrue(
                    candidate.system.startswith(v5.system.rstrip() + "\n\n")
                )
                self.assertIn("실제 참고 문서", candidate.user)
                self.assertNotIn("실제 참고 문서", candidate.system)

    def test_readability_candidate_has_scoped_capability_and_branching_examples(self):
        candidate = build_profile_prompt(
            "질문", [], "examples_answer_scope_v7_readability"
        )
        self.assertIn("대표 업무 분야는 짧은 불릿 목록", candidate.system)
        self.assertIn("실제 사내 정책이 아닙니다", candidate.system)
        self.assertIn("별빛연구소", candidate.system)
        self.assertIn("조건별로 구분하세요", candidate.system)

        examples = [
            line.removeprefix("예시 출력(JSON): ")
            for line in candidate.system.splitlines()
            if line.startswith("예시 출력(JSON): ")
        ]
        self.assertEqual(len(examples), 2)
        decoded = [json.loads(example) for example in examples]
        for value in decoded:
            self.assertEqual(set(value), {"answer"})
            self.assertIsInstance(value["answer"], str)
            self.assertIn("\n", value["answer"])
        self.assertIn("\n\n- ", decoded[0]["answer"])
        self.assertIn("\n\n1. ", decoded[1]["answer"])
        self.assertIn("- 승인되면", decoded[1]["answer"])
        self.assertIn("- 반려되면", decoded[1]["answer"])

    def test_completeness_candidate_is_independent_and_combined_registers_both(self):
        v5 = build_profile_prompt("질문", [], "examples_answer_scope_v5")
        readability = build_profile_prompt(
            "질문", [], "examples_answer_scope_v7_readability"
        )
        completeness = build_profile_prompt(
            "질문", [], "examples_answer_scope_v7_completeness"
        )
        combined = build_profile_prompt("질문", [], "examples_answer_scope_v7_combined")

        self.assertIn("완료 확인 방법", completeness.system)
        self.assertIn("반려·실패·미응답", completeness.system)
        self.assertNotIn("예시 출력(JSON):", completeness.system)
        self.assertNotEqual(readability.system, completeness.system)
        self.assertIn("예시 출력(JSON):", combined.system)
        self.assertIn("완료 확인 방법", combined.system)
        self.assertTrue(completeness.system.startswith(v5.system.rstrip() + "\n\n"))


if __name__ == "__main__":
    unittest.main()
