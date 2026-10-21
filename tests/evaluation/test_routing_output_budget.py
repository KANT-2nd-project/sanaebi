"""Offline guardrails for the fixed RSH-040 output-budget follow-up."""

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from generation.config import GenerationOutputMode
from generation.presets import load_runtime_settings
from generation_evaluation.budget import BudgetLedger
from scripts import evaluate_routing_policy as routing
from scripts import verify_routing_output_budget as followup

ROOT = Path(__file__).resolve().parents[2]


def _case():
    return {
        "id": followup.CASE_ID,
        "question": followup.EXPECTED_CASE_QUESTION,
        "category": "mixed_guidance_and_execution",
        "provenance": "new_ai_authored",
        "snapshot": "base",
    }


class RoutingOutputBudgetTests(unittest.TestCase):
    def test_current_defaults_keep_output_budget_16384(self):
        settings = load_runtime_settings(ROOT)
        self.assertEqual(settings.config.model_name, "gpt-6-luna")
        self.assertEqual(settings.config.max_output_tokens, 16384)
        self.assertEqual(settings.config.reasoning_effort, "xhigh")
        self.assertEqual(settings.config.timeout_seconds, 180)
        self.assertIsNone(settings.config.temperature)
        self.assertEqual(settings.config.output_mode.value, "strict_json_schema")
        self.assertEqual(settings.prompt_profile, "examples_answer_scope_v5")

    def test_historical_v1_followup_rejects_current_profile_before_calls(self):
        with self.assertRaisesRegex(followup.FollowupError, "출력 한도 외 생성 설정"):
            followup._verify_final_settings()

    def test_followup_accepts_supported_maximum_and_rejects_out_of_range(self):
        baseline = load_runtime_settings(ROOT)
        maxed = SimpleNamespace(
            config=replace(
                baseline.config,
                max_output_tokens=followup.MAX_OUTPUT_TOKENS,
                output_mode=GenerationOutputMode.PROMPT_JSON,
            ),
            prompt_profile=followup.PROFILE,
        )
        with patch.object(followup, "load_runtime_settings", return_value=maxed):
            self.assertEqual(
                followup._verify_final_settings()[1]["max_output_tokens"], 128000
            )

        too_small = SimpleNamespace(
            config=replace(
                baseline.config,
                max_output_tokens=4096,
                output_mode=GenerationOutputMode.PROMPT_JSON,
            ),
            prompt_profile=followup.PROFILE,
        )
        with (
            patch.object(followup, "load_runtime_settings", return_value=too_small),
            self.assertRaisesRegex(followup.FollowupError, "16384~128000"),
        ):
            followup._verify_final_settings()

    def test_original_40_case_runner_still_rejects_new_generation_default(self):
        with self.assertRaisesRegex(routing.EvaluationError, "현재 모델 설정"):
            routing.build_manifest(
                cases_path=Path("cases.json"),
                rubric_path=Path("rubric.json"),
                snapshots_path=Path("snapshots.json"),
                classifier_path=Path("classifier"),
                pricing_path=Path("pricing.json"),
                cases=[],
                rubric={},
                snapshots={},
                pricing={},
            )

    def test_schedule_contains_only_four_rsh040_slots_with_followup_prefix(self):
        schedule = followup.make_followup_schedule(_case())
        self.assertEqual(len(schedule), 4)
        self.assertEqual(
            {item["slot_id"] for item in schedule},
            {
                "followup:output-budget-followup:gate:RSH-040:r1",
                "followup:output-budget-followup:shadow:RSH-040:r1",
                "followup:output-budget-followup:gate:RSH-040:r2",
                "followup:output-budget-followup:shadow:RSH-040:r2",
            },
        )
        with self.assertRaises(followup.FollowupError):
            followup.make_followup_schedule({"id": "RSH-039"})

    def test_cumulative_budget_rejects_time_cost_or_attempt_overflow(self):
        reservations = {f"old:{index}": {} for index in range(130)}
        valid = followup._validate_budget_headroom(
            reservations=reservations,
            charged_usd=1.92036,
            per_call_bound_usd=0.08,
            now_epoch=1000,
            origin_started_at_epoch=0,
        )
        self.assertEqual(valid["cumulative_generation_attempt_upper_bound"], 134)
        self.assertEqual(valid["absolute_deadline_epoch"], 7200)

        with self.assertRaisesRegex(followup.FollowupError, "160회"):
            followup._validate_budget_headroom(
                reservations={f"old:{index}": {} for index in range(157)},
                charged_usd=1.0,
                per_call_bound_usd=0.01,
                now_epoch=1000,
                origin_started_at_epoch=0,
            )
        with self.assertRaisesRegex(followup.FollowupError, r"\$5"):
            followup._validate_budget_headroom(
                reservations=reservations,
                charged_usd=4.9,
                per_call_bound_usd=0.03,
                now_epoch=1000,
                origin_started_at_epoch=0,
            )
        with self.assertRaisesRegex(followup.FollowupError, "마감"):
            followup._validate_budget_headroom(
                reservations=reservations,
                charged_usd=1.0,
                per_call_bound_usd=0.01,
                now_epoch=7200,
                origin_started_at_epoch=0,
            )

    def test_shared_ledger_is_reused_and_missing_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            source_ledger_path = source / "budget.json"
            source_ledger = BudgetLedger(
                source_ledger_path,
                total_dollars=5,
                dev_dollars=None,
                total_seconds=None,
                dev_seconds=None,
                max_calls=160,
            )
            source_ledger.bind_limits()
            identity = source_ledger.ensure_identity()
            source_ledger.reserve("gate:old-case:r1", "final", 0.1)
            source_ledger.settle("gate:old-case:r1", 0.05)
            initial_bytes = source_ledger_path.read_bytes()
            source_snapshot = source_ledger.snapshot()
            source_info = {
                "path": source,
                "tree_sha256": "source-tree-hash",
                "manifest_sha256": "source-manifest-hash",
                "budget": source_snapshot,
                "run_state": {
                    "started_at_epoch": time.time() - 10,
                    "ledger_identity": identity,
                },
            }
            state = followup._load_or_create_shared_state(source_info, create=True)
            schedule = followup.make_followup_schedule(_case(), "batch-one")
            followup._register_batch(state, "batch-one", root / "output-one", schedule)
            copied = BudgetLedger(
                state["ledger"],
                total_dollars=5,
                dev_dollars=None,
                total_seconds=None,
                dev_seconds=None,
                max_calls=160,
            )
            copied_snapshot = copied.snapshot()
            self.assertEqual(copied_snapshot["ledger_identity"], identity)
            self.assertEqual(
                copied_snapshot["reservations"]["gate:old-case:r1"],
                source_snapshot["reservations"]["gate:old-case:r1"],
            )
            reservation_id = "followup:batch-one:shadow:RSH-040:r1"
            copied.reserve(reservation_id, "final", 0.08)
            copied.settle(reservation_id, 0.05)
            final_snapshot = copied.snapshot()
            followup._finish_batch(
                state,
                "batch-one",
                final_snapshot,
                {
                    "expected_http_slots": 4,
                    "completed_http_slots": 4,
                    "generation_attempts": 1,
                },
            )
            reloaded = followup._load_or_create_shared_state(source_info, create=False)
            self.assertEqual(
                reloaded["ledger_snapshot"]["reservations"][reservation_id]["status"],
                "settled",
            )
            self.assertEqual(len(reloaded["ledger_snapshot"]["reservations"]), 2)
            cumulative = followup._validate_budget_headroom(
                reservations=reloaded["ledger_snapshot"]["reservations"],
                charged_usd=followup._ledger_charge(
                    reloaded["ledger_snapshot"]["reservations"]
                ),
                per_call_bound_usd=0.08,
                now_epoch=time.time(),
                origin_started_at_epoch=time.time() - 10,
            )
            self.assertEqual(cumulative["cumulative_generation_attempt_upper_bound"], 6)
            self.assertEqual(source_ledger_path.read_bytes(), initial_bytes)

            state["ledger"].write_bytes(initial_bytes)
            with self.assertRaisesRegex(followup.FollowupError, "claim에 기록된"):
                followup._load_or_create_shared_state(source_info, create=True)
            state["ledger"].unlink()
            with self.assertRaisesRegex(followup.FollowupError, "일부가 없거나 교체"):
                followup._load_or_create_shared_state(source_info, create=True)
            self.assertEqual(source_ledger_path.read_bytes(), initial_bytes)

    def test_baseline_profile_code_hash_must_match_but_model_config_may_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "generation").mkdir()
            profile = root / "generation/profiles.py"
            model_settings = root / "generation/models.json"
            profile.write_text("PROFILE = 'frozen'\n", encoding="utf-8")
            model_settings.write_text('{"max_output_tokens": 4096}\n', encoding="utf-8")
            baseline = {
                "generation/profiles.py": followup._sha256_file(profile),
                "generation/models.json": "historical-output-setting-hash",
            }
            with patch.object(followup, "ROOT", root):
                actual = followup._verify_baseline_code_hashes(baseline)
                self.assertEqual(
                    actual["generation/profiles.py"], baseline["generation/profiles.py"]
                )
                self.assertNotEqual(
                    actual["generation/models.json"], baseline["generation/models.json"]
                )

                profile.write_text("PROFILE = 'changed'\n", encoding="utf-8")
                with self.assertRaisesRegex(followup.FollowupError, "profiles.py"):
                    followup._verify_baseline_code_hashes(baseline)

    def test_existing_output_path_is_rejected_without_reusing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing"
            output.mkdir()
            marker = output / "marker"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(followup.FollowupError, "이미 있습니다"):
                followup._prepare_output(output, {}, {}, Path("unused"), {})
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_concurrent_followup_run_lock_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "run"
            source.mkdir()
            lock = followup._run_lock(source)
            lock.__enter__()
            try:
                with (
                    self.assertRaisesRegex(followup.FollowupError, "진행 중"),
                    followup._run_lock(source),
                ):
                    pass
            finally:
                lock.__exit__(None, None, None)

    def test_generation_trace_must_match_model_profile_and_output_limit(self):
        expected = {
            "provider": "openai",
            "model_name": "gpt-6-luna",
            "timeout_seconds": 180,
            "context_window": None,
            "max_output_tokens": 16384,
            "reasoning_effort": "xhigh",
            "temperature": None,
            "output_mode": "prompt_json",
            "prompt_profile": followup.PROFILE,
        }
        trace = {
            "steps": [
                {
                    "stage": "생성 판정",
                    "model": expected["model_name"],
                    "profile": expected["prompt_profile"],
                    "config": {
                        key: expected[key]
                        for key in (
                            "provider",
                            "model_name",
                            "timeout_seconds",
                            "context_window",
                            "max_output_tokens",
                            "reasoning_effort",
                            "temperature",
                            "output_mode",
                        )
                    },
                }
            ]
        }
        followup._check_generation_trace_settings(trace, expected)
        trace["steps"][0]["config"]["max_output_tokens"] = 4096
        with self.assertRaisesRegex(followup.FollowupError, "고정 후속 설정"):
            followup._check_generation_trace_settings(trace, expected)


if __name__ == "__main__":
    unittest.main()
