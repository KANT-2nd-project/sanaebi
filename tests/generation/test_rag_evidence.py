import unittest

from generation.evidence import compose_evidence_state
from generation.profiles import RAG_PROMPT_PROFILE, build_profile_prompt


class RagEvidenceTests(unittest.TestCase):
    def test_empty_state_is_explicit_without_fake_document(self):
        prompt = build_profile_prompt("안녕하세요", [], RAG_PROMPT_PROFILE)
        actual = compose_evidence_state(prompt, "no_matches")
        self.assertIn("검색 결과 없음", actual.system)
        self.assertIn("인사", actual.system)
        self.assertIn("개인별 상태 조회", actual.system)

    def test_invalid_state_fails(self):
        prompt = build_profile_prompt("질문", [], RAG_PROMPT_PROFILE)
        with self.assertRaises(ValueError):
            compose_evidence_state(prompt, "storage_error")
