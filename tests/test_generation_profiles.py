import hashlib
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from generation.profiles import build_profile_prompt


class ProfileCompatibilityTests(unittest.TestCase):
    def test_historical_profiles_keep_identical_messages(self):
        expected = json.loads(
            Path("tests/fixtures/generation-profile-compatibility.json").read_text()
        )
        for name, digest in expected.items():
            with self.subTest(profile=name):
                value = asdict(build_profile_prompt("Q42", ["D17", "D29"], name))
                encoded = (
                    json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
                ).encode()
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), digest)

    def test_scope_changes_only_system_suffix_and_preserves_inputs(self):
        reference = build_profile_prompt("Q42", ["D17", "D29"], "examples")
        scope = build_profile_prompt("Q42", ["D17", "D29"], "examples_answer_scope_v1")
        self.assertEqual(scope.user, reference.user)
        self.assertTrue(scope.system.startswith(reference.system.rstrip() + "\n\n"))
        self.assertGreater(len(scope.system), len(reference.system))

    def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):
            build_profile_prompt("Q42", ["D17"], "unknown-profile")
