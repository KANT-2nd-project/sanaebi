import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from retrieval.experiments.calibration_answer_summary import summarize


class AnswerSummaryTests(unittest.TestCase):
    def test_first_failure_stays_counted_after_successful_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def save(relative, value):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
                return path

            save(
                "schedule.json",
                [
                    {
                        "slot_id": "case",
                        "case_id": "Q",
                        "variant_id": "baseline",
                        "repeat": 1,
                    }
                ],
            )
            save("private/blind-map.json", {"Q": {"baseline": "A"}})
            save("slots/case.json", {"status": "completed", "attempts": [1, 2]})
            for number, status in [(1, "json_error_retryable"), (2, "completed")]:
                save(
                    f"attempts/case-attempt-{number}.json",
                    {
                        "status": status,
                        "actual_cost_usd": 0.01,
                        "elapsed_seconds": 1,
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    },
                )
            grades = save(
                "grades.json",
                {
                    "judge": "independent_ai",
                    "human_review": False,
                    "answers": [
                        {
                            "case_id": "Q",
                            "blind_variant": "A",
                            "repeat": 1,
                            "attempts": [
                                {
                                    "attempt": i,
                                    "content_complete": i == 2,
                                    "major_error": False,
                                    "unsupported_assertion": False,
                                    "missing_claims": ["C1"] if i == 1 else [],
                                }
                                for i in [1, 2]
                            ],
                        }
                    ],
                },
            )
            with contextlib.redirect_stdout(io.StringIO()):
                summarize(root, [grades], root / "summary.json")
            result = json.loads((root / "summary.json").read_text())
            s = result["summary"][0]
            self.assertEqual(s["first_format_success"], 0)
            self.assertEqual(s["first_content_complete"], 0)
            self.assertEqual(s["retry_recovered"], 1)
            self.assertEqual(s["final_delivered_complete"], 1)
            self.assertEqual(s["provider_attempts"], 2)
            self.assertEqual(s["estimated_cost_usd"], 0.02)
            self.assertEqual(len(result["rows"][0]["attempts"]), 2)

    def test_known_rejection_cost_requires_settled_ledger(self):
        from retrieval.experiments.calibration_answer_summary import attempt_cost

        attempt = {
            "status": "retryable_provider_error",
            "error_type": "OpenAIRateLimitError",
            "request_id": "request",
            "actual_cost_usd": None,
        }
        ledger = {
            "reservations": {"request": {"status": "settled", "actual_dollars": 0}}
        }
        for status in ("provider_rejected", "retryable_provider_error"):
            self.assertEqual(attempt_cost({**attempt, "status": status}, ledger), 0)
        for invalid in [
            {},
            {
                "reservations": {
                    "request": {"status": "unknown", "actual_dollars": None}
                }
            },
            {
                "reservations": {
                    "request": {"status": "settled", "actual_dollars": False}
                }
            },
        ]:
            with self.assertRaises(ValueError):
                attempt_cost(attempt, invalid)
        with self.assertRaises(ValueError):
            attempt_cost({**attempt, "status": "provider_error_unknown_cost"}, ledger)
