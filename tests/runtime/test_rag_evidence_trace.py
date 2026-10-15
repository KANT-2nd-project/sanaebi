import json
import unittest

from app.diagnostics.callback import TraceCallback
from app.diagnostics.stages import _safe_stage_metadata


class EvidenceTraceTests(unittest.TestCase):
    def test_evidence_state_survives_final_rows(self):
        callback = TraceCallback()
        callback.record_generation(
            {
                "status": "completed",
                "evidence_state": "no_matches",
                "raw_text": "SECRET",
            }
        )
        rows = callback.record_rows("/ask", {"question": "q"}, 200)
        text = json.dumps(rows)
        self.assertIn("no_matches", text)
        self.assertNotIn("SECRET", text)

    def test_source_ranges_and_expanded_ids_exclude_contents(self):
        safe = _safe_stage_metadata(
            {
                "selected_chunk_ids": ["original"],
                "expanded_chunk_ids": ["supplement"],
                "source_ranges": [
                    {
                        "document_id": "d",
                        "revision_id": "r",
                        "kind": "expanded",
                        "start": 4,
                        "end": 9,
                        "body": "SECRET",
                    },
                    {
                        "document_id": "d",
                        "revision_id": "r",
                        "kind": "expanded",
                        "start": -1,
                        "end": 4,
                    },
                ],
                "body": "SECRET",
            }
        )
        self.assertEqual(safe["expanded_chunk_ids"], ["supplement"])
        self.assertEqual(len(safe["source_ranges"]), 1)
        self.assertNotIn("SECRET", json.dumps(safe))

    def test_invalid_evidence_enum_not_logged(self):
        callback = TraceCallback()
        callback.record_generation({"evidence_state": "SECRET"})
        self.assertNotIn("SECRET", json.dumps(callback.record_rows("/ask", {}, 200)))
