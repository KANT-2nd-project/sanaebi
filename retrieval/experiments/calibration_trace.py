"""Trace each reviewed fact through source spans, ranking and final budgets."""

import argparse
import json
from pathlib import Path

from retrieval.experiments.calibration_metrics import claim_metrics


def trace(qrels_path, search_path, output):
    if output.exists():
        raise ValueError("Preserve existing trace")
    qrels = json.loads(qrels_path.read_text())
    search = json.loads(search_path.read_text())
    rankings = {r["case_id"]: r for r in search["ranking"]}
    rows = {(r["case_id"], r["variant_id"]): r for r in search["rows"]}
    result = []
    for case in qrels["cases"]:
        ranking = rankings[case["case_id"]]["ranking"]
        rank_items = [
            (r["document_id"], [(s["start"], s["end"]) for s in r["spans"]])
            for r in ranking
        ]
        for claim in case["required_claims"]:
            criterion = {"required_claims": [claim]}
            first = next(
                (
                    i
                    for i in range(1, len(ranking) + 1)
                    if claim_metrics(rank_items[:i], criterion)["complete"]
                ),
                None,
            )
            source_chunks = []
            for i, r in enumerate(ranking, 1):
                if any(
                    a["document_id"] == r["document_id"]
                    and any(
                        s["start"] < t["end"] and t["start"] < s["end"]
                        for s in a["spans"]
                        for t in r["spans"]
                    )
                    for a in claim["evidence_alternatives"]
                ):
                    source_chunks.append({"rank": i, **r})
            stages = {}
            for variant in [
                "baseline",
                "score040_max8",
                "score035_unlimited",
                "score035_unlimited_proxy4000",
            ]:
                row = rows.get((case["case_id"], variant))
                if row is None:
                    continue
                chosen = (
                    ranking[:10]
                    if variant == "baseline"
                    else [
                        r
                        for r in ranking
                        if r["score"]
                        >= (0.4 if variant.startswith("score040") else 0.35)
                    ]
                )
                candidate = claim_metrics(
                    [
                        (r["document_id"], [(s["start"], s["end"]) for s in r["spans"]])
                        for r in chosen
                    ],
                    criterion,
                )["complete"]
                final = claim_metrics(
                    [
                        (
                            e["knowledge_id"],
                            [(s["start"], s["end"]) for s in e["spans"]],
                        )
                        for e in row["evidence"]
                    ],
                    criterion,
                )["complete"]
                stages[variant] = {
                    "candidate_included": candidate,
                    "final_included": final,
                    "loss_stage": None
                    if final
                    else "candidate_or_threshold"
                    if not candidate
                    else "selection_or_budget",
                }
            result.append(
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "claim": claim,
                    "first_complete_rank": first,
                    "source_chunks": source_chunks,
                    "stages": stages,
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    trace(a.qrels, a.search, a.output)
