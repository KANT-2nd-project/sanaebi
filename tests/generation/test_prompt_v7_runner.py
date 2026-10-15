import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from generation.types import GenerationResult, GenerationStatus
from generation_evaluation.types import GenerationRun

RUNNER_PATH = Path(
    "generation_evaluation/experiments/prompt-v7-20261015/run.py"
).resolve()
SPEC = importlib.util.spec_from_file_location("prompt_v7_runner", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class PromptV7LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.ledger_path = Path(self.temp_dir.name) / "ledger.sqlite3"
        self.ledger = runner.AttemptLedger(self.ledger_path)
        self.ledger.initialize("global-fingerprint")

    def test_concurrent_reservations_never_exceed_global_limit(self):
        def reserve(index):
            try:
                return self.ledger.claim("development", f"slot-{index}", index, 0.01)
            except runner.CallLimitExceeded:
                return "limit"

        with ThreadPoolExecutor(max_workers=32) as executor:
            results = list(executor.map(reserve, range(140)))

        self.assertEqual(results.count("claimed"), runner.MAX_CALLS)
        self.assertEqual(results.count("limit"), 20)
        with self.ledger._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
        self.assertEqual(count, runner.MAX_CALLS)

    def test_restart_skips_completed_failures_and_refuses_uncertain_retry(self):
        self.assertEqual(
            self.ledger.claim("development", "uncertain", 0, 0.2), "claimed"
        )
        self.assertEqual(self.ledger.claim("development", "failure", 1, 0.3), "claimed")
        self.ledger.finish(
            "failure",
            {
                "result": None,
                "error_type": "TimeoutError",
                "usage_known": False,
                "cost_estimate_usd": 0.3,
            },
        )

        reopened = runner.AttemptLedger(self.ledger_path)
        reopened.initialize("global-fingerprint")
        self.assertEqual(
            reopened.claim("development", "uncertain", 0, 0.2), "uncertain"
        )
        self.assertEqual(reopened.claim("development", "failure", 1, 0.3), "finished")
        with reopened._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
        self.assertEqual(count, 2)

    def test_changed_global_or_stage_fingerprint_blocks_resume(self):
        self.ledger.register_stage("development", {"stage": "development"})
        with self.assertRaises(runner.ExperimentError):
            runner.AttemptLedger(self.ledger_path).initialize("changed-global")
        with self.assertRaises(runner.ExperimentError):
            self.ledger.register_stage("development", {"stage": "changed"})

    def test_unknown_or_partial_usage_keeps_full_slot_reservation(self):
        pricing = {"input_usd_per_million": 0.25, "output_usd_per_million": 0.75}
        reserved = 0.123
        self.assertEqual(
            runner.cost_for_result(None, 30, reserved, pricing),
            (False, reserved),
        )
        self.assertEqual(
            runner.cost_for_result(40, None, reserved, pricing),
            (False, reserved),
        )
        known, cost = runner.cost_for_result(40, 30, reserved, pricing)
        self.assertTrue(known)
        self.assertAlmostEqual(cost, (40 * 0.25 + 30 * 0.75) / 1_000_000)

    def test_evidence_quotes_and_dev_selection_intent_groups_are_validated(self):
        def case(case_id, group, quote="원문 근거 문장"):
            return {
                "id": case_id,
                "intent_group": group,
                "evidence": [
                    {
                        "source": "published_snapshot",
                        "document_id": "doc-1",
                        "title": "업무 안내",
                        "section": "절차",
                        "quote": quote,
                    }
                ],
            }

        development = {"cases": [case("D01", "dev-group")]}
        selection = {"cases": [case("H01", "holdout-group")]}
        snapshot = {
            "documents": [
                {"id": "doc-1", "title": "업무 안내", "body": "절차: 원문 근거 문장"}
            ]
        }
        runner.validate_evidence_sources(development, selection, snapshot)

        selection["cases"][0]["evidence"][0]["quote"] = "없는 문장"
        with self.assertRaises(runner.ExperimentError):
            runner.validate_evidence_sources(development, selection, snapshot)

        selection["cases"][0]["evidence"][0]["quote"] = "원문 근거 문장"
        selection["cases"][0]["intent_group"] = "dev-group"
        with self.assertRaises(runner.ExperimentError):
            runner.validate_evidence_sources(development, selection, snapshot)

    def test_planned_stages_reserve_exactly_36_plus_12_plus_72_slots(self):
        settings = runner.validate_settings(runner.ROOT)
        pricing = {"input_usd_per_million": 0.25, "output_usd_per_million": 0.75}

        def cases(prefix):
            return [
                {
                    "id": f"{prefix}{index:02d}",
                    "question": f"질문 {prefix}{index:02d}",
                    "category": "fixture",
                    "intent_group": f"{prefix}-group-{index:02d}",
                    "exposure": "synthetic_test",
                }
                for index in range(1, 13)
            ]

        development = {"cases": cases("D")}
        selection = {"cases": cases("H")}
        documents = ["합성 문서"]
        development_slots = runner.build_slots(
            "development",
            development,
            selection,
            documents,
            settings,
            pricing,
            None,
        )
        combination_slots = runner.build_slots(
            "combination",
            development,
            selection,
            documents,
            settings,
            pricing,
            None,
        )
        final_slots = runner.build_slots(
            "final",
            development,
            selection,
            documents,
            settings,
            pricing,
            "examples_answer_scope_v7_readability",
        )

        self.assertEqual(len(development_slots), 36)
        self.assertEqual(len(combination_slots), 12)
        self.assertEqual(len(final_slots), 72)
        self.assertEqual(
            len(development_slots) + len(combination_slots) + len(final_slots),
            runner.MAX_CALLS,
        )
        self.assertEqual({slot.repetition for slot in final_slots}, {1, 2, 3})

    def _request_slot(self, case_id, ordinal, question):
        case = {
            "id": case_id,
            "question": question,
            "category": "test",
            "intent_group": f"group-{case_id}",
            "exposure": "test_only",
        }
        return runner._slot(
            case,
            "examples_answer_scope_v5",
            1,
            ordinal,
            ["문서 본문"],
            runner.validate_settings(runner.ROOT),
            {"input_usd_per_million": 0.25, "output_usd_per_million": 0.75},
            "development",
        )

    @staticmethod
    def _run_for(slot, config, *, fail=False, prompt_hash=None):
        result = (
            None
            if fail
            else GenerationResult(
                status=GenerationStatus.COMPLETED,
                raw_text='{"answer":"확인했습니다."}',
                answer="확인했습니다.",
                input_tokens=18,
                output_tokens=7,
                finish_reason="stop",
            )
        )
        return GenerationRun(
            case_id=slot.case["id"],
            config=config,
            result=result,
            elapsed_seconds=0.2,
            error_type="TimeoutError" if fail else None,
            document_count=1,
            prompt_sha256=prompt_hash or slot.prompt_sha256,
            prompt_profile=slot.profile,
        )

    def test_run_stage_exports_raw_success_failure_and_skips_all_saved_states(self):
        settings = runner.validate_settings(runner.ROOT)
        pricing = {"input_usd_per_million": 0.25, "output_usd_per_million": 0.75}
        slots = [
            self._request_slot("case-a", 0, "첫 질문"),
            self._request_slot("case-b", 1, "둘째 질문"),
            self._request_slot("case-c", 2, "셋째 질문"),
        ]
        stage_dir = Path(self.temp_dir.name) / "stages" / "development"
        stage_dir.mkdir(parents=True)
        self.ledger.register_stage("development", {"stage": "development", "count": 3})
        # This started row simulates an uncertain provider request after a process exit.
        self.assertEqual(
            self.ledger.claim("development", slots[2].key, 2, slots[2].reserved_usd),
            "claimed",
        )

        class FakeClient:
            async def aclose(self):
                return None

        fake_client = FakeClient()
        seen = []

        def fake_run_case(
            case_id, config, question, documents, client, *, prompt_profile
        ):
            slot = next(slot for slot in slots if slot.case["id"] == case_id)
            seen.append(case_id)
            return self._run_for(slot, config, fail=case_id == "case-b")

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.object(runner, "build_managed_model_call", return_value=fake_client),
            patch.object(runner, "run_case", side_effect=fake_run_case),
        ):
            summary = asyncio.run(
                runner.run_stage(
                    slots,
                    "development",
                    stage_dir,
                    self.ledger,
                    settings,
                    ["문서 본문"],
                    pricing,
                )
            )

        self.assertEqual(seen, ["case-a", "case-b"])
        self.assertEqual(summary["finished_slots"], 2)
        self.assertEqual(summary["uncertain_started_slots"], 1)
        rows = [
            json.loads(line)
            for line in (stage_dir / "responses.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [row.get("status") for row in rows],
            [None, None, "uncertain_started_no_automatic_retry"],
        )
        self.assertEqual(rows[0]["result"]["raw_text"], '{"answer":"확인했습니다."}')
        self.assertEqual(rows[1]["error_type"], "TimeoutError")
        self.assertFalse(rows[1]["usage_known"])
        self.assertEqual(rows[1]["cost_estimate_usd"], slots[1].reserved_usd)

        seen.clear()
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.object(
                runner,
                "build_managed_model_call",
                side_effect=AssertionError("client should not be created"),
            ),
            patch.object(
                runner,
                "run_case",
                side_effect=AssertionError("saved slots must not be called"),
            ),
        ):
            resumed = asyncio.run(
                runner.run_stage(
                    slots,
                    "development",
                    stage_dir,
                    runner.AttemptLedger(self.ledger_path),
                    settings,
                    ["문서 본문"],
                    pricing,
                )
            )
        self.assertEqual(resumed["finished_slots"], 2)
        self.assertEqual(resumed["uncertain_started_slots"], 1)
        self.assertEqual(resumed["total_reserved_attempts_all_stages"], 3)

    def test_prompt_hash_mismatch_is_saved_then_stops_before_next_slot(self):
        settings = runner.validate_settings(runner.ROOT)
        pricing = {"input_usd_per_million": 0.25, "output_usd_per_million": 0.75}
        slots = [
            self._request_slot("case-a", 0, "첫 질문"),
            self._request_slot("case-b", 1, "둘째 질문"),
        ]
        stage_dir = Path(self.temp_dir.name) / "mismatch"
        stage_dir.mkdir()
        self.ledger.register_stage("development", {"stage": "development", "count": 2})

        class FakeClient:
            async def aclose(self):
                return None

        def mismatched_run(
            case_id, config, question, documents, client, *, prompt_profile
        ):
            return self._run_for(slots[0], config, prompt_hash="0" * 64)

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.object(runner, "build_managed_model_call", return_value=FakeClient()),
            patch.object(runner, "run_case", side_effect=mismatched_run) as run_mock,
            self.assertRaises(runner.ExperimentError),
        ):
            asyncio.run(
                runner.run_stage(
                    slots,
                    "development",
                    stage_dir,
                    self.ledger,
                    settings,
                    ["문서 본문"],
                    pricing,
                )
            )
        self.assertEqual(run_mock.call_count, 1)
        self.assertEqual(self.ledger.status(slots[0].key), "finished")
        self.assertIsNone(self.ledger.status(slots[1].key))

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.object(
                runner,
                "build_managed_model_call",
                side_effect=AssertionError("no request after hash mismatch"),
            ),
            patch.object(runner, "run_case", side_effect=AssertionError("no retry")),
            self.assertRaises(runner.ExperimentError),
        ):
            asyncio.run(
                runner.run_stage(
                    slots,
                    "development",
                    stage_dir,
                    self.ledger,
                    settings,
                    ["문서 본문"],
                    pricing,
                )
            )


if __name__ == "__main__":
    unittest.main()
