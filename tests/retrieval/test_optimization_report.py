import unittest

from retrieval.experiments.optimization_report import (
    aggregate,
    evidence_metrics,
    quality_order,
    rank_metrics,
)


class OptimizationReportTests(unittest.TestCase):
    def test_empty_candidate_does_not_remove_judged_case_from_selection(self):
        case = {"case_id": "q", "answerability": "unanswerable", "required_claims": []}
        evidence = [
            {
                "knowledge_id": "d",
                "spans": [{"start": 0, "end": 1}],
                "chunk_ids": ["a"],
                "text": "x",
            }
        ]
        result = aggregate(
            {
                "rows": [
                    {"case_id": "q", "variant_id": "C_unlimited", "evidence": evidence},
                    {"case_id": "q", "variant_id": "empty", "evidence": []},
                ],
                "rankings": [],
            },
            {"cases": [{"case_id": "q", "passages": [{"chunk_id": "a"}]}]},
            {"cases": [case]},
            [
                {
                    "case_id": "q",
                    "chunk_id": "a",
                    "grade": 2,
                    "reason": "direct procedure",
                }
            ],
        )
        summaries = {r["variant_id"]: r for r in result["summaries"]}
        self.assertEqual(summaries["C_unlimited"]["precision"], 1)
        self.assertEqual(summaries["empty"]["precision"], 0)
        self.assertEqual(summaries["empty"]["common_precision_cases"], ["q"])

    def test_unjudged_pool_nulls_metrics_even_when_selected_are_judged(self):
        result = rank_metrics(["a"], {"a": 3}, {"a", "b"}, 1)
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["ndcg"])
        self.assertEqual(result["unjudged_count"], 1)

    def test_ideal_is_common_pool_and_empty_is_not_perfect(self):
        result = rank_metrics(["a"], {"a": 1, "b": 3}, {"a", "b"}, 1)
        self.assertEqual(result["precision"], 0)
        self.assertAlmostEqual(result["ndcg"], 1 / 7)
        self.assertIsNone(rank_metrics([], {"a": 3}, {"a"}, 5)["precision"])
        self.assertEqual(rank_metrics([], {"a": 3}, {"a"}, 5)["ndcg"], 0)

    def test_and_or_spans_and_unique_selected_chunks(self):
        case = {
            "required_claims": [
                {
                    "claim_id": "r",
                    "evidence_alternatives": [
                        {
                            "document_id": "d",
                            "spans": [{"start": 0, "end": 2}, {"start": 4, "end": 6}],
                        },
                        {"document_id": "other", "spans": [{"start": 10, "end": 12}]},
                    ],
                }
            ]
        }
        evidence = [
            {
                "knowledge_id": "d",
                "spans": [{"start": 0, "end": 2}],
                "chunk_ids": ["a"],
                "text": "xx",
            }
        ]
        self.assertFalse(evidence_metrics(evidence, case, {"a": 3}, {"a"})["complete"])
        evidence.append(
            {
                "knowledge_id": "d",
                "spans": [{"start": 4, "end": 6}],
                "chunk_ids": ["a"],
                "text": "yy",
            }
        )
        result = evidence_metrics(evidence, case, {"a": 3}, {"a"})
        self.assertTrue(result["complete"])
        self.assertEqual(result["direct_precision"], 1)
        self.assertEqual(result["selected_chunks"], 1)

    def test_duplicate_source_positions_count_across_returned_evidence(self):
        evidence = [
            {
                "knowledge_id": "d",
                "spans": [{"start": 0, "end": 4}],
                "chunk_ids": ["a"],
                "text": "abcd",
            },
            {
                "knowledge_id": "d",
                "spans": [{"start": 2, "end": 6}],
                "chunk_ids": ["b"],
                "text": "cdef",
            },
        ]
        result = evidence_metrics(
            evidence, {"required_claims": []}, {"a": 2, "b": 2}, {"a", "b"}
        )
        self.assertEqual(result["duplicate_source_chars"], 2)
        self.assertEqual(result["unique_source_chars"], 6)

    def test_invalid_relevance_grade_rejected(self):
        with self.assertRaises(ValueError):
            rank_metrics(["a"], {"a": True}, {"a"}, 1)

    def test_selection_rejects_lost_success_and_unjudged_pool(self):
        rows = [
            {
                "variant_id": "C_unlimited",
                "complete_ids": ["q"],
                "precision": 0.2,
                "mean_chars": 1000,
                "unjudged": 0,
            },
            {
                "variant_id": "fast",
                "complete_ids": [],
                "precision": 1,
                "mean_chars": 10,
                "unjudged": 0,
            },
            {
                "variant_id": "small",
                "complete_ids": ["q"],
                "precision": 0.5,
                "mean_chars": 100,
                "unjudged": 0,
            },
        ]
        self.assertEqual(quality_order(rows), ["small", "C_unlimited"])
        rows[2]["unjudged"] = 1
        with self.assertRaises(ValueError):
            quality_order(rows)


class ArtifactBindingTests(unittest.TestCase):
    def test_same_ids_with_modified_source_bytes_are_rejected(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path

        from retrieval.experiments.optimization_report import load_verified_inputs

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qrels = root / "qrels.json"
            packet = root / "packet.json"
            search = root / "search.json"
            judgments = root / "judgments.json"
            qrels.write_text('{"cases": []}')
            packet.write_text('{"cases": []}')
            judgments.write_text("[]")
            search.write_text(
                json.dumps(
                    {
                        "qrels_sha256": hashlib.sha256(qrels.read_bytes()).hexdigest(),
                        "relevance_packet_sha256": hashlib.sha256(
                            packet.read_bytes()
                        ).hexdigest(),
                    }
                )
            )
            self.assertEqual(
                len(load_verified_inputs(search, packet, qrels, judgments)), 4
            )
            for changed in (qrels, packet):
                original = changed.read_bytes()
                changed.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, "SHA"):
                    load_verified_inputs(search, packet, qrels, judgments)
                changed.write_bytes(original)


class FinalTieTests(unittest.TestCase):
    def test_final_tie_requires_actual_latency_before_simplicity(self):
        rows = [
            {
                "variant_id": name,
                "complete_ids": ["q"],
                "precision": 1,
                "mean_chars": 10,
                "unjudged": 0,
            }
            for name in ("C_unlimited", "adjacent_top12")
        ]
        with self.assertRaisesRegex(ValueError, "latency"):
            quality_order(rows, require_latency=True)
        rows[0]["warm_p95_ms"] = 20
        rows[1]["warm_p95_ms"] = 10
        self.assertEqual(quality_order(rows, require_latency=True)[0], "adjacent_top12")


class ConfirmationGateTests(unittest.TestCase):
    def test_average_gain_cannot_override_a_lost_baseline_success(self):
        from retrieval.experiments.optimization_report import confirmation_decision

        baseline = {
            "variant_id": "C_unlimited",
            "complete_ids": ["a", "b"],
            "precision": 0.1,
            "unjudged": 0,
        }
        candidate = {
            "variant_id": "adjacent_top12",
            "complete_ids": ["a", "c", "d"],
            "precision": 0.4,
            "unjudged": 0,
        }
        decision = confirmation_decision(baseline, candidate, runtime_passed=True)
        self.assertEqual(decision["adopted"], "C_unlimited")
        self.assertEqual(decision["lost_success_ids"], ["b"])
        candidate["complete_ids"].append("b")
        self.assertEqual(
            confirmation_decision(baseline, candidate, runtime_passed=True)["adopted"],
            "adjacent_top12",
        )
        candidate["unjudged"] = 1
        with self.assertRaisesRegex(ValueError, "judgments"):
            confirmation_decision(baseline, candidate, runtime_passed=True)
