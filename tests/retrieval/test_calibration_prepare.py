import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retrieval.experiments import answers
from retrieval.experiments.calibration_prepare import prepare
from tests.support.generation_settings import historical_prompt_json_settings


class CalibrationPrepareConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.object(
                answers,
                "load_runtime_settings",
                side_effect=historical_prompt_json_settings,
            )
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.qrels_path = self.root / "qrels.json"
        self.confirmation_path = self.root / "confirmation.json"
        self.search_path = self.root / "confirmation-search.json"
        self.old_search_path = self.root / "development-search.json"

        self.qrels_path.write_text(
            json.dumps(self._dataset("R", 48), ensure_ascii=False), encoding="utf-8"
        )
        self.confirmation_path.write_text(
            json.dumps(self._dataset("N", 40), ensure_ascii=False), encoding="utf-8"
        )
        confirmation_sha = self._sha(self.confirmation_path)
        qrels_sha = self._sha(self.qrels_path)
        self.search_path.write_text(
            json.dumps(self._search("N", 40, confirmation_sha), ensure_ascii=False),
            encoding="utf-8",
        )
        self.old_search_path.write_text(
            json.dumps(self._search("N", 40, qrels_sha), ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _dataset(prefix, count):
        return {
            "schema_version": 1,
            "status": "frozen_independent_ai_reviewed",
            "cases": [
                {
                    "case_id": f"{prefix}{index:02d}",
                    "question": f"{prefix}{index:02d} 확인 질문",
                    "answerability": "answerable",
                    "required_claims": [],
                }
                for index in range(1, count + 1)
            ],
        }

    @staticmethod
    def _search(prefix, count, qrels_sha):
        rows = []
        for index in range(1, count + 1):
            case_id = f"{prefix}{index:02d}"
            for variant in ("baseline", "candidate"):
                rows.append(
                    {
                        "case_id": case_id,
                        "variant_id": variant,
                        "evidence": [
                            {
                                "knowledge_id": "doc-1",
                                "title": "테스트 문서",
                                "text": f"{case_id} {variant} 근거",
                                "revision": 1,
                            }
                        ],
                    }
                )
        return {
            "qrels_sha": qrels_sha,
            "snapshot_fingerprint": "snapshot-test",
            "model_revision": "revision-test",
            "rows": rows,
        }

    @staticmethod
    def _sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_confirmation_uses_new_questions_and_matching_search_rows(self):
        output = self.root / "prepared-confirmation.json"

        prepare(
            self.qrels_path,
            self.confirmation_path,
            self.search_path,
            ["baseline", "candidate"],
            "confirmation",
            output,
        )

        payload = json.loads(output.read_text(encoding="utf-8"))
        case_ids = [case["case_id"] for case in payload["cases"]]
        self.assertEqual(len(case_ids), 40)
        self.assertEqual(case_ids, [f"N{index:02d}" for index in range(1, 41)])
        self.assertEqual(payload["phase"], "confirmation")
        self.assertEqual(
            payload["identifiers"]["qrels_sha"], self._sha(self.confirmation_path)
        )
        self.assertEqual(
            payload["identifiers"]["development_qrels_sha"],
            self._sha(self.qrels_path),
        )
        first = payload["cases"][0]
        self.assertEqual(first["question"], "N01 확인 질문")
        prompts = {item["variant_id"]: item["prompt"] for item in first["variants"]}
        self.assertIn("N01 baseline 근거", prompts["baseline"]["user"])
        self.assertIn("N01 candidate 근거", prompts["candidate"]["user"])
        self.assertNotIn("R01", json.dumps(payload, ensure_ascii=False))

    def test_development_search_hash_is_rejected_for_confirmation(self):
        output = self.root / "must-not-be-created.json"

        with self.assertRaisesRegex(ValueError, "different qrels"):
            prepare(
                self.qrels_path,
                self.confirmation_path,
                self.old_search_path,
                ["baseline", "candidate"],
                "confirmation",
                output,
            )

        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
