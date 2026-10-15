import unittest

from retrieval.experiments.kure_gate import choose_threshold, decide_adoption, gate_hits


class KureGateTests(unittest.TestCase):
    def test_question_gate_keeps_low_score_exception_and_passes_equality(self):
        hits = [("b", 0.5), ("a", 0.5), ("exception", 0.1)]
        self.assertEqual(
            gate_hits(hits, 0.5, maximum=20),
            [("a", 0.5), ("b", 0.5), ("exception", 0.1)],
        )
        self.assertEqual(gate_hits(hits, 0.5001), [])
        self.assertEqual(gate_hits([], 0.5), [])

    def test_threshold_never_blocks_related_and_lowest_tie_wins(self):
        rows = [
            {"case_id": "r", "related": True, "maximum": 0.5, "gate_negative": False},
            {"case_id": "u1", "related": False, "maximum": 0.1, "gate_negative": True},
            {"case_id": "u2", "related": False, "maximum": 0.2, "gate_negative": True},
            {
                "case_id": "old",
                "related": False,
                "maximum": 0.4,
                "gate_negative": False,
            },
        ]
        result = choose_threshold(rows, required_negative_count=2, minimum_rejections=2)
        self.assertTrue(result["eligible"])
        self.assertAlmostEqual(result["threshold"], 0.3)
        self.assertEqual(result["related_rejected"], [])

    def test_failure_is_explicit_not_an_arbitrary_threshold(self):
        rows = [
            {"case_id": "r", "related": True, "maximum": 0.1, "gate_negative": False},
            {"case_id": "u", "related": False, "maximum": 0.8, "gate_negative": True},
        ]
        self.assertFalse(
            choose_threshold(rows, required_negative_count=1, minimum_rejections=1)[
                "eligible"
            ]
        )

    def test_duplicate_or_nonfinite_scores_fail(self):
        with self.assertRaises(ValueError):
            choose_threshold(
                [
                    {
                        "case_id": "x",
                        "related": True,
                        "maximum": float("nan"),
                        "gate_negative": False,
                    }
                ]
            )
        with self.assertRaises(ValueError):
            gate_hits([("x", 0.2), ("x", 0.3)], 0.1)

    def test_confirmation_regression_or_false_gate_prevents_transition(self):
        args = {
            "development_eligible": True,
            "baseline_success": ["a", "b"],
            "candidate_success": ["a", "b"],
            "related_rejected": [],
            "unrelated_rejected": 5,
            "resource_passed": True,
        }
        self.assertTrue(decide_adoption(**args)["adopted"])
        self.assertFalse(
            decide_adoption(**{**args, "candidate_success": ["a"]})["adopted"]
        )
        self.assertFalse(
            decide_adoption(**{**args, "related_rejected": ["personal_balance"]})[
                "adopted"
            ]
        )
        self.assertFalse(
            decide_adoption(**{**args, "unrelated_rejected": 4})["adopted"]
        )
        self.assertFalse(
            decide_adoption(**{**args, "resource_passed": False})["adopted"]
        )


class ConfirmationCompletenessTests(unittest.TestCase):
    def fixture(self):
        cases = []
        for i in range(40):
            kind = "answerable" if i < 20 else "partial" if i < 25 else "unanswerable"
            cases.append(
                {
                    "case_id": str(i),
                    "related": i < 30,
                    "gate_negative": i >= 30,
                    "answerability": kind,
                }
            )
        rows = [
            {
                "case_id": str(i),
                "complete": True if i < 25 else None,
                "gate_rejected": i >= 30,
            }
            for i in range(40)
        ]
        return cases, rows

    def test_missing_or_duplicate_confirmation_cannot_be_adopted(self):
        from retrieval.experiments.kure_gate import validate_confirmation

        cases, rows = self.fixture()
        validate_confirmation(cases, rows, rows)
        for broken in [rows[:-1], rows[:-1] + [rows[0]]]:
            with self.assertRaises(ValueError):
                validate_confirmation(cases, rows, broken)
        with self.assertRaises(ValueError):
            validate_confirmation(cases[:-1], rows, rows)

    def test_partial_or_missing_resource_measurements_cannot_pass(self):
        from retrieval.experiments.kure_gate import resource_passes

        runs = [
            {
                "concurrency": c,
                "requested": 144,
                "completed": 144,
                "p95_ms": 200.0,
                "max_rss_mib": 3000.0,
            }
            for c in [1, 2]
        ]
        self.assertTrue(resource_passes({"runs": runs}))
        self.assertFalse(resource_passes({"runs": runs[:1]}))
        self.assertFalse(
            resource_passes({"runs": [{**runs[0], "completed": 143}, runs[1]]})
        )
        self.assertFalse(
            resource_passes({"runs": [{**runs[0], "p95_ms": float("nan")}, runs[1]]})
        )
