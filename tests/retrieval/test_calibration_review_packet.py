import json
import tempfile
import unittest
from pathlib import Path

from retrieval.experiments.calibration_review_packet import prepare_packet


class ReviewPacketTests(unittest.TestCase):
    def test_two_format_failures_are_kept_in_blind_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"

            def save(relative, value):
                path = run / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))

            slot_id = "R01--baseline--r1"
            save(
                "schedule.json",
                [
                    {
                        "slot_id": slot_id,
                        "case_id": "R01",
                        "variant_id": "baseline",
                        "question": "질문",
                        "repeat": 1,
                    }
                ],
            )
            save("inputs.json", {"cases": [{"case_id": "R01"}]})
            save("private/blind-map.json", {"R01": {"baseline": "A"}})
            save("private/blinding.json", {"seed": "frozen"})
            save(
                f"slots/{slot_id}.json",
                {
                    "case_id": "R01",
                    "status": "json_error_after_retry",
                    "content": None,
                    "attempts": [1, 2],
                },
            )
            for attempt in [1, 2]:
                save(
                    f"attempts/{slot_id}-attempt-{attempt}.json",
                    {
                        "status": "json_error_retryable",
                        "provider_response": {"raw_text": f"비JSON 응답 {attempt}"},
                    },
                )
            qrels = root / "qrels.json"
            qrels.write_text(json.dumps({"cases": [{"case_id": "R01"}]}))
            output = root / "packet.json"
            prepare_packet(run, qrels, ["R01"], output)
            rows = json.loads(output.read_text())["responses"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                [a["raw_text"] for a in rows[0]["attempts"]],
                ["비JSON 응답 1", "비JSON 응답 2"],
            )
            self.assertEqual(rows[0]["status"], "json_error_after_retry")
