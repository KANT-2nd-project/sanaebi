"""Join independently blinded judgments to all attempts without cherry-picking."""

import argparse
import json
import math
import statistics
from pathlib import Path


def attempt_cost(attempt, ledger):
    cost = attempt.get("actual_cost_usd")
    if cost is not None:
        return cost
    settled = ledger.get("reservations", {}).get(attempt.get("request_id"), {})
    settled_cost = settled.get("actual_dollars")
    if (
        attempt.get("status") in {"provider_rejected", "retryable_provider_error"}
        and settled.get("status") == "settled"
        and isinstance(settled_cost, (int, float))
        and not isinstance(settled_cost, bool)
        and settled_cost == 0
    ):
        return 0.0
    raise ValueError("Unknown attempt cost must not be treated as zero")


def summarize(run_root, grade_paths, output, ledger_path=None):
    if output.exists():
        raise ValueError("Preserve existing summary")
    schedule = json.loads((run_root / "schedule.json").read_text())
    mapping = json.loads((run_root / "private/blind-map.json").read_text())
    grades = {}
    for path in grade_paths:
        data = json.loads(path.read_text())
        if data.get("human_review") is not False or not data.get("judge"):
            raise ValueError("Expected attributed AI judgments")
        for row in data["answers"]:
            for a in row["attempts"]:
                key = (
                    row["case_id"],
                    row["blind_variant"],
                    row["repeat"],
                    a["attempt"],
                )
                if key in grades:
                    raise ValueError("Duplicate judgment")
                grades[key] = a
    ledger = json.loads(ledger_path.read_text()) if ledger_path else {}
    rows = []
    for item in schedule:
        slot = json.loads((run_root / "slots" / f"{item['slot_id']}.json").read_text())
        blind = mapping[item["case_id"]][item["variant_id"]]
        attempts = []
        numbers = slot["attempts"] or [0]
        for number in numbers:
            key = (item["case_id"], blind, item["repeat"], number)
            if key not in grades:
                raise ValueError(f"Missing judgment: {key}")
            grade = grades.pop(key)
            if number:
                actual = json.loads(
                    (
                        run_root
                        / "attempts"
                        / f"{item['slot_id']}-attempt-{number}.json"
                    ).read_text()
                )
            else:
                if slot["status"] != "empty_context":
                    raise ValueError("Unrun is not empty context")
                actual = {
                    "status": "system_empty_context",
                    "usage": {},
                    "actual_cost_usd": 0,
                    "elapsed_seconds": 0,
                }
            attempts.append(
                {
                    "attempt": number,
                    "status": actual["status"],
                    "grade": grade,
                    "usage": actual.get("usage", {}),
                    "actual_cost_usd": attempt_cost(actual, ledger),
                    "elapsed_seconds": actual.get("elapsed_seconds"),
                }
            )
        rows.append(
            {
                "case_id": item["case_id"],
                "variant_id": item["variant_id"],
                "repeat": item["repeat"],
                "status": slot["status"],
                "attempts": attempts,
            }
        )
    if grades:
        raise ValueError("Unexpected judgment")
    summaries = []
    for variant in dict.fromkeys(r["variant_id"] for r in rows):
        chosen = [r for r in rows if r["variant_id"] == variant]
        api = [r for r in chosen if r["attempts"][0]["attempt"]]
        finals = [r["attempts"][-1]["grade"] for r in chosen]
        first = [r["attempts"][0]["grade"] for r in chosen]
        attempts = [a for r in api for a in r["attempts"]]
        retried = [r for r in api if len(r["attempts"]) > 1]
        slot_seconds = [
            sum(a["elapsed_seconds"] or 0 for a in r["attempts"]) for r in chosen
        ]
        summaries.append(
            {
                "variant_id": variant,
                "scheduled_slots": len(chosen),
                "api_slots": len(api),
                "provider_attempts": len(attempts),
                "empty_context_slots": len(chosen) - len(api),
                "first_format_success": sum(
                    r["attempts"][0]["status"] == "completed" for r in api
                ),
                "retries": len(retried),
                "retry_recovered": sum(r["status"] == "completed" for r in retried),
                "final_format_success": sum(r["status"] == "completed" for r in api),
                "first_content_complete": sum(g["content_complete"] for g in first),
                "final_content_complete": sum(g["content_complete"] for g in finals),
                "final_delivered_complete": sum(
                    r["status"] in ["completed", "empty_context"]
                    and r["attempts"][-1]["grade"]["content_complete"]
                    for r in chosen
                ),
                "first_major_errors": sum(g["major_error"] for g in first),
                "final_major_errors": sum(g["major_error"] for g in finals),
                "final_unsupported_assertions": sum(
                    g["unsupported_assertion"] for g in finals
                ),
                "final_missing_facts": sum(len(g["missing_claims"]) for g in finals),
                "estimated_cost_usd": sum(a["actual_cost_usd"] for a in attempts),
                "input_tokens": sum(
                    a["usage"].get("input_tokens", 0) for a in attempts
                ),
                "output_tokens": sum(
                    a["usage"].get("output_tokens", 0) for a in attempts
                ),
                "slot_latency_median_seconds": statistics.median(slot_seconds),
                "slot_latency_p95_seconds": sorted(slot_seconds)[
                    math.ceil(len(slot_seconds) * 0.95) - 1
                ],
                "request_latency_median_seconds": statistics.median(
                    a["elapsed_seconds"] for a in attempts
                )
                if attempts
                else None,
            }
        )
    payload = {"human_review": False, "summary": summaries, "rows": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--grades", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    summarize(args.run_root, args.grades, args.output, args.ledger)
