"""Ensure missing blinded evidence cannot silently improve a score."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "v7_audit",
    ROOT / "generation_evaluation/reports/2026-10-15-prompt-v7/validate_evidence.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class JudgmentAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = {
            "responses": {
                "slot": "s",
                "case_id": "c",
                "prompt_profile": "p",
                "repetition": 1,
            },
            "mapping": {
                "a": {"slot": "s", "case_id": "c", "profile": "p", "repetition": 1}
            },
            "judgments": {
                "responses": [
                    {
                        "anonymous_id": "a",
                        "content": "pass",
                        "required_checks": [{"index": 0, "status": "met"}],
                    }
                ]
            },
            "cases": {"cases": [{"id": "c", "required": ["needed"]}]},
        }

    def run_audit(self):
        paths = {}
        for key, value in self.data.items():
            path = self.root / key
            path.write_text(json.dumps(value) + "\n")
            paths[key] = path
        return MODULE.audit(**paths, profiles=["p"], repetitions=1)

    def test_complete_evidence_passes(self):
        self.assertTrue(self.run_audit()["exact_coverage"])

    def test_mapping_and_judgment_cannot_both_drop_response(self):
        self.data["mapping"] = {}
        self.data["judgments"]["responses"] = []
        with self.assertRaisesRegex(AssertionError, "mapping coverage"):
            self.run_audit()

    def test_empty_checks_cannot_pass(self):
        self.data["judgments"]["responses"][0]["required_checks"] = []
        with self.assertRaises(AssertionError):
            self.run_audit()

    def test_duplicate_mapping_cannot_replace_missing_slot(self):
        self.data["mapping"]["b"] = dict(self.data["mapping"]["a"])
        with self.assertRaisesRegex(AssertionError, "mapping coverage"):
            self.run_audit()

    def test_missing_required_cannot_pass(self):
        self.data["judgments"]["responses"][0]["required_checks"][0]["status"] = (
            "missing"
        )
        with self.assertRaises(AssertionError):
            self.run_audit()
