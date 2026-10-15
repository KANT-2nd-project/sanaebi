"""Focused checks for routing-policy evaluation integrity and accounting."""

import fcntl
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from generation.documents import render_document
from generation.profiles import build_profile_prompt
from generation_evaluation.budget import BudgetLedger
from scripts.evaluate_routing_policy import (
    EXPECTED_COUNTS,
    EXPECTED_QUESTIONS,
    EvaluationError,
    _check_generation_reservation_join,
    _check_trace_integrity,
    _load_trace,
    _open_or_verify_ledger,
    _prepare_output,
    _run_level_lock,
    _validate_cases,
    _validate_pricing,
    _validate_resume_slots,
    _validate_rubric,
    _validate_snapshots,
    _worker_main,
    build_schedule,
    estimate_observed_cost,
    estimate_upper_bound,
)


def _cases():
    cases = []
    questions = list(EXPECTED_QUESTIONS.values())
    categories = [
        category for category, count in EXPECTED_COUNTS.items() for _ in range(count)
    ]
    for index, category in enumerate(categories):
        question = questions[index] if index < len(questions) else f"질문 {index}"
        cases.append(
            {
                "id": f"case-{index:02}",
                "question": question,
                "category": category,
                "provenance": "existing" if index < 4 else "synthetic",
                "snapshot": "base",
            }
        )
    return {"schema_version": 1, "cases": cases}["cases"]


class RoutingEvaluationIntegrityTests(unittest.TestCase):
    def test_case_set_is_40_cases_with_fixed_category_counts_and_legacy_questions(self):
        normalized = _validate_cases({"schema_version": 1, "cases": _cases()})
        self.assertEqual(len(normalized), 40)

    def test_case_set_rejects_category_drift_and_missing_legacy_problem(self):
        cases = _cases()
        cases[0]["category"] = "unknown"
        with self.assertRaises(EvaluationError):
            _validate_cases({"schema_version": 1, "cases": cases})

        cases = _cases()
        cases[0]["question"] = "바뀐 질문"
        with self.assertRaises(EvaluationError):
            _validate_cases({"schema_version": 1, "cases": cases})

        cases = _cases()
        cases[0]["category"] = []
        with self.assertRaises(EvaluationError):
            _validate_cases({"schema_version": 1, "cases": cases})

        cases = _cases()
        cases[0]["snapshot"] = []
        with self.assertRaises(EvaluationError):
            _validate_cases({"schema_version": 1, "cases": cases})

    def test_rubric_must_cover_each_case_once_with_separate_decision_fields(self):
        cases = _cases()
        rubric = {
            "schema_version": 1,
            "cases": {
                case["id"]: {
                    "allowed_actions": ["answer"],
                    "required_claims": [],
                    "forbidden_claims": ["fabricated action"],
                    "evidence": [],
                }
                for case in cases
            },
        }
        _validate_rubric(rubric, cases)
        first_id = cases[0]["id"]
        rubric["cases"][first_id]["id"] = "other-case"
        with self.assertRaises(EvaluationError):
            _validate_rubric(rubric, cases)
        del rubric["cases"][first_id]["id"]
        rubric["cases"]["duplicate"] = dict(next(iter(rubric["cases"].values())))
        with self.assertRaises(EvaluationError):
            _validate_rubric(rubric, cases)

    def test_snapshot_contract_accepts_four_fixed_snapshots_and_rejects_duplicate_ids(
        self,
    ):
        snapshots = {"schema_version": 1}
        snapshots.update(
            {
                name: [
                    {
                        "knowledge_id": "DOC-1",
                        "title": "규정",
                        "body": "게시된 문서 본문",
                        "revision": 1,
                    }
                ]
                for name in ("base", "added", "revised", "withdrawn")
            }
        )
        _validate_snapshots(snapshots)
        snapshots["base"].append(dict(snapshots["base"][0]))
        with self.assertRaises(EvaluationError):
            _validate_snapshots(snapshots)

    def test_interleaving_is_repeatable_and_each_case_repeat_has_both_modes(self):
        cases = _cases()
        first = build_schedule(cases)
        self.assertEqual(first, build_schedule(cases))
        self.assertEqual(len(first), 160)
        for index in range(0, len(first), 2):
            pair = first[index : index + 2]
            self.assertEqual(pair[0]["case_id"], pair[1]["case_id"])
            self.assertEqual(pair[0]["repeat"], pair[1]["repeat"])
            self.assertEqual({item["mode"] for item in pair}, {"gate", "shadow"})

    def test_pricing_requires_verified_https_source_and_upper_bound_basis(self):
        pricing = {
            "model": "gpt-6-luna",
            "input_usd_per_million": 0.25,
            "output_usd_per_million": 0.75,
            "source_url": "https://developers.openai.com/api/docs/pricing",
            "verified_at": "2026-10-15",
            "pricing_basis": "standard_long_context_all_input_at_cache_write_upper_bound",
        }
        _validate_pricing(pricing)
        invalid = dict(pricing, output_usd_per_million=float("nan"))
        with self.assertRaises(EvaluationError):
            _validate_pricing(invalid)

    def test_cost_bounds_reserve_output_and_unknown_usage_stays_unknown(self):
        pricing = {
            "input_usd_per_million": 0.25,
            "output_usd_per_million": 0.75,
        }
        bound = estimate_upper_bound([HumanMessage(content="abc")], 4096, pricing)
        self.assertAlmostEqual(bound, (259 * 0.25 + 4096 * 0.75) / 1_000_000)
        self.assertIsNone(estimate_observed_cost({"steps": []}, pricing))
        trace = {
            "steps": [
                {
                    "stage": "생성 판정",
                    "input_tokens": 100,
                    "output_tokens": 10,
                }
            ]
        }
        self.assertAlmostEqual(estimate_observed_cost(trace, pricing), 32.5 / 1_000_000)

    def test_trace_requires_mode_source_state_and_reservation_join_fields(self):
        good = {
            "steps": [
                {
                    "stage": "분류",
                    "routing_mode": "shadow",
                    "label_source": "model",
                    "classification_status": "ok",
                    "classification_elapsed_seconds": 0.01,
                    "processing_path": "generation",
                    "generation_attempted": True,
                }
            ]
        }
        self.assertIs(_check_trace_integrity(good, "shadow"), good["steps"][0])
        with self.assertRaises(EvaluationError):
            _check_trace_integrity(good, "gate")
        with self.assertRaises(EvaluationError):
            _check_trace_integrity({"steps": [{"stage": "분류"}]}, "shadow")
        with self.assertRaises(EvaluationError):
            _check_generation_reservation_join(
                good["steps"][0], {"generation_reserved": False}
            )
        _check_generation_reservation_join(
            good["steps"][0], {"generation_reserved": False, "budget_blocked": True}
        )

    def test_resume_refuses_uncertain_slots_without_recalling_them(self):
        schedule = build_schedule(_cases())
        slot_id = schedule[0]["slot_id"]
        with self.assertRaises(EvaluationError):
            _validate_resume_slots({slot_id}, {}, schedule)
        _validate_resume_slots({slot_id}, {slot_id: {"http_status": 502}}, schedule)
        with self.assertRaises(EvaluationError):
            _validate_resume_slots(set(), {"not-in-plan": {}}, schedule)

    def test_resume_refuses_missing_or_replaced_budget_ledger(self):
        schedule = build_schedule(_cases())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            state = {"started_at_epoch": None, "ledger_identity": None}
            ledger = _open_or_verify_ledger(
                output=output,
                resume=False,
                run_state=state,
                results={},
                schedule=schedule,
            )
            slot_id = schedule[0]["slot_id"]
            ledger.reserve(slot_id, "final", 0.05)
            ledger.settle(slot_id, None)
            results = {slot_id: {"generation_reserved": True}}
            _open_or_verify_ledger(
                output=output,
                resume=True,
                run_state=state,
                results=results,
                schedule=schedule,
            )
            (output / "budget.json").unlink()
            with self.assertRaises(EvaluationError):
                _open_or_verify_ledger(
                    output=output,
                    resume=True,
                    run_state=state,
                    results=results,
                    schedule=schedule,
                )

    def test_run_lock_blocks_a_second_execution_for_the_same_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            lock = _run_level_lock(output)
            try:
                with self.assertRaises(EvaluationError):
                    _run_level_lock(output)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()

    def test_trace_id_can_be_joined_to_trace_record_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-10-15.jsonl"
            path.write_text(
                json.dumps({"trace_id": "abc", "steps": []}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(_load_trace(Path(directory), "abc")["trace_id"], "abc")
            self.assertIsNone(_load_trace(Path(directory), "missing"))

    def test_output_manifest_blocks_overwrite_and_changed_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            manifest = {"schema_version": 1, "created_at": None, "code": "same"}
            _prepare_output(output, manifest, resume=False)
            with self.assertRaises(EvaluationError):
                _prepare_output(output, manifest, resume=False)
            _prepare_output(output, manifest, resume=True)
            with self.assertRaises(EvaluationError):
                _prepare_output(output, dict(manifest, code="changed"), resume=True)

    def test_cli_can_be_launched_as_a_script(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "scripts/evaluate_routing_policy.py"),
                "--help",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gate-versus-shadow HTTP comparison", result.stdout)


class RoutingEvaluationWorkerTests(unittest.TestCase):
    def _run_worker(self, mode, *, max_dollars=5.0):
        from app import fastapi_main
        from scripts import evaluate_routing_policy as runner

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        trace_dir = root / "traces"
        trace_dir.mkdir()
        document = {
            "knowledge_id": "SNAPSHOT-ADDED",
            "title": "테스트 추가 규정",
            "body": "이 문서는 added 스냅샷에만 있으며 답변 프롬프트에 포함되어야 합니다.",
            "revision": 3,
        }
        snapshots = {
            "schema_version": 1,
            "base": [],
            "added": [document],
            "revised": [],
            "withdrawn": [],
        }
        pricing = {
            "model": "gpt-6-luna",
            "input_usd_per_million": 0.25,
            "output_usd_per_million": 0.75,
            "source_url": "https://developers.openai.com/api/docs/pricing",
            "verified_at": "2026-10-15",
            "pricing_basis": "standard_long_context_all_input_at_cache_write_upper_bound",
        }
        snapshots_path = root / "snapshots.json"
        pricing_path = root / "pricing.json"
        ledger_path = root / "budget.json"
        snapshots_path.write_text(json.dumps(snapshots), encoding="utf-8")
        pricing_path.write_text(json.dumps(pricing), encoding="utf-8")
        config_path = root / "worker-config.json"
        config_path.write_text(
            json.dumps(
                {
                    "snapshots": str(snapshots_path),
                    "pricing": str(pricing_path),
                    "ledger": str(ledger_path),
                }
            ),
            encoding="utf-8",
        )
        slot_id = f"{mode}:added-snapshot:r1"
        now = time.time()
        slot = {
            "slot_id": slot_id,
            "mode": mode,
            "case_id": "added-snapshot",
            "repeat": 1,
            "case": {
                "id": "added-snapshot",
                "question": "추가 문서에 기록된 기준을 알려주세요.",
                "category": "business_guidance",
                "provenance": "synthetic_test",
                "snapshot": "added",
            },
            "deadline_epoch": now + 300,
            "experiment_started_at_epoch": now,
        }

        calls = []

        class FakeClassifier:
            def predict(self, question):
                return "UNSUPPORTED"

        class FakeAnswerer:
            def answer(self, question, snapshot):
                calls.append((question, snapshot))
                ledger = BudgetLedger(ledger_path)
                self_slot_reservations = ledger.snapshot()["reservations"]
                if slot_id not in self_slot_reservations:
                    raise AssertionError("generation ran before its ledger reservation")
                return "문서 근거에 따른 테스트 답변입니다."

        answerer = FakeAnswerer()

        @asynccontextmanager
        async def test_lifespan(application):
            application.state.routing_mode = mode
            application.state.classifier = FakeClassifier()
            application.state.answerer = answerer
            yield

        old_lifespan = fastapi_main.app.router.lifespan_context
        old_state = {
            name: getattr(fastapi_main.app.state, name, None)
            for name in ("routing_mode", "classifier", "answerer", "document_provider")
        }
        original_max_dollars = runner.MAX_DOLLARS
        runner.MAX_DOLLARS = max_dollars
        fastapi_main.app.router.lifespan_context = test_lifespan
        args = SimpleNamespace(
            worker_config=config_path,
            worker_mode=mode,
            worker_trace=trace_dir,
        )
        stdout = StringIO()
        try:
            with (
                patch.dict(
                    "os.environ",
                    {"TRACE_DIR": str(trace_dir), "TRACE_FULL_PROMPT": "0"},
                ),
                patch("sys.stdin", StringIO(json.dumps(slot) + "\n")),
                patch("sys.stdout", stdout),
            ):
                return_code = _worker_main(args)
        finally:
            runner.MAX_DOLLARS = original_max_dollars
            fastapi_main.app.router.lifespan_context = old_lifespan
            for name, value in old_state.items():
                if value is None:
                    fastapi_main.app.state.__dict__.pop(name, None)
                else:
                    setattr(fastapi_main.app.state, name, value)

        records = [json.loads(line) for line in stdout.getvalue().splitlines()]
        return return_code, records, calls, ledger_path, slot, document, trace_dir

    def test_shadow_http_worker_reserves_before_answer_and_uses_selected_snapshot_prompt(
        self,
    ):
        return_code, records, calls, ledger_path, slot, document, trace_dir = (
            self._run_worker("shadow")
        )
        self.assertEqual(return_code, 0)
        self.assertEqual(records[0], {"worker_ready": True, "mode": "shadow"})
        result = records[1]
        self.assertEqual(result["http_status"], 200)
        self.assertTrue(result["generation_reserved"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], slot["case"]["question"])
        self.assertEqual(
            calls[0][1].documents[0].knowledge_id, document["knowledge_id"]
        )

        from generation.presets import load_runtime_settings

        settings = load_runtime_settings(Path(__file__).resolve().parents[1])
        rendered = render_document(
            document["knowledge_id"],
            document["title"],
            document["body"],
            document["revision"],
        )
        prompt = build_profile_prompt(
            slot["case"]["question"], [rendered], settings.prompt_profile
        )
        import hashlib

        expected_prompt_hash = hashlib.sha256(
            json.dumps(
                {"system": prompt.system, "user": prompt.user},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(result["prompt_sha256"], expected_prompt_hash)
        self.assertIsNone(result["usage_cost_upper_estimate_dollars"])

        reservation = BudgetLedger(ledger_path).snapshot()["reservations"][
            slot["slot_id"]
        ]
        self.assertEqual(reservation["status"], "settled")
        self.assertIsNone(reservation["actual_dollars"])
        self.assertEqual(
            reservation["charged_dollars"], reservation["reserved_dollars"]
        )
        self.assertIsNotNone(_load_trace(trace_dir, result["trace_id"]))

    def test_gate_http_worker_makes_no_generation_reservation(self):
        return_code, records, calls, ledger_path, _slot, _doc, _traces = (
            self._run_worker("gate")
        )
        self.assertEqual(return_code, 0)
        self.assertEqual(records[1]["http_status"], 200)
        self.assertFalse(records[1]["generation_reserved"])
        self.assertEqual(calls, [])
        self.assertEqual(BudgetLedger(ledger_path).snapshot()["reservations"], {})

    def test_budget_denial_stops_before_answer_and_does_not_create_reservation(self):
        return_code, records, calls, ledger_path, _slot, _doc, _traces = (
            self._run_worker("shadow", max_dollars=0.0)
        )
        self.assertEqual(return_code, 0)
        result = records[1]
        self.assertTrue(result["budget_blocked"])
        self.assertFalse(result["generation_reserved"])
        self.assertEqual(calls, [])
        self.assertEqual(BudgetLedger(ledger_path).snapshot()["reservations"], {})


if __name__ == "__main__":
    unittest.main()
