import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import HumanMessage, SystemMessage

from generation_evaluation.budget import (
    BudgetExceeded,
    BudgetLedger,
    actual_cost,
    reserve_cost,
)


class BudgetLedgerTests(unittest.TestCase):
    def test_reservations_are_atomic_across_threads_and_include_pending_cost(self):
        with TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", 1, 1, 7200, 4200)
            barrier = threading.Barrier(10)
            outcomes: list[str] = []
            outcome_lock = threading.Lock()

            def reserve(index: int) -> None:
                barrier.wait()
                try:
                    ledger.reserve(f"request-{index}", "dev", 0.2)
                except BudgetExceeded:
                    result = "rejected"
                else:
                    result = "reserved"
                with outcome_lock:
                    outcomes.append(result)

            threads = [threading.Thread(target=reserve, args=(i,)) for i in range(10)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(outcomes.count("reserved"), 5)
            self.assertEqual(outcomes.count("rejected"), 5)
            self.assertEqual(len(ledger.snapshot()["reservations"]), 5)

    def test_pending_request_cannot_be_retried_and_unknown_actual_charges_reservation(
        self,
    ):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "budget.json"
            ledger = BudgetLedger(path)
            ledger.reserve("first", "dev", 1.25)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("first", "dev", 1.25)

            ledger.settle("first", None)
            ledger.settle("first", None)
            with self.assertRaises(ValueError):
                ledger.settle("first", 0.5)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("second", "final", 4)

            resumed = BudgetLedger(path)
            self.assertEqual(
                resumed.snapshot()["reservations"]["first"]["charged_dollars"], 1.25
            )

    def test_actual_settlement_releases_unused_reservation_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json", 1, 0.8)
            ledger.reserve("first", "dev", 0.8)
            ledger.settle("first", 0.25)
            ledger.settle("first", 0.25)
            ledger.reserve("second", "dev", 0.55)
            with self.assertRaises(ValueError):
                ledger.settle("first", 0.2)

    def test_invalid_costs_and_unknown_settlement_are_rejected(self):
        with TemporaryDirectory() as directory:
            ledger = BudgetLedger(Path(directory) / "budget.json")
            for value in (True, -1, float("nan"), float("inf")):
                with (
                    self.subTest(value=value),
                    self.assertRaises((TypeError, ValueError)),
                ):
                    ledger.reserve("invalid", "dev", value)
            with self.assertRaises(KeyError):
                ledger.settle("missing", None)

    def test_deadline_starts_at_first_reservation_and_carries_unused_dev_time(self):
        with (
            TemporaryDirectory() as directory,
            patch("generation_evaluation.budget.time.time", return_value=1000.0),
        ):
            ledger = BudgetLedger(
                Path(directory) / "budget.json",
                total_seconds=120,
                dev_seconds=70,
            )
            self.assertEqual(ledger.remaining_seconds("dev"), 70)
            self.assertEqual(ledger.remaining_seconds("final"), 120)
            ledger.reserve("first", "dev", 0.1)
            self.assertEqual(ledger.snapshot()["started_at"], 1000.0)
            with patch("generation_evaluation.budget.time.time", return_value=1030.0):
                self.assertEqual(ledger.remaining_seconds("dev"), 40)
                self.assertEqual(ledger.remaining_seconds("final"), 90)
            with patch("generation_evaluation.budget.time.time", return_value=1070.0):
                self.assertEqual(ledger.remaining_seconds("dev"), 0)
                self.assertEqual(ledger.remaining_seconds("final"), 50)

    def test_zero_cost_reservation_still_respects_shared_phase_clock(self):
        with (
            TemporaryDirectory() as directory,
            patch("generation_evaluation.budget.time.time", return_value=1000.0),
        ):
            ledger = BudgetLedger(
                Path(directory) / "budget.json",
                total_seconds=10,
                dev_seconds=1,
            )
            ledger.reserve("clock-start", "dev", 0)
            with (
                patch("generation_evaluation.budget.time.time", return_value=1001.0),
                self.assertRaises(BudgetExceeded),
            ):
                ledger.reserve("qwen-call", "dev", 0)


class GenerationBudgetCostTests(unittest.TestCase):
    def test_reserve_cost_uses_utf8_byte_upper_bound_and_output_ceiling(self):
        messages = [SystemMessage(content="가" * 100), HumanMessage(content="질문")]
        estimate = reserve_cost(messages, 100)
        input_upper = 300 + 256 + len("질문".encode()) + 256
        self.assertAlmostEqual(estimate, (input_upper * 0.25 + 100 * 0.75) / 1_000_000)

    def test_reserve_cost_keeps_long_tier_rates_for_large_prompts(self):
        estimate = reserve_cost([HumanMessage(content="x" * 272_000)], 100)
        self.assertAlmostEqual(estimate, (272_256 * 0.25 + 100 * 0.75) / 1_000_000)

    def test_actual_cost_accounts_for_cache_read_write_and_missing_write(self):
        with_write = actual_cost(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "prompt_tokens_details": {
                    "cached_tokens": 300,
                    "cache_write_tokens": 200,
                },
            },
            {},
        )
        self.assertAlmostEqual(
            with_write,
            (500 * 0.2 + 300 * 0.02 + 200 * 0.25 + 100 * 0.75) / 1_000_000,
        )

        without_write = actual_cost(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "prompt_tokens_details": {"cached_tokens": 300},
            },
            {},
        )
        self.assertAlmostEqual(
            without_write,
            (700 * 0.25 + 300 * 0.02 + 100 * 0.75) / 1_000_000,
        )

    def test_actual_cost_reads_langchain_metadata_and_returns_none_when_unknown(self):
        cost = actual_cost(
            {},
            {
                "token_usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 50},
                }
            },
        )
        self.assertAlmostEqual(cost, (50 * 0.25 + 50 * 0.02 + 20 * 0.75) / 1_000_000)
        self.assertIsNone(actual_cost({}, {}))

    def test_actual_cost_reads_singular_langchain_cache_details(self):
        cost = actual_cost(
            {},
            {
                "token_usage": {"input_tokens": 1000, "output_tokens": 100},
                "input_token_details": {"cache_read": 300, "cache_creation": 200},
            },
        )
        self.assertAlmostEqual(
            cost,
            (500 * 0.2 + 300 * 0.02 + 200 * 0.25 + 100 * 0.75) / 1_000_000,
        )

    def test_actual_cost_uses_long_rates_and_rejects_inconsistent_cache_counts(self):
        cost = actual_cost(
            {"input_tokens": 272_001, "output_tokens": 2},
            {},
        )
        self.assertAlmostEqual(cost, (272_001 * 0.25 + 2 * 0.75) / 1_000_000)
        self.assertIsNone(
            actual_cost(
                {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 11},
                },
                {},
            )
        )


if __name__ == "__main__":
    unittest.main()
