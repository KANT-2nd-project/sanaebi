import unittest

from retrieval.experiments.calibration_metrics import claim_metrics, ranking_metrics


class CalibrationMetricsTests(unittest.TestCase):
    def test_claims_require_all_claims_but_allow_alternative_documents(self):
        case = {
            "required_claims": [
                {
                    "claim_id": "a",
                    "evidence_alternatives": [
                        {"document_id": "d1", "spans": [{"start": 0, "end": 10}]},
                        {"document_id": "d2", "spans": [{"start": 20, "end": 30}]},
                    ],
                },
                {
                    "claim_id": "b",
                    "evidence_alternatives": [
                        {
                            "document_id": "d1",
                            "spans": [
                                {"start": 40, "end": 45},
                                {"start": 50, "end": 55},
                            ],
                        }
                    ],
                },
            ]
        }
        result = claim_metrics([("d2", [(20, 30)]), ("d1", [(40, 45)])], case)
        self.assertEqual(result["included"], 1)
        self.assertFalse(result["complete"])
        result = claim_metrics(
            [("d2", [(20, 25), (25, 30)]), ("d1", [(40, 45), (50, 55)])], case
        )
        self.assertEqual(result["included"], 2)
        self.assertTrue(result["complete"])

    def test_empty_required_is_not_perfect_recall(self):
        self.assertIsNone(claim_metrics([], {"required_claims": []})["recall"])

    def test_unjudged_is_null_without_reranking(self):
        result = ranking_metrics(["a", "unknown", "b"], {"a": 3, "b": 2, "c": 0}, 3)
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["ndcg"])
        self.assertEqual(result["unjudged_count"], 1)

    def test_idcg_uses_common_pool_and_missing_results_keep_denominator(self):
        result = ranking_metrics(["b"], {"a": 3, "b": 2, "c": 0}, 2)
        self.assertEqual(result["precision"], 0.5)
        self.assertLess(result["ndcg"], 0.5)
        self.assertGreater(result["ndcg"], 0)
