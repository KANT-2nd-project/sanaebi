"""Integrity checks for the frozen GPT-6 Luna follow-up benchmark."""

import csv
import hashlib
import json
import unittest

from tests.support.paths import ROOT

BENCHMARK = ROOT / "generation_evaluation" / "benchmarks" / "luna-reference-followup-v1"
SNAPSHOT_SHA256 = "d58dc0ab1d40bdb9fff68362dc4f5a241fb34ac7fee92f551851d933c1adde74"
CORPUS_SHA256 = "84b44e6592e3a6bd883b7890239aada11382cbef9a369ebb0aca3b15defddfe4"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class FollowupBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dev = _json(BENCHMARK / "dev.json")
        cls.holdout = _json(BENCHMARK / "holdout.json")
        cls.rubric = _json(BENCHMARK / "rubric.json")
        cls.corpus_path = ROOT / "data/company-knowledge/documents.jsonl"
        cls.corpus = {
            document["document_id"]: document
            for document in map(
                json.loads, cls.corpus_path.read_text(encoding="utf-8").splitlines()
            )
        }
        with (ROOT / "data/dataset.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            cls.source_questions = {
                row["question_id"]: row for row in csv.DictReader(stream)
            }

    def test_split_sizes_categories_and_intent_groups(self):
        self.assertEqual(len(self.dev), 12)
        self.assertEqual(len(self.holdout), 20)
        self.assertEqual(
            {
                category: sum(case["category"] == category for case in self.holdout)
                for category in (
                    "normal",
                    "partial_missing",
                    "conditions",
                    "authority",
                    "false_premise",
                )
            },
            {
                "normal": 8,
                "partial_missing": 4,
                "conditions": 4,
                "authority": 2,
                "false_premise": 2,
            },
        )
        dev_groups = {case["intent_group"] for case in self.dev}
        holdout_groups = {case["intent_group"] for case in self.holdout}
        self.assertEqual(len(dev_groups), len(self.dev))
        self.assertEqual(len(holdout_groups), len(self.holdout))
        self.assertTrue(dev_groups.isdisjoint(holdout_groups))
        ids = [case["case_id"] for case in self.dev + self.holdout]
        self.assertEqual(len(ids), len(set(ids)))

    def test_search_knowledge_provenance_matches_source_rows(self):
        cases = self.dev + self.holdout
        self.assertEqual(
            sum(case["provenance"]["kind"] == "search_knowledge" for case in cases), 6
        )
        for case in cases:
            provenance = case["provenance"]
            if provenance["kind"] != "search_knowledge":
                continue
            row = self.source_questions[provenance["question_id"]]
            self.assertEqual(case["question"], row["question"])
            self.assertEqual(row["label"], "SEARCH_KNOWLEDGE")
            self.assertEqual(case["intent_group"], row["group_id"])
            self.assertEqual(provenance["original_group_id"], row["group_id"])
            self.assertEqual(provenance["source"], row["source"])

    def test_rubric_contract_and_document_evidence(self):
        self.assertEqual(self.rubric["snapshot_sha256"], SNAPSHOT_SHA256)
        self.assertEqual(
            hashlib.sha256(self.corpus_path.read_bytes()).hexdigest(), CORPUS_SHA256
        )
        self.assertIsInstance(self.rubric["dimensions"], list)
        self.assertEqual(len(self.rubric["case_ids"]), 32)
        self.assertEqual(
            set(self.rubric["case_ids"]),
            {case["case_id"] for case in self.dev + self.holdout},
        )

        for case in self.dev + self.holdout:
            self.assertEqual(case["snapshot_sha256"], SNAPSHOT_SHA256)
            evidence_by_id = {item["evidence_id"]: item for item in case["evidence"]}
            self.assertEqual(len(evidence_by_id), len(case["evidence"]))
            absence_ids = {item["absence_id"] for item in case["absence_checks"]}
            for claim in case["required_claims"] + case["forbidden_claims"]:
                self.assertTrue(
                    set(claim.get("evidence_refs", [])).issubset(evidence_by_id)
                )
                self.assertTrue(
                    set(claim.get("absence_refs", [])).issubset(absence_ids)
                )
            for item in case["evidence"]:
                document = self.corpus[item["document_id"]]
                body = document["document"]
                self.assertEqual(document["title"], item["title"])
                self.assertEqual(item["revision_number"], 1)
                self.assertEqual(
                    hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    item["document_content_hash"],
                )
                start = item["location"]["char_start"]
                end = item["location"]["char_end"]
                self.assertEqual(body[start:end], item["quote"])
                self.assertEqual(body.index(item["quote"]), start)
                self.assertEqual(
                    body.count("\n", 0, start) + 1, item["location"]["line_start"]
                )


if __name__ == "__main__":
    unittest.main()
