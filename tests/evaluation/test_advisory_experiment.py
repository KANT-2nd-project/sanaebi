import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from generation.presets import load_runtime_settings
from generation.types import ModelResponse
from generation_evaluation import advisory_experiment as ae
from generation_evaluation.experiment_support import digest


class AdvisoryExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        corpus = json.loads(ae.CASES.read_text())
        ae.validate_corpus(corpus)
        labels = {
            c["id"]: {"label": "SEARCH_KNOWLEDGE"}
            for phase in ("pilot", "confirmation")
            for c in corpus[phase]
        }
        settings = load_runtime_settings(ae.ROOT)
        self.manifest = {
            "corpus": corpus,
            "labels": labels,
            "documents": [
                {"document_id": "ieum-068", "title": "배포", "document": "테스트"}
            ],
            "profile": settings.prompt_profile,
            "config": asdict(settings.config),
            "code_hashes": ae.code_hashes(),
            "limits": ae.LIMITS,
        }
        self.manifest["slots"] = ae.make_slots(corpus, labels)
        self.manifest["prompt_hashes"] = {
            s["slot"]: digest(asdict(ae.slot_prompt(s, self.manifest)))
            for s in self.manifest["slots"]
        }
        self.manifest["manifest_digest"] = digest(self.manifest)
        ae.write_json(self.output / "manifest.json", self.manifest)
        self.call = Mock(
            return_value=ModelResponse(
                raw_text='{"answer":"답변"}', input_tokens=100, output_tokens=10
            )
        )

    def test_plan_counts_and_control_changes_only_label(self):
        self.assertEqual(len(self.manifest["slots"]), 184)
        pilot = [s for s in self.manifest["slots"] if s["phase"] == "pilot"]
        self.assertEqual(len(pilot), 64)
        self.assertEqual(sum(s["arm"] == "W" for s in pilot), 16)

    def test_same_code_resume_does_not_repeat_completed_or_failed_slots(self):
        self.call.side_effect = [TimeoutError(), RuntimeError("private error")] + [
            self.call.return_value
        ] * 22
        ae.run_batch(self.output, 24, self.call)
        self.assertEqual(self.call.call_count, 24)
        records = ae.read_records(self.output)
        self.assertEqual(next(iter(records.values()))["status"], "timeout")
        self.assertEqual(list(records.values())[1]["error_type"], "RuntimeError")
        self.assertNotIn("private error", (self.output / "responses.jsonl").read_text())
        ae.run_batch(self.output, 24, self.call)
        self.assertEqual(self.call.call_count, 24)

    def test_changed_helper_manifest_refused_before_call(self):
        changed = dict(ae.code_hashes())
        changed["generation/advisory.py"] = "changed"
        with (
            patch.object(ae, "code_hashes", return_value=changed),
            self.assertRaises(ValueError),
        ):
            ae.run_batch(self.output, 24, self.call)
        self.call.assert_not_called()

    def test_budget_exhaustion_does_not_call_provider(self):
        with patch.object(ae, "reserve_cost", return_value=6.0):
            ae.run_batch(self.output, 24, self.call)
        self.call.assert_not_called()
        self.assertIn("budget_stop", (self.output / "events.jsonl").read_text())

    def test_uncertain_slot_never_retried(self):
        ledger = ae.BudgetLedger(self.output / "ledger.json", **ae.LIMITS)
        ledger.bind_limits()
        ledger.reserve(self.manifest["slots"][0]["slot"], "dev", 0.1)
        with self.assertRaises(ValueError):
            ae.run_batch(self.output, 24, self.call)
        self.call.assert_not_called()

    def test_confirmation_requires_complete_bound_semantic_review(self):
        ae.write_json(self.output / "judgments.json", {})
        with self.assertRaises(ValueError):
            ae.run_batch(self.output, 124, self.call)
        self.call.assert_not_called()

    def test_refusal_truncation_and_bad_json_preserve_status_and_usage(self):
        self.call.side_effect = [
            ModelResponse(
                raw_text=None, refusal="refused", input_tokens=100, output_tokens=10
            ),
            ModelResponse(
                raw_text="", finish_reason="length", input_tokens=100, output_tokens=20
            ),
            ModelResponse(raw_text="bad json", input_tokens=100, output_tokens=30),
        ] + [self.call.return_value] * 21
        ae.run_batch(self.output, 24, self.call)
        rows = list(ae.read_records(self.output).values())
        self.assertEqual(
            [r["status"] for r in rows[:3]], ["refusal", "truncated", "parse_error"]
        )
        self.assertTrue(all(r["actual_cost_usd"] is not None for r in rows[:3]))

    def test_pilot_requires_incremental_value_beyond_instructions(self):
        records = {}
        judgments = {}
        for s in self.manifest["slots"][:64]:
            records[s["slot"]] = {"status": "completed"}
            judgments[s["slot"]] = {
                "grade": "pass",
                "reason": "fixture semantic review",
                "serious": False,
                "false_rejection": False,
                "record_sha256": digest(records[s["slot"]]),
            }
        self.assertFalse(
            ae.pilot_decision(self.manifest, records, judgments)["eligible"]
        )
        for arm in ("A", "B"):
            judgments[f"P01:{arm}:1"]["grade"] = "partial"
        self.assertTrue(
            ae.pilot_decision(self.manifest, records, judgments)["eligible"]
        )
        stress = next(s for s in self.manifest["slots"] if s["arm"] == "W")
        judgments[stress["slot"]]["false_rejection"] = True
        self.assertFalse(
            ae.pilot_decision(self.manifest, records, judgments)["eligible"]
        )
        judgments[stress["slot"]]["record_sha256"] = "changed"
        with self.assertRaises(ValueError):
            ae.pilot_decision(self.manifest, records, judgments)
