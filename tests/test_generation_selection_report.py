import unittest

from generation_evaluation.selection_report import DIMENSION_IDS, summarize


def _judgment(
    case_id: str,
    repeat: int,
    candidate_id: str,
    verdict: str,
    *,
    severity: str = "none",
    issues: list[dict] | None = None,
    dimension_status: str = "pass",
) -> dict:
    return {
        "case_id": case_id,
        "repeat": repeat,
        "candidate_id": candidate_id,
        "verdict": verdict,
        "severity": severity,
        "issues": issues or [],
        "dimensions": {
            dimension_id: {
                "status": dimension_status,
                "evidence": "근거",
                "reason": "판정 이유",
            }
            for dimension_id in DIMENSION_IDS
        },
    }


def _record(
    case_id: str,
    repeat: int,
    candidate_id: str,
    *,
    status: str = "completed",
    elapsed: float = 1.0,
    calls: list[dict] | None = None,
) -> dict:
    return {
        "case_id": case_id,
        "repeat": repeat,
        "candidate_id": candidate_id,
        "result": {"status": status},
        "elapsed_seconds": elapsed,
        "calls": calls
        if calls is not None
        else [
            {
                "estimated_dollars": 0.01,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 30,
                    "output_token_details": {"reasoning": 5},
                },
                "metadata": {},
            }
        ],
    }


class GenerationSelectionReportTests(unittest.TestCase):
    def test_rank_prioritizes_critical_case_count_over_raw_pass_count(self):
        records = []
        judgments = []
        outcomes = {
            "safe": {
                "c1": ("pass", "pass"),
                "c2": ("pass", "partial"),
                "c3": ("fail", "fail"),
            },
            "risky": {
                "c1": ("pass", "pass"),
                "c2": ("pass", "pass"),
                "c3": ("pass", "fail"),
            },
        }
        for candidate_id, cases in outcomes.items():
            for case_id, verdicts in cases.items():
                for repeat, verdict in enumerate(verdicts, start=1):
                    critical = (
                        candidate_id == "risky" and case_id == "c3" and repeat == 2
                    )
                    records.append(
                        _record(
                            case_id,
                            repeat,
                            candidate_id,
                            status="timeout" if critical else "completed",
                            elapsed=repeat + 0.25,
                            calls=[] if critical else None,
                        )
                    )
                    judgments.append(
                        _judgment(
                            case_id,
                            repeat,
                            candidate_id,
                            verdict,
                            severity="critical" if critical else "none",
                            issues=[{"kind": "critical_error"}] if critical else [],
                            dimension_status="uncertain" if critical else "pass",
                        )
                    )

        result = summarize(records, judgments)
        safe, risky = result["candidates"]
        self.assertEqual(
            [safe["candidate_id"], risky["candidate_id"]], ["safe", "risky"]
        )
        self.assertEqual(safe["pass_count"], 3)
        self.assertEqual(risky["pass_count"], 5)
        self.assertEqual(risky["critical_case_count"], 1)
        self.assertEqual(risky["timeout_count"], 1)
        self.assertEqual(risky["response_count"], 6)
        self.assertEqual(result["denominator"]["attempt_count"], 12)

    def test_candidate_aggregates_latency_tokens_cost_and_dimension_statuses(self):
        records = [
            _record(
                "c1",
                1,
                "a",
                elapsed=2,
                calls=[
                    {
                        "estimated_dollars": 0.02,
                        "usage": {
                            "prompt_tokens": 120,
                            "completion_tokens": 40,
                            "completion_tokens_details": {"reasoning_tokens": 7},
                        },
                        "metadata": {},
                    },
                    {"estimated_dollars": None, "usage": {}, "metadata": {}},
                ],
            ),
            _record("c1", 2, "a", elapsed=4),
        ]
        judgments = [
            _judgment("c1", 1, "a", "pass", dimension_status="pass"),
            _judgment("c1", 2, "a", "pass", dimension_status="na"),
        ]
        candidate = summarize(records, judgments)["candidates"][0]
        self.assertEqual(candidate["stable_both_pass_case_count"], 1)
        self.assertEqual(candidate["repeat_disagreement_case_count"], 0)
        self.assertEqual(candidate["median_elapsed_seconds"], 3)
        self.assertEqual(candidate["max_elapsed_seconds"], 4)
        self.assertEqual(candidate["total_input_tokens"], 220)
        self.assertEqual(candidate["total_output_tokens"], 70)
        self.assertEqual(candidate["total_reasoning_tokens"], 12)
        self.assertEqual(candidate["estimated_cost_dollars"], 0.03)
        self.assertEqual(candidate["estimated_cost_unknown_count"], 1)
        self.assertEqual(candidate["dimension_counts"]["format"]["pass"], 1)
        self.assertEqual(candidate["dimension_counts"]["format"]["na"], 1)
        self.assertFalse(candidate["default_promotable"])

    def test_unknown_cost_ranks_after_known_cost_when_priorities_tie(self):
        records = []
        judgments = []
        for candidate_id, estimated_cost in (("known", 0.01), ("unknown", None)):
            for repeat in (1, 2):
                records.append(
                    _record(
                        "c1",
                        repeat,
                        candidate_id,
                        calls=[
                            {
                                "estimated_dollars": estimated_cost,
                                "usage": {},
                                "metadata": {},
                            }
                        ],
                    )
                )
                judgments.append(_judgment("c1", repeat, candidate_id, "pass"))
        self.assertEqual(
            [
                row["candidate_id"]
                for row in summarize(records, judgments)["candidates"]
            ],
            ["known", "unknown"],
        )

    def test_join_rejects_duplicate_missing_and_extra_judgments(self):
        records = [_record("c1", 1, "a")]
        judgment = _judgment("c1", 1, "a", "pass")
        with self.assertRaisesRegex(ValueError, "중복 실행"):
            summarize(records + records, [judgment, judgment])
        with self.assertRaisesRegex(ValueError, "중복 판정"):
            summarize(records, [judgment, judgment])
        with self.assertRaisesRegex(ValueError, "일치하지 않습니다"):
            summarize(records, [])
        extra = _judgment("other", 1, "a", "pass")
        with self.assertRaisesRegex(ValueError, "일치하지 않습니다"):
            summarize(records, [judgment, extra])

    def test_final_requires_twenty_shared_cases_with_exactly_two_repeats(self):
        records = []
        judgments = []
        for case_index in range(20):
            case_id = f"case-{case_index:02}"
            for repeat in (1, 2):
                records.append(_record(case_id, repeat, "a"))
                judgments.append(_judgment(case_id, repeat, "a", "pass"))
        summary = summarize(records, judgments, final=True)
        self.assertTrue(summary["final_evaluation"])
        self.assertEqual(summary["denominator"]["case_count"], 20)
        self.assertEqual(summary["candidates"][0]["stable_both_pass_case_count"], 20)
        self.assertTrue(summary["candidates"][0]["default_promotable"])

        with self.assertRaisesRegex(ValueError, "repeat 1, 2"):
            summarize(records[:-1], judgments[:-1], final=True)

    def test_invalid_dimension_vocabulary_and_call_types_are_rejected(self):
        record = _record("c1", 1, "a")
        judgment = _judgment("c1", 1, "a", "pass")
        bad_dimensions = dict(judgment["dimensions"])
        bad_dimensions.pop("format")
        with self.assertRaisesRegex(ValueError, "8개 차원"):
            summarize([record], [{**judgment, "dimensions": bad_dimensions}])

        bad_status_dimensions = {
            **judgment["dimensions"],
            "format": {"status": "partial", "evidence": "", "reason": ""},
        }
        with self.assertRaisesRegex(ValueError, "status는"):
            summarize([record], [{**judgment, "dimensions": bad_status_dimensions}])

        with self.assertRaisesRegex(TypeError, "calls는"):
            summarize([{**record, "calls": None}], [judgment])

    def test_failures_and_timeouts_remain_in_denominator_and_promotion_gate(self):
        records = [
            _record("c1", 1, "a"),
            _record("c1", 2, "a", status="timeout", calls=[]),
        ]
        judgments = [
            _judgment("c1", 1, "a", "pass"),
            _judgment(
                "c1",
                2,
                "a",
                "uncertain",
                severity="omission",
                issues=[{"kind": "required_omission"}],
            ),
        ]
        candidate = summarize(records, judgments)["candidates"][0]
        self.assertEqual(candidate["response_count"], 2)
        self.assertEqual(candidate["uncertain_count"], 1)
        self.assertEqual(candidate["generation_failure_count"], 1)
        self.assertEqual(candidate["timeout_count"], 1)
        self.assertEqual(candidate["repeat_disagreement_case_count"], 1)
        self.assertFalse(candidate["default_promotable"])


if __name__ == "__main__":
    unittest.main()
