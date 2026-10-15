"""Aggregate frozen claim metrics and independently judged ranking pools."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from retrieval.experiments.calibration_metrics import ranking_metrics


def summarize(search_path, packet_path, grade_paths, output):
    if output.exists():
        raise ValueError("Preserve existing comparison output")
    search = json.loads(search_path.read_text())
    packet = {c["case_id"]: c for c in json.loads(packet_path.read_text())}
    grades = {}
    for path in grade_paths:
        review = json.loads(path.read_text())
        if not review.get("reviewer") or review.get("human_review") is not False:
            raise ValueError("Expected attributed AI review")
        for case in review["cases"]:
            if any(
                type(r["grade"]) is not int or not 0 <= r["grade"] <= 3
                for r in case["grades"]
            ):
                raise ValueError("Invalid grade")
            if case["case_id"] in grades:
                raise ValueError("Duplicate case review")
            chunk_ids = [r["chunk_id"] for r in case["grades"]]
            allowed = {p["chunk_id"] for p in packet[case["case_id"]]["passages"]}
            if len(set(chunk_ids)) != len(chunk_ids) or not set(chunk_ids) <= allowed:
                raise ValueError("Duplicate or out-of-pool grade")
            grades[case["case_id"]] = {
                r["chunk_id"]: r["grade"] for r in case["grades"]
            }
    ranks = {r["case_id"]: r for r in search["ranking"]}
    rows = []
    for row in search["rows"]:
        cid = row["case_id"]
        judged = grades.get(cid, {})
        missing = {p["chunk_id"] for p in packet[cid]["passages"]} - judged.keys()
        scores = ranks[cid]["ranking"]
        variant = row["variant_id"]
        if variant.startswith("baseline"):
            candidates = scores[:10]
        else:
            threshold = 0.40 if variant.startswith("score040") else 0.35
            candidates = [r for r in scores if r["score"] >= threshold]
        metrics = ranking_metrics([r["chunk_id"] for r in candidates], judged, 5)
        if missing:
            metrics.update(precision=None, ndcg=None)
        rows.append(
            {
                "case_id": cid,
                "variant_id": variant,
                "complete": row["complete"],
                "included": row["included"],
                "required": row["required"],
                "characters": row["characters"],
                "tiny_proxy_tokens": row["proxy_tokens"],
                "evidence_count": row["evidence_count"],
                "precision_at_5": metrics["precision"],
                "ndcg_at_5": metrics["ndcg"],
                "unjudged_pool": len(missing),
                "selection_ms": row["selection_ms"],
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [search_path, packet_path, *grade_paths]
            },
            indent=2,
        )
        + "\n"
    )
    with output.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--grades", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.search, args.packet, args.grades, args.output)
