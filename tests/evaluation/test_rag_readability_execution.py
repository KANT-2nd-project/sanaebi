"""Offline end-to-end safety checks for the bounded live runner."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from generation.presets import load_runtime_settings
from generation_evaluation import rag_readability as runner
from tests.support.generation_settings import historical_prompt_json_settings
from tests.support.paths import ROOT


class FakeClient:
    def __init__(self, invoke):
        self.runnable = RunnableLambda(invoke)

    async def aclose(self):
        pass


class RagReadabilityExecutionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.object(
                runner,
                "load_runtime_settings",
                side_effect=historical_prompt_json_settings,
            )
        )
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.calls = []
        self.write(
            "inputs.json",
            [
                {
                    "id": f"R{i:02d}",
                    "answer_input": {
                        "question": "안녕하세요",
                        "documents": [],
                        "snapshot_fingerprint": "frozen",
                        "evidence_state": "no_matches",
                        "classification_context": {
                            "label": "UNSUPPORTED",
                            "source": "model",
                            "status": "ok",
                        },
                    },
                }
                for i in range(1, 9)
            ],
        )
        self.write("rubric.json", {"fixed": True})
        self.write(
            "pricing.json",
            {
                "currency": "USD",
                "input_usd_per_million_tokens": 0.25,
                "output_usd_per_million_tokens": 0.75,
                "source": "https://developers.openai.com/api/docs/pricing",
                "verified_at": "2026-10-16T09:00:00+09:00",
            },
        )

    def test_frozen_runner_rejects_active_strict_output(self):
        with self.assertRaisesRegex(runner.ReadabilityExperimentError, "고정된 실험"):
            runner._validate_settings(load_runtime_settings(ROOT))
        self.assertEqual(self.calls, [])

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value, ensure_ascii=False))

    def invoke(self, prompt):
        self.calls.append(prompt)
        self.assertTrue((self.directory / "budget.json").is_file())
        return AIMessage(
            content='{"answer":"안녕하세요.\\n\\n어떤 업무가 궁금하신가요?"}',
            response_metadata={"finish_reason": "stop"},
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        )

    def run_fake(self, invoke=None):
        with patch.object(
            runner.answerer_adapter,
            "build_managed_model_call",
            side_effect=lambda config: FakeClient(invoke or self.invoke),
        ):
            return runner.run_experiment(self.directory)

    def test_24_cap_exact_prompts_and_resume_skips_all(self):
        result = self.run_fake()
        self.assertEqual(len(self.calls), 24)
        self.assertEqual(result["completed"], 24)
        records = [
            json.loads(p.read_text())
            for p in sorted((self.directory / "slots").glob("*.json"))
        ]
        self.assertTrue(all(r["prompt_matches_manifest"] for r in records))
        self.assertTrue(
            all(
                r["final_prompt"]["user"] == records[0]["final_prompt"]["user"]
                for r in records
            )
        )
        self.assertTrue(
            all("JSON만 출력" in r["final_prompt"]["system"] for r in records)
        )
        self.assertTrue(all(r["answer"].count("\n") == 2 for r in records))
        self.assertEqual(self.run_fake()["skipped"], 24)
        self.assertEqual(len(self.calls), 24)
        ledger = runner.BudgetLedger(
            self.directory / "budget.json",
            total_dollars=None,
            dev_dollars=None,
            total_seconds=None,
            dev_seconds=None,
            max_calls=24,
        )
        with self.assertRaises(runner.BudgetExceeded):
            ledger.reserve("25th", "final", 0.1)

    def test_parse_failure_and_missing_usage_preserved_on_resume(self):
        def invoke(prompt):
            self.calls.append(prompt)
            return AIMessage(
                content="not json", response_metadata={"finish_reason": "stop"}
            )

        result = self.run_fake(invoke)
        self.assertEqual(result["failed"], 24)
        for entry in result["budget"]["reservations"].values():
            self.assertIsNone(entry["actual_dollars"])
            self.assertGreater(entry["charged_dollars"], 0)
        resumed = self.run_fake()
        self.assertEqual(resumed["failed"], 24)
        self.assertEqual(len(self.calls), 24)

    def test_interrupted_slot_never_recalled(self):
        def interrupt(prompt):
            self.calls.append(prompt)
            raise KeyboardInterrupt("simulated interruption after reservation")

        with self.assertRaises(KeyboardInterrupt):
            self.run_fake(interrupt)
        result = self.run_fake()
        self.assertEqual(len(self.calls), 24)
        self.assertEqual(result["uncertain"], 1)
        self.assertEqual(result["completed"], 23)

    def test_changed_inputs_rubric_and_code_block_before_call(self):
        runner.run_experiment(self.directory, prepare_only=True)
        for name in ["inputs.json", "rubric.json"]:
            original = (self.directory / name).read_text()
            (self.directory / name).write_text(original + " ")
            with self.assertRaises(runner.ReadabilityExperimentError):
                self.run_fake()
            (self.directory / name).write_text(original)
        with (
            patch.object(runner, "_source_hashes", return_value={"changed": "hash"}),
            self.assertRaises(runner.ReadabilityExperimentError),
        ):
            self.run_fake()
        self.assertEqual(self.calls, [])

    def test_wrong_slot_manifest_rejected(self):
        self.run_fake()
        path = self.directory / "slots/slot-01.json"
        value = json.loads(path.read_text())
        value["manifest_sha256"] = "foreign"
        path.write_text(json.dumps(value))
        with self.assertRaises(runner.ReadabilityExperimentError):
            self.run_fake()
        self.assertEqual(len(self.calls), 24)

    def test_no_verified_pricing_no_call(self):
        self.write("pricing.json", {"currency": "USD"})
        with self.assertRaises(runner.ReadabilityExperimentError):
            self.run_fake()
        self.assertEqual(self.calls, [])
