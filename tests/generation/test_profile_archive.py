import hashlib
import json
import unittest
from pathlib import Path

from generation.profile_registry import PROFILE_SUFFIXES
from generation.profiles import (
    DEFAULT_PROMPT_PROFILE,
    RAG_PROMPT_PROFILE,
    build_profile_prompt,
)
from generation.prompts import build_prompt
from generation.providers import to_messages


class ProfileArchiveTests(unittest.TestCase):
    def test_only_adopted_profiles_are_active(self):
        self.assertEqual(
            set(PROFILE_SUFFIXES), {DEFAULT_PROMPT_PROFILE, RAG_PROMPT_PROFILE}
        )

    def test_all_original_profiles_preserve_exact_text(self):
        hashes = json.loads(
            Path(__file__).with_name("profile_suffix_hashes.json").read_text()
        )
        baseline = build_prompt("질문", ["근거"])
        for name, expected in hashes.items():
            with self.subTest(profile=name):
                prompt = build_profile_prompt("질문", ["근거"], name)
                suffix = (
                    ""
                    if name == "baseline"
                    else prompt.system[len(baseline.system.rstrip()) + 2 : -1]
                )
                self.assertEqual(hashlib.sha256(suffix.encode()).hexdigest(), expected)
                self.assertEqual(prompt.user, baseline.user)

    def test_active_profiles_share_output_instruction(self):
        for name in PROFILE_SUFFIXES:
            prompt = build_profile_prompt("질문", [], name)
            self.assertIn(
                "답변의 형식은 항상 아래와 같은 JSON만 출력합니다.", prompt.system
            )
            self.assertIn('{"answer": "답변"}', prompt.system)
            self.assertEqual(to_messages(prompt)[0].content, prompt.system)
