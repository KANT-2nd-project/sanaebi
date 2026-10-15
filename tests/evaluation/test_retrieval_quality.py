"""Evaluation gates protect source evidence and avoid post-holdout tuning."""

import unittest
from types import SimpleNamespace

from app.retrieval.types import SourceSpan
from retrieval.experiments.quality import (
    complete,
    covers,
    improves,
    validate_freeze,
    validate_snapshot,
)


class RetrievalQualityTests(unittest.TestCase):
    def test_required_interval_can_span_adjacent_evidence_but_not_a_gap(self):
        required = {"start": 3, "end": 9}
        self.assertTrue(covers([SourceSpan(2, 6), SourceSpan(6, 10)], required))
        self.assertFalse(covers([SourceSpan(2, 5), SourceSpan(6, 10)], required))

    def test_all_required_conditions_and_document_identity_matter(self):
        case = {
            "document_id": "policy",
            "required_spans": [{"start": 1, "end": 3}, {"start": 7, "end": 9}],
        }
        self.assertFalse(
            complete(
                [("policy", [SourceSpan(0, 4)]), ("other", [SourceSpan(6, 10)])], case
            )
        )
        self.assertTrue(
            complete([("policy", [SourceSpan(0, 4), SourceSpan(6, 10)])], case)
        )

    def test_adoption_requires_new_development_gain_without_any_regression(self):
        def rows(success):
            return [
                {"case_id": key, "final_complete": key in success}
                for key in ("R1", "D1", "D2")
            ]

        self.assertTrue(
            improves(rows({"R1", "D1"}), rows({"R1", "D1", "D2"}), {"D1", "D2"})
        )
        self.assertFalse(improves(rows({"R1", "D1"}), rows({"D1", "D2"}), {"D1", "D2"}))
        self.assertFalse(improves(rows({"D1"}), rows({"R1", "D1"}), {"D1", "D2"}))
        self.assertFalse(improves(rows({"R1", "D1"}), rows({"R1", "D1"}), {"D1", "D2"}))

    def test_unreviewed_cases_and_wrong_source_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_freeze({"status": "draft_pending_independent_review"}, b"source")
        with self.assertRaises(ValueError):
            validate_freeze(
                {
                    "status": "frozen_independent_ai_reviewed",
                    "source": {"sha256": "wrong"},
                },
                b"source",
            )

    def test_reused_snapshot_must_exactly_match_source(self):
        source = [{"document_id": "one", "title": "Title", "document": "body"}]
        doc = SimpleNamespace(knowledge_id="one", title="Title", body="body")
        validate_snapshot(SimpleNamespace(documents=[doc]), source)
        doc.body = "modified"
        with self.assertRaises(ValueError):
            validate_snapshot(SimpleNamespace(documents=[doc]), source)

    def test_cli_runs_all_stages_and_baseline_only_holdout_once(self):
        import hashlib
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from retrieval.experiments.quality import ROOT, main
        from tests.retrieval.helpers import FakeEmbedder

        class LocalFake(FakeEmbedder):
            def __init__(self, _path):
                super().__init__()

            def warmup(self):
                pass

        affinity = os.sched_getaffinity(0)
        self.addCleanup(os.sched_setaffinity, 0, affinity)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = (
                ROOT / "data/company-knowledge/documents.jsonl"
            ).read_bytes().splitlines()[0] + b"\n"
            row = json.loads(raw)
            source = root / "source.jsonl"
            source.write_bytes(raw)
            cases = {
                "status": "frozen_independent_ai_reviewed",
                "source": {"sha256": hashlib.sha256(raw).hexdigest()},
                "unanswerable": [],
            }
            for section, case_id in [
                ("regression_original_18", "R1"),
                ("development_20", "D1"),
                ("holdout_20", "H1"),
            ]:
                cases[section] = [
                    {
                        "case_id": case_id,
                        "question": "휴가 신청",
                        "document_id": row["document_id"],
                        "required_spans": [
                            {"start": 0, "end": 2, "text": row["document"][:2]}
                        ],
                    }
                ]
            casefile = root / "cases.json"
            casefile.write_text(json.dumps(cases))
            common = [
                "--cases",
                str(casefile),
                "--source",
                str(source),
                "--model",
                str(root),
                "--artifact-root",
                str(root / "out"),
            ]
            with patch("retrieval.experiments.quality.TinyEmbedder", LocalFake):
                self.assertEqual(main(["--phase", "development", *common]), 0)
                dev = json.loads((root / "out/development.json").read_text())
                self.assertEqual(len(dev["stages"]), 4)
                self.assertEqual(main(["--phase", "holdout", *common]), 0)
                with self.assertRaises(SystemExit):
                    main(["--phase", "holdout", *common])
