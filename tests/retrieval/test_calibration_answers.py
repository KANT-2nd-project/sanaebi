from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import AuthenticationError, RateLimitError

from generation.profiles import build_profile_prompt
from generation.types import ModelResponse
from generation_evaluation.budget import BudgetExceeded, BudgetLedger
from retrieval.experiments import calibration_answers as runner
from tests.support.generation_settings import historical_prompt_json_settings


class FakeProvider:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result


def _openai_error(error_type, status_code):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code, request=request)
    return error_type("test-only", response=response, body=None)


class CalibrationAnswerRunnerTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.object(
                runner.paired_answers,
                "load_runtime_settings",
                side_effect=historical_prompt_json_settings,
            )
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "run"
        self.artifacts.mkdir()
        self.ledger_path = self.root / "common-ledger.json"
        self.env_file = self.root / ".env"
        self.env_file.write_text("OPENAI_API_KEY=test-only\n", encoding="utf-8")
        self.settings_root = Path(runner.ROOT)
        self.input_path = self.root / "inputs.json"
        self.inputs = self._inputs()
        self.input_path.write_text(
            json.dumps(self.inputs, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _prompt(question: str):
        prompt = build_profile_prompt(question, [], "examples_answer_scope_v5")
        return {"system": prompt.system, "user": prompt.user}

    def _inputs(self, phase="development", *, count=48, variant_count=1, repeats=2):
        cases = []
        for index in range(count):
            case_id = f"Q{index + 1:02d}"
            question = f"질문 {index + 1}"
            variants = [
                {
                    "variant_id": f"config-{variant + 1}",
                    "prompt": self._prompt(question),
                }
                for variant in range(variant_count)
            ]
            cases.append(
                {
                    "case_id": case_id,
                    "question": question,
                    "answerable": index % 2 == 0,
                    "variants": variants,
                }
            )
        if phase == "confirmation":
            count = 40
        return {
            "schema_version": 1,
            "phase": phase,
            "repeats": repeats,
            "identifiers": {
                "provider": "openai",
                "model_name": "gpt-6-luna",
                "prompt_profile": "examples_answer_scope_v5",
                "reasoning_effort": "xhigh",
                "max_output_tokens": 16_384,
                "output_mode": "prompt_json",
                "runtime_config": asdict(
                    historical_prompt_json_settings(runner.ROOT).config
                ),
                "snapshot_sha256": "a" * 64,
            },
            "cases": cases,
        }

    def _execute(self, provider, *, artifact_root=None):
        return runner.execute_calibration(
            self.input_path,
            artifact_root or self.artifacts,
            self.ledger_path,
            self.env_file,
            root=self.settings_root,
            provider_factory=lambda _config: provider,
        )

    def test_phase_caps_and_global_planned_retry_ceiling_are_448_and_896(self):
        self.assertEqual(runner.MAX_PLANNED_CALLS, 448)
        self.assertEqual(runner.MAX_API_CALLS, 896)
        dev_max = runner.validate_inputs(self._inputs(variant_count=3))
        confirm = self._inputs(phase="confirmation", count=40, variant_count=2)
        confirm_max = runner.validate_inputs(confirm)
        self.assertEqual(dev_max.planned_calls, 288)
        self.assertEqual(dev_max.max_attempts, 576)
        self.assertEqual(confirm_max.planned_calls, 160)
        self.assertEqual(confirm_max.max_attempts, 320)
        self.assertLessEqual(dev_max.planned_calls + confirm_max.planned_calls, 448)
        self.assertEqual(dev_max.max_attempts + confirm_max.max_attempts, 896)
        with self.assertRaises(runner.CalibrationError):
            runner.validate_inputs(self._inputs(variant_count=4))

    def test_quick_context_is_exactly_12_cases_three_variants_once_and_72_attempts(
        self,
    ):
        inputs = self._inputs("quick_context", count=12, variant_count=3, repeats=1)
        validated = runner.validate_inputs(inputs)
        slots = runner.build_slots(validated)

        self.assertEqual(validated.planned_calls, 36)
        self.assertEqual(validated.max_attempts, 72)
        self.assertEqual(validated.max_api_calls, 72)
        self.assertEqual(len(slots), 36)
        self.assertEqual({slot["repeat"] for slot in slots}, {1})
        self.assertEqual(runner._phase_ledger_name("quick_context"), "dev")

        invalid = [
            self._inputs("quick_context", count=11, variant_count=3, repeats=1),
            self._inputs("quick_context", count=13, variant_count=3, repeats=1),
            self._inputs("quick_context", count=12, variant_count=2, repeats=1),
            self._inputs("quick_context", count=12, variant_count=4, repeats=1),
            self._inputs("quick_context", count=12, variant_count=3, repeats=2),
        ]
        for value in invalid:
            with (
                self.subTest(
                    count=len(value["cases"]),
                    variants=len(value["cases"][0]["variants"]),
                    repeats=value["repeats"],
                ),
                self.assertRaises(runner.CalibrationError),
            ):
                runner.validate_inputs(value)

    def test_quick_context_preflight_requires_a_new_ledger_and_reports_72_cap(self):
        quick_inputs = self._inputs(
            "quick_context", count=12, variant_count=3, repeats=1
        )
        self.input_path.write_text(
            json.dumps(quick_inputs, ensure_ascii=False), encoding="utf-8"
        )

        before = set(self.root.iterdir())
        estimate = runner.preflight(self.input_path, self.ledger_path)

        self.assertEqual(estimate["scheduled_slots"], 36)
        self.assertEqual(estimate["max_provider_calls_in_phase"], 72)
        self.assertEqual(estimate["max_provider_calls_global"], 72)
        self.assertEqual(set(self.root.iterdir()), before)

        old_ledger = BudgetLedger(
            self.ledger_path,
            total_dollars=None,
            dev_dollars=None,
            total_seconds=None,
            dev_seconds=None,
            max_calls=896,
        )
        old_ledger.bind_limits()
        old_ledger.ensure_identity()
        with self.assertRaises(BudgetExceeded):
            runner.preflight(self.input_path, self.ledger_path)

    def test_quick_context_execution_binds_72_call_ledger_and_refuses_old_ledger(self):
        inputs = self._inputs("quick_context", count=12, variant_count=3, repeats=1)
        quick_path = self.root / "quick-inputs.json"
        quick_path.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8")
        quick_root = self.root / "quick-run"
        quick_root.mkdir()
        provider = FakeProvider([_openai_error(AuthenticationError, 401)])

        with self.assertRaises(runner.CalibrationStopped):
            runner.execute_calibration(
                quick_path,
                quick_root,
                self.root / "quick-ledger.json",
                self.env_file,
                root=self.settings_root,
                provider_factory=lambda _config: provider,
            )

        stored = json.loads(
            (self.root / "quick-ledger.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored["budget_limits"]["max_calls"], 72)
        self.assertEqual(len(provider.calls), 1)

        old_ledger_path = self.root / "old-ledger.json"
        old_ledger = BudgetLedger(
            old_ledger_path,
            total_dollars=None,
            dev_dollars=None,
            total_seconds=None,
            dev_seconds=None,
            max_calls=896,
        )
        old_ledger.bind_limits()
        old_ledger.ensure_identity()
        blocked_root = self.root / "blocked-run"
        blocked_root.mkdir()
        blocked_provider = FakeProvider([])
        with self.assertRaises(BudgetExceeded):
            runner.execute_calibration(
                quick_path,
                blocked_root,
                old_ledger_path,
                self.env_file,
                root=self.settings_root,
                provider_factory=lambda _config: blocked_provider,
            )
        self.assertEqual(blocked_provider.calls, [])
        self.assertFalse((blocked_root / runner.EXECUTION_MARKER).exists())

    def test_two_repeats_create_distinct_slots_for_every_config(self):
        validated = runner.validate_inputs(self._inputs(variant_count=2))
        slots = runner.build_slots(validated)
        case_slots = [slot for slot in slots if slot["case_id"] == "Q01"]
        self.assertEqual(
            {(slot["variant_id"], slot["repeat"]) for slot in case_slots},
            {
                ("config-1", 1),
                ("config-1", 2),
                ("config-2", 1),
                ("config-2", 2),
            },
        )
        self.assertEqual(len({slot["slot_id"] for slot in case_slots}), 4)

    def test_schedule_rotates_variant_order_by_case_and_repeat(self):
        slots = runner.build_slots(
            runner.validate_inputs(self._inputs(variant_count=3))
        )
        first_cases = [slot for slot in slots if slot["case_id"] in {"Q01", "Q02"}]
        self.assertEqual(
            [
                (slot["case_id"], slot["repeat"], slot["variant_id"])
                for slot in first_cases
            ],
            [
                ("Q01", 1, "config-1"),
                ("Q01", 1, "config-2"),
                ("Q01", 1, "config-3"),
                ("Q01", 2, "config-2"),
                ("Q01", 2, "config-3"),
                ("Q01", 2, "config-1"),
                ("Q02", 1, "config-2"),
                ("Q02", 1, "config-3"),
                ("Q02", 1, "config-1"),
                ("Q02", 2, "config-3"),
                ("Q02", 2, "config-1"),
                ("Q02", 2, "config-2"),
            ],
        )

    def test_parse_error_is_saved_then_retried_once_and_success_is_not_repeated(self):
        provider = FakeProvider(
            [
                ModelResponse("not-json", 10, 3, "stop"),
                ModelResponse('{"answer":"정상 답변"}', 10, 4, "stop"),
                _openai_error(AuthenticationError, 401),
            ]
        )
        with self.assertRaises(runner.CalibrationStopped):
            self._execute(provider)
        first_slot = runner.build_slots(runner.validate_inputs(self.inputs))[0]
        first_attempt = (
            self.artifacts / "attempts" / f"{first_slot['slot_id']}-attempt-1.json"
        )
        second_attempt = (
            self.artifacts / "attempts" / f"{first_slot['slot_id']}-attempt-2.json"
        )
        first = json.loads(first_attempt.read_text(encoding="utf-8"))
        second = json.loads(second_attempt.read_text(encoding="utf-8"))
        self.assertEqual(first["provider_response"]["raw_text"], "not-json")
        self.assertEqual(first["generation_status"], "parse_error")
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["answer"], "정상 답변")
        self.assertEqual(len(provider.calls), 3)

    def test_settled_rate_limit_is_retried_once_then_success_is_kept(self):
        provider = FakeProvider(
            [
                _openai_error(RateLimitError, 429),
                ModelResponse('{"answer":"복구 답변"}', 10, 4, "stop"),
                _openai_error(AuthenticationError, 401),
            ]
        )
        with self.assertRaises(runner.CalibrationStopped):
            self._execute(provider)
        slot = runner.build_slots(runner.validate_inputs(self.inputs))[0]
        first = json.loads(
            (
                self.artifacts / "attempts" / f"{slot['slot_id']}-attempt-1.json"
            ).read_text(encoding="utf-8")
        )
        second = json.loads(
            (
                self.artifacts / "attempts" / f"{slot['slot_id']}-attempt-2.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(first["status"], "retryable_provider_error")
        self.assertEqual(first["error_type"], "RateLimitError")
        self.assertEqual(second["answer"], "복구 답변")
        self.assertEqual(len(provider.calls), 3)

    def test_authentication_error_stops_without_retry_or_following_slot(self):
        provider = FakeProvider([_openai_error(AuthenticationError, 401)])
        with self.assertRaises(runner.CalibrationStopped):
            self._execute(provider)
        self.assertEqual(len(provider.calls), 1)
        execution = json.loads(
            (self.artifacts / "execution.json").read_text(encoding="utf-8")
        )
        self.assertEqual(execution["status"], "stopped_authentication_error")
        self.assertEqual(execution["provider_calls"], 1)

    def test_unknown_usage_is_preserved_and_never_retried(self):
        provider = FakeProvider(
            [ModelResponse('{"answer":"원문 보존"}', None, 4, "stop")]
        )
        with self.assertRaises(runner.CalibrationStopped):
            self._execute(provider)
        self.assertEqual(len(provider.calls), 1)
        slot = runner.build_slots(runner.validate_inputs(self.inputs))[0]
        record = json.loads(
            (
                self.artifacts / "attempts" / f"{slot['slot_id']}-attempt-1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(record["status"], "unknown_usage")
        self.assertEqual(
            record["provider_response"]["raw_text"], '{"answer":"원문 보존"}'
        )
        self.assertEqual(record["actual_cost_usd"], None)

    def test_ledger_settlement_failure_preserves_raw_response_and_stops(self):
        provider = FakeProvider([ModelResponse('{"answer":"보존"}', 10, 4, "stop")])
        with (
            patch.object(runner.BudgetLedger, "settle", side_effect=OSError("disk")),
            self.assertRaises(OSError),
        ):
            self._execute(provider)
        slot = runner.build_slots(runner.validate_inputs(self.inputs))[0]
        record = json.loads(
            (
                self.artifacts / "attempts" / f"{slot['slot_id']}-attempt-1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(record["status"], "response_received")
        self.assertEqual(record["provider_response"]["raw_text"], '{"answer":"보존"}')
        self.assertEqual(len(provider.calls), 1)

    def test_rate_limit_settlement_failure_is_not_retried(self):
        provider = FakeProvider(
            [
                _openai_error(RateLimitError, 429),
                AssertionError("a failed settlement must not trigger another call"),
            ]
        )
        with (
            patch.object(runner.BudgetLedger, "settle", side_effect=OSError("ledger")),
            self.assertRaises(OSError),
        ):
            self._execute(provider)
        self.assertEqual(len(provider.calls), 1)
        slot = runner.build_slots(runner.validate_inputs(self.inputs))[0]
        record = json.loads(
            (
                self.artifacts / "attempts" / f"{slot['slot_id']}-attempt-1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(record["status"], "provider_rejected")

    def test_rate_limit_error_record_write_failure_is_not_retried(self):
        provider = FakeProvider(
            [
                _openai_error(RateLimitError, 429),
                AssertionError("a failed write must not trigger another call"),
            ]
        )
        original_write = runner._write_json

        def fail_provider_error_write(path, value, *, exclusive=False):
            if (
                path.name.endswith("attempt-1.json")
                and value.get("status") == "provider_rejected"
            ):
                raise OSError("raw error record write")
            original_write(path, value, exclusive=exclusive)

        with (
            patch.object(runner, "_write_json", side_effect=fail_provider_error_write),
            self.assertRaises(OSError),
        ):
            self._execute(provider)
        self.assertEqual(len(provider.calls), 1)

    def test_blinded_packet_order_is_private_reproducible_and_shuffled(self):
        provider = FakeProvider([_openai_error(AuthenticationError, 401)])
        with (
            patch.object(runner.secrets, "token_hex", return_value="test-private-seed"),
            self.assertRaises(runner.CalibrationStopped),
        ):
            self._execute(provider)

        schedule = json.loads(
            (self.artifacts / "schedule.json").read_text(encoding="utf-8")
        )
        packet = runner.build_blinded_packet(self.artifacts)
        self.assertEqual(packet, runner.build_blinded_packet(self.artifacts))
        scheduled_slots = [item["slot_id"] for item in schedule]
        packet_slots = [
            f"{item['case_id']}--config-1--r{item['repeat']}" for item in packet
        ]
        self.assertNotEqual(packet_slots, scheduled_slots)
        packet_text = json.dumps(packet, ensure_ascii=False)
        self.assertNotIn("test-private-seed", packet_text)
        private_blinding = json.loads(
            (self.artifacts / "private" / "blinding.json").read_text(encoding="utf-8")
        )
        self.assertEqual(private_blinding["seed"], "test-private-seed")

    def test_rate_limit_is_the_only_retryable_provider_error(self):
        self.assertTrue(
            runner.is_retryable_provider_error(_openai_error(RateLimitError, 429))
        )

    def test_preflight_estimates_cost_and_has_no_provider_or_file_side_effect(self):
        before = set(self.root.iterdir())
        result = runner.preflight(self.input_path, self.ledger_path)
        self.assertEqual(result["status"], "preflight_only")
        self.assertEqual(result["scheduled_slots"], 96)
        self.assertEqual(result["normal_provider_calls"], 96)
        self.assertEqual(result["max_provider_calls_in_phase"], 192)
        self.assertEqual(result["cost_cap_usd"], None)
        self.assertGreater(result["reserved_cost_estimate_usd_with_all_retries"], 0)
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertFalse(
            runner.is_retryable_provider_error(_openai_error(AuthenticationError, 401))
        )

    def test_duplicate_artifact_execution_is_refused_before_provider_call(self):
        first = FakeProvider([_openai_error(AuthenticationError, 401)])
        with self.assertRaises(runner.CalibrationStopped):
            self._execute(first)
        second = FakeProvider([])
        with self.assertRaises(runner.CalibrationError):
            self._execute(second)
        self.assertEqual(second.calls, [])

    def test_empty_context_is_recorded_without_llm_and_included_in_blind_packet(self):
        inputs = self._inputs()
        inputs["cases"][0]["variants"][0] = {
            "variant_id": "config-1",
            "prompt": None,
            "skipped_reason": "empty_evidence",
            "fixed_response": "현재 확인 가능한 회사 문서가 없어 답변하기 어렵습니다.",
        }
        self.input_path.write_text(
            json.dumps(inputs, ensure_ascii=False), encoding="utf-8"
        )
        provider = FakeProvider([_openai_error(AuthenticationError, 401)])
        with self.assertRaises(runner.CalibrationStopped):
            self._execute(provider)
        first_slot = runner.build_slots(runner.validate_inputs(inputs))[0]
        slot_record = json.loads(
            (self.artifacts / "slots" / f"{first_slot['slot_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(slot_record["status"], "empty_context")
        self.assertEqual(len(provider.calls), 1)
        second_repeat = first_slot | {"repeat": 2}
        second_slot_id = (
            f"{second_repeat['case_id']}--{second_repeat['variant_id']}--r2"
        )
        second_record = json.loads(
            (self.artifacts / "slots" / f"{second_slot_id}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(second_record["status"], "empty_context")
        packet = runner.build_blinded_packet(self.artifacts)
        row = next(item for item in packet if item["case_id"] == "Q01")
        self.assertEqual(row["status"], "empty_context")
        self.assertEqual(
            row["content"], inputs["cases"][0]["variants"][0]["fixed_response"]
        )
        self.assertTrue(row["answerable"])
        self.assertNotIn("variant_id", row)

    def test_shared_plan_registration_returns_cumulative_total_and_enforces_448(self):
        development = self._inputs(variant_count=3)
        confirmation = self._inputs("confirmation", count=40, variant_count=2)
        self.assertEqual(runner.register_plan(self.ledger_path, development), 288)
        self.assertEqual(runner.register_plan(self.ledger_path, confirmation), 448)
        self.assertEqual(
            runner.read_registered_plans(self.ledger_path)["planned_calls"], 448
        )
        with self.assertRaises(BudgetExceeded):
            runner.register_plan(self.ledger_path, development)


if __name__ == "__main__":
    unittest.main()
