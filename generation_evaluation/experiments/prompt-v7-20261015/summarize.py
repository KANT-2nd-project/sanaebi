"""Join masked AI judgments to preserved responses without changing their scores."""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def summarize(records, mapping, judgments):
    by_slot = {row["slot"]: row for row in records}
    if len(by_slot) != len(records):
        raise ValueError("Duplicate response slots")
    if len(judgments) != len(mapping):
        raise ValueError("Every masked response needs one judgment")
    seen = set()
    joined = []
    groups = defaultdict(list)
    for judgment in judgments:
        identifier = judgment["anonymous_id"]
        if identifier in seen or identifier not in mapping:
            raise ValueError("Duplicate or unknown anonymous judgment")
        seen.add(identifier)
        identity = mapping[identifier]
        record = by_slot[identity["slot"]]
        checks = judgment["required_checks"]
        if any(c["status"] != "met" for c in checks) and judgment["content"] == "pass":
            raise ValueError("Passing content cannot have missing or uncertain claims")
        result = record.get("result") or {}
        row = {**identity, **judgment}
        row["api_format_pass"] = result.get("status") == "completed"
        if not row["api_format_pass"] and row["content"] == "pass":
            raise ValueError("Generation failure cannot pass content")
        joined.append(row)
        groups[identity["profile"]].append((record, row))
    summaries = {}
    for profile, pairs in groups.items():
        per_case = defaultdict(list)
        for record, judgment in pairs:
            per_case[record["case_id"]].append(judgment)
        summaries[profile] = {
            "responses": len(pairs),
            "content_pass": sum(j["content"] == "pass" for _, j in pairs),
            "content_uncertain": sum(j["content"] == "uncertain" for _, j in pairs),
            "all_observed_repetitions_pass_cases": sum(
                all(j["content"] == "pass" for j in case) for case in per_case.values()
            ),
            "observed_repetitions_by_case": {k: len(v) for k, v in per_case.items()},
            "major_error_responses": sum(
                j["major_grounded_or_authority_error"] for _, j in pairs
            ),
            "missing_required_claims": sum(
                c["status"] == "missing" for _, j in pairs for c in j["required_checks"]
            ),
            "uncertain_required_claims": sum(
                c["status"] == "uncertain"
                for _, j in pairs
                for c in j["required_checks"]
            ),
            "common_readability_pass": sum(
                j["common_readability"] == "pass" for _, j in pairs
            ),
            "structure_pass": sum(j["structure"] == "pass" for _, j in pairs),
            "api_format_failures": sum(not j["api_format_pass"] for _, j in pairs),
            "unnecessary_guidance": sum(j["unnecessary_guidance"] for _, j in pairs),
            "unnecessary_formatting": sum(
                j["unnecessary_formatting"] for _, j in pairs
            ),
            "conditional_sequence_errors": sum(
                j["conditional_sequence_error"] for _, j in pairs
            ),
            "latency_median_seconds": statistics.median(
                r["elapsed_seconds"] for r, _ in pairs
            ),
            "latency_max_seconds": max(r["elapsed_seconds"] for r, _ in pairs),
            "input_tokens_known": sum(
                (r.get("result") or {}).get("input_tokens") or 0 for r, _ in pairs
            ),
            "output_tokens_known": sum(
                (r.get("result") or {}).get("output_tokens") or 0 for r, _ in pairs
            ),
            "usage_unknown_responses": sum(not r["usage_known"] for r, _ in pairs),
            "cost_estimate_usd": sum(r["cost_estimate_usd"] for r, _ in pairs),
        }
    return {"profiles": summaries, "responses": joined}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.responses.read_text().splitlines()]
    judgments = json.loads(args.judgments.read_text())
    result = summarize(
        records, json.loads(args.mapping.read_text()), judgments["responses"]
    )
    with args.output.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
