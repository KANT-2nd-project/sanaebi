"""Coverage-aware, model-free metrics for frozen retrieval comparisons."""

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

from retrieval.experiments.calibration_metrics import claim_metrics


def rank_metrics(ids, grades, pool, k):
    """Use one completely judged common pool, including for the ideal ranking."""
    if k < 1:
        raise ValueError("k must be positive")
    if any(
        type(grade) is not int or grade not in range(4) for grade in grades.values()
    ):
        raise ValueError("grades must be integers in [0, 3]")
    ids = list(dict.fromkeys(ids))[:k]
    pool = set(pool)
    if not set(ids).issubset(pool):
        raise ValueError("selected IDs are outside the reviewed pool")
    unknown = len(pool - grades.keys())
    if unknown:
        return {"precision": None, "ndcg": None, "unjudged_count": unknown}

    def dcg(values):
        return sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(values))

    gains = [grades[cid] for cid in ids]
    ideal = dcg(sorted((grades[cid] for cid in pool), reverse=True)[:k])
    return {
        "precision": sum(grade >= 2 for grade in gains) / k if ids else None,
        "ndcg": dcg(gains) / ideal if ideal else None,
        "unjudged_count": 0,
    }


def evidence_metrics(evidence, case, grades, pool):
    """Score returned source spans and unique contributing chunks separately."""
    intervals = {}
    raw_chars = 0
    for item in evidence:
        for span in item["spans"]:
            intervals.setdefault(item["knowledge_id"], []).append(
                (span["start"], span["end"])
            )
            raw_chars += span["end"] - span["start"]
    unique_chars = 0
    for spans in intervals.values():
        cursor = -1
        for start, end in sorted(spans):
            unique_chars += max(0, end - max(cursor, start))
            cursor = max(cursor, end)
    claims = claim_metrics(
        [
            (item["knowledge_id"], [(s["start"], s["end"]) for s in item["spans"]])
            for item in evidence
        ],
        case,
    )
    ids = list(dict.fromkeys(cid for item in evidence for cid in item["chunk_ids"]))
    relevance = rank_metrics(ids, grades, pool, max(1, len(ids)))
    return {
        **claims,
        "direct_precision": relevance["precision"],
        "unjudged_count": relevance["unjudged_count"],
        "selected_chunks": len(ids),
        "evidence_count": len(evidence),
        "body_chars": sum(len(item["text"]) for item in evidence),
        "unique_source_chars": unique_chars,
        "duplicate_source_chars": raw_chars - unique_chars,
    }


def quality_order(summaries, *, require_latency=False):
    """Return a quality shortlist, not acceptance before runtime/holdout gates."""
    if any(row["unjudged"] for row in summaries):
        raise ValueError("complete common-pool judgments are required for selection")
    by_id = {row["variant_id"]: row for row in summaries}
    if len(by_id) != len(summaries):
        raise ValueError("duplicate variant summary")
    baseline_success = set(by_id["C_unlimited"]["complete_ids"])
    eligible = [
        row for row in summaries if baseline_success.issubset(row["complete_ids"])
    ]
    if any(row["precision"] is None for row in eligible):
        raise ValueError("common valid precision is required for selection")
    if require_latency:
        ties = {}
        for row in eligible:
            key = (len(row["complete_ids"]), row["precision"], row["mean_chars"])
            ties.setdefault(key, []).append(row)
        for group in ties.values():
            if len(group) > 1 and any(
                not math.isfinite(row.get("warm_p95_ms", float("inf"))) for row in group
            ):
                raise ValueError("latency is required to resolve a final selection tie")
    eligible.sort(
        key=lambda row: (
            -len(row["complete_ids"]),
            -row["precision"],
            row["mean_chars"],
            row.get("warm_p95_ms", float("inf")),
            row["variant_id"].startswith(("adjacent_", "bge_")),
            row["variant_id"],
        )
    )
    return [row["variant_id"] for row in eligible]


def confirmation_decision(baseline, candidate, *, runtime_passed):
    """Apply the frozen holdout gate; aggregate gains cannot hide regressions."""
    if any(
        row["unjudged"] or row["precision"] is None for row in (baseline, candidate)
    ):
        raise ValueError("complete judgments are required before final confirmation")
    lost = sorted(set(baseline["complete_ids"]) - set(candidate["complete_ids"]))
    precision_regressed = candidate["precision"] < baseline["precision"]
    accepted = runtime_passed and not lost and not precision_regressed
    return {
        "candidate": candidate["variant_id"],
        "adopted": candidate["variant_id"] if accepted else baseline["variant_id"],
        "candidate_accepted": bool(accepted),
        "lost_success_ids": lost,
        "precision_regressed": precision_regressed,
        "runtime_passed": runtime_passed,
    }


def aggregate(search, packet, qrels, judgments):
    """Join explicit per-passage AI judgments, never infer grades from qrel hits."""
    cases = {case["case_id"]: case for case in qrels["cases"]}
    pools = {
        case["case_id"]: {p["chunk_id"] for p in case["passages"]}
        for case in packet["cases"]
    }
    if len(cases) != len(qrels["cases"]) or len(pools) != len(packet["cases"]):
        raise ValueError("duplicate case ID")
    if set(cases) != set(pools):
        raise ValueError("review packet case set does not match frozen qrels")
    grades = {cid: {} for cid in cases}
    for judgment in judgments:
        cid, chunk = judgment["case_id"], judgment["chunk_id"]
        if cid not in pools or chunk not in pools[cid]:
            raise ValueError("judgment outside frozen common pool")
        if chunk in grades[cid]:
            raise ValueError("duplicate judgment")
        if not judgment.get("reason"):
            raise ValueError("judgment reason is required")
        grades[cid][chunk] = judgment["grade"]
    rows = []
    seen = set()
    for row in search["rows"]:
        cid = row["case_id"]
        key = (cid, row["variant_id"])
        if key in seen:
            raise ValueError("duplicate experiment row")
        seen.add(key)
        rows.append(
            {
                "case_id": cid,
                "variant_id": row["variant_id"],
                **evidence_metrics(
                    row["evidence"], cases[cid], grades[cid], pools[cid]
                ),
            }
        )
    variants = sorted({row["variant_id"] for row in rows})
    for variant in variants:
        if {row["case_id"] for row in rows if row["variant_id"] == variant} != set(
            cases
        ):
            raise ValueError("variant does not cover every frozen case")
    common_valid = set(cases)
    for row in rows:
        if row["unjudged_count"]:
            common_valid.discard(row["case_id"])
    summaries = []
    for variant in variants:
        own = [row for row in rows if row["variant_id"] == variant]
        precision = [
            (row["direct_precision"] if row["direct_precision"] is not None else 0.0)
            for row in own
            if row["case_id"] in common_valid
        ]
        summaries.append(
            {
                "variant_id": variant,
                "complete_ids": [r["case_id"] for r in own if r["complete"] is True],
                "answerable_count": sum(
                    cases[r["case_id"]]["answerability"] == "answerable" for r in own
                ),
                "partial_count": sum(
                    cases[r["case_id"]]["answerability"] == "partial" for r in own
                ),
                "required_evidence_case_count": sum(r["required"] > 0 for r in own),
                "included_facts": sum(r["included"] for r in own),
                "required_facts": sum(r["required"] for r in own),
                "precision": mean(precision) if precision else None,
                "common_precision_cases": sorted(common_valid),
                "mean_chars": mean(r["body_chars"] for r in own),
                "mean_chunks": mean(r["selected_chunks"] for r in own),
                "mean_duplicate_source_chars": mean(
                    r["duplicate_source_chars"] for r in own
                ),
                "unjudged": sum(r["unjudged_count"] for r in own),
                "required_evidence_empty": [
                    r["case_id"]
                    for r in own
                    if r["required"] and not r["selected_chunks"]
                ],
            }
        )
    rankings = []
    for ranking in search["rankings"]:
        cid = ranking["case_id"]
        for k in (5, 8, 10, 12, 20, 40):
            rankings.append(
                {
                    "case_id": cid,
                    "ranking_id": ranking["ranking_id"],
                    "k": k,
                    **rank_metrics(
                        [r["chunk_id"] for r in ranking["items"][:k]],
                        grades[cid],
                        pools[cid],
                        k,
                    ),
                }
            )
    return {
        "summaries": summaries,
        "rows": rows,
        "rankings": rankings,
        "selection_status": "pending_runtime_and_confirmation",
        "preliminary_quality_order_without_latency": quality_order(summaries)
        if not any(r["unjudged"] for r in summaries)
        else None,
    }


def load_verified_inputs(search_path, packet_path, qrels_path, judgments_path):
    """Bind aggregation to the exact frozen inputs used by the model run."""
    search = json.loads(search_path.read_bytes())
    for path, field in (
        (qrels_path, "qrels_sha256"),
        (packet_path, "relevance_packet_sha256"),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != search.get(field):
            raise ValueError(f"SHA mismatch for {field}")
    return (
        search,
        *(
            json.loads(path.read_bytes())
            for path in (packet_path, qrels_path, judgments_path)
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("search", "packet", "qrels", "judgments", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve existing aggregate; choose a new output path")
    result = aggregate(
        *load_verified_inputs(args.search, args.packet, args.qrels, args.judgments)
    )
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
