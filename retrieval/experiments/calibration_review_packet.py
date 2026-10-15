"""Export only complete cases for independent, mode-hidden answer review."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from retrieval.experiments.calibration_answers import build_blinded_packet


def prepare_packet(run_root, qrels_path, case_ids, output):
    if output.exists():
        raise ValueError("Preserve existing review packet")
    schedule = json.loads((run_root / "schedule.json").read_text())
    selected = [r for r in schedule if r["case_id"] in case_ids]
    if {r["case_id"] for r in selected} != set(case_ids):
        raise ValueError("Unknown case")
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        (temp / "private").mkdir()
        (temp / "slots").mkdir()
        (temp / "attempts").mkdir()
        for relative in [
            "inputs.json",
            "private/blind-map.json",
            "private/blinding.json",
        ]:
            shutil.copyfile(run_root / relative, temp / relative)
        (temp / "schedule.json").write_text(json.dumps(selected))
        for row in selected:
            relative = Path("slots") / f"{row['slot_id']}.json"
            slot = json.loads((run_root / relative).read_text())
            if slot["status"] not in (
                "completed",
                "generation_error",
                "empty_context",
                "json_error_after_retry",
            ):
                raise ValueError(
                    "Case is unfinished or execution stopped; review only completed groups"
                )
            shutil.copyfile(run_root / relative, temp / relative)
            for attempt in slot["attempts"]:
                relative = Path("attempts") / f"{row['slot_id']}-attempt-{attempt}.json"
                shutil.copyfile(run_root / relative, temp / relative)
        responses = build_blinded_packet(temp)
    qrels = json.loads(qrels_path.read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "review_kind": "mode_score_cost_blinded_ai",
                "cases": [c for c in qrels["cases"] if c["case_id"] in case_ids],
                "responses": responses,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare_packet(args.run_root, args.qrels, args.cases, args.output)
