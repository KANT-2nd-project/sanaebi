"""Deterministic aggregation for blinded generation-model selection runs."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any

from generation_evaluation.selection_report_validation import (
    DIMENSION_IDS,
    DIMENSION_STATUSES,
    ISSUE_KINDS,
    SEVERITIES,
    VERDICTS,
    _join_key,
    _record_derived,
    _validate_judgment,
    _validate_record_judgment_consistency,
)

__all__ = [
    "DIMENSION_IDS",
    "DIMENSION_STATUSES",
    "ISSUE_KINDS",
    "SEVERITIES",
    "VERDICTS",
    "summarize",
]


def summarize(
    records: list[dict[str, Any]], judgments: list[dict[str, Any]], final: bool = False
) -> dict[str, Any]:
    """Join attempts to blinded judgments and compute deterministic candidate ranks.

    Every attempt, including failed calls and timeouts, must have one judgment;
    no run is removed from any denominator.
    """
    if not isinstance(records, list) or not isinstance(judgments, list):
        raise TypeError("records와 judgments는 객체 목록이어야 합니다.")
    if not isinstance(final, bool):
        raise TypeError("final은 bool이어야 합니다.")

    record_map: dict[tuple[str, int, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for index, record in enumerate(records):
        key = _join_key(record, index, "records")
        if key in record_map:
            raise ValueError(f"중복 실행 기록이 있습니다: {key}")
        derived = _record_derived(record, index)
        record_map[key] = (record, derived)

    judgment_map: dict[tuple[str, int, str], dict[str, Any]] = {}
    for index, judgment in enumerate(judgments):
        if not isinstance(judgment, dict):
            raise TypeError(f"judgments[{index}]는 객체여야 합니다.")
        key = _join_key(judgment, index, "judgments")
        if key in judgment_map:
            raise ValueError(f"중복 판정이 있습니다: {key}")
        judgment_map[key] = _validate_judgment(judgment, index)

    missing = set(record_map) - set(judgment_map)
    extra = set(judgment_map) - set(record_map)
    if missing or extra:
        raise ValueError(
            f"실행 기록과 판정이 일치하지 않습니다. 누락={sorted(missing)}, 추가={sorted(extra)}"
        )
    if not record_map:
        raise ValueError("집계할 실행 기록이 없습니다.")
    for key, (record, _) in record_map.items():
        _validate_record_judgment_consistency(record, judgment_map[key], key)

    candidate_ids = sorted({key[2] for key in record_map})
    case_sets: dict[str, set[str]] = {}
    candidate_rows: dict[
        str,
        list[
            tuple[tuple[str, int, str], dict[str, Any], dict[str, Any], dict[str, Any]]
        ],
    ] = defaultdict(list)
    for key, (record, derived) in record_map.items():
        candidate_rows[key[2]].append((key, record, derived, judgment_map[key]))
    for candidate_id, rows in candidate_rows.items():
        case_sets[candidate_id] = {key[0] for key, *_ in rows}

    if final:
        expected_cases = set(next(iter(case_sets.values())))
        if len(expected_cases) != 20:
            raise ValueError("최종 평가에는 정확히 20개 문항이 필요합니다.")
        if any(cases != expected_cases for cases in case_sets.values()):
            raise ValueError("최종 평가 후보마다 같은 20개 문항을 사용해야 합니다.")
        for candidate_id, rows in candidate_rows.items():
            repeats_by_case: dict[str, set[int]] = defaultdict(set)
            for key, *_ in rows:
                repeats_by_case[key[0]].add(key[1])
            if any(repeats != {1, 2} for repeats in repeats_by_case.values()):
                raise ValueError(
                    f"최종 평가 후보 {candidate_id}는 각 문항을 repeat 1, 2로 실행해야 합니다."
                )

    candidate_summaries: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        rows = candidate_rows[candidate_id]
        verdict_counts = Counter(row[3]["verdict"] for row in rows)
        issue_counts: Counter[str] = Counter()
        issue_response_keys: dict[str, set[tuple[str, int, str]]] = defaultdict(set)
        critical_cases: set[str] = set()
        critical_case_keys: set[tuple[str, int, str]] = set()
        format_fail_keys: set[tuple[str, int, str]] = set()
        dimensions: dict[str, Counter[str]] = {
            dimension_id: Counter() for dimension_id in DIMENSION_IDS
        }
        verdicts_by_case: dict[str, dict[int, str]] = defaultdict(dict)
        latencies: list[float] = []
        cost_total = 0.0
        cost_unknown = 0
        token_totals = {"input": 0, "output": 0, "reasoning": 0}
        token_unknown = {"input": 0, "output": 0, "reasoning": 0}
        generation_failure_count = 0
        timeout_count = 0
        result_status_counts: Counter[str] = Counter()

        for key, record, derived, judgment in rows:
            case_id, repeat, _ = key
            verdicts_by_case[case_id][repeat] = judgment["verdict"]
            latencies.append(derived["elapsed"])
            cost_total += derived["cost_total"]
            cost_unknown += derived["cost_unknown"]
            generation_failure_count += int(derived["generation_failed"])
            timeout_count += int(derived["timed_out"])
            if derived["status"] is not None:
                result_status_counts[derived["status"]] += 1
            for name in token_totals:
                token_totals[name] += derived["token_totals"][name]
                token_unknown[name] += derived["token_unknown"][name]
            if judgment["severity"] == "critical":
                critical_cases.add(case_id)
                critical_case_keys.add(key)
            for issue in judgment["issues"]:
                kind = issue["kind"]
                issue_counts[kind] += 1
                issue_response_keys[kind].add(key)
                if kind == "critical_error":
                    critical_cases.add(case_id)
                    critical_case_keys.add(key)
                if kind == "format_error":
                    format_fail_keys.add(key)
            for dimension_id, value in judgment["dimensions"].items():
                dimensions[dimension_id][value["status"]] += 1

        stable_both_pass_cases = sum(
            set(verdicts) == {1, 2}
            and verdicts.get(1) == "pass"
            and verdicts.get(2) == "pass"
            for verdicts in verdicts_by_case.values()
        )
        disagreement_cases = sum(
            len(set(verdicts.values())) > 1 for verdicts in verdicts_by_case.values()
        )
        # A malformed JSON result is a format failure even if the judge did not
        # add a duplicate format_error issue.
        for key, record, derived, _ in rows:
            if derived["status"] == "parse_error":
                format_fail_keys.add(key)
        format_fail_count = len(format_fail_keys)
        median_seconds = float(median(latencies))
        max_seconds = max(latencies)
        unknown_cost_flag = int(cost_unknown > 0)
        rank_key: list[float | int] = [
            len(critical_cases),
            -stable_both_pass_cases,
            -verdict_counts["pass"],
            verdict_counts["uncertain"],
            median_seconds,
            unknown_cost_flag,
            cost_total,
        ]
        candidate_summaries.append(
            {
                "candidate_id": candidate_id,
                "case_count": len(case_sets[candidate_id]),
                "response_count": len(rows),
                "verdict_counts": {
                    verdict: verdict_counts[verdict] for verdict in VERDICTS
                },
                "pass_count": verdict_counts["pass"],
                "partial_count": verdict_counts["partial"],
                "fail_count": verdict_counts["fail"],
                "uncertain_count": verdict_counts["uncertain"],
                "critical_case_count": len(critical_cases),
                "critical_response_count": len(critical_case_keys),
                "stable_both_pass_case_count": stable_both_pass_cases,
                "repeat_disagreement_case_count": disagreement_cases,
                "format_fail_count": format_fail_count,
                "median_elapsed_seconds": median_seconds,
                "max_elapsed_seconds": max_seconds,
                "total_input_tokens": token_totals["input"],
                "total_output_tokens": token_totals["output"],
                "total_reasoning_tokens": token_totals["reasoning"],
                "unknown_input_token_calls": token_unknown["input"],
                "unknown_output_token_calls": token_unknown["output"],
                "unknown_reasoning_token_calls": token_unknown["reasoning"],
                "estimated_cost_dollars": cost_total,
                "estimated_cost_unknown_count": cost_unknown,
                "issue_counts": {kind: issue_counts[kind] for kind in ISSUE_KINDS},
                "issue_response_counts": {
                    kind: len(issue_response_keys[kind]) for kind in ISSUE_KINDS
                },
                "dimension_counts": {
                    dimension_id: {
                        status: dimensions[dimension_id][status]
                        for status in DIMENSION_STATUSES
                    }
                    for dimension_id in DIMENSION_IDS
                },
                "generation_failure_count": generation_failure_count,
                "timeout_count": timeout_count,
                "result_status_counts": dict(sorted(result_status_counts.items())),
                "default_promotable": final
                and len(candidate_ids) >= 2
                and stable_both_pass_cases >= 18
                and not critical_cases,
                "rank_key": rank_key,
            }
        )

    candidate_summaries.sort(key=lambda item: (item["rank_key"], item["candidate_id"]))
    for rank, summary in enumerate(candidate_summaries, start=1):
        summary["rank"] = rank

    return {
        "denominator": {
            "attempt_count": len(record_map),
            "judgment_count": len(judgment_map),
            "candidate_count": len(candidate_ids),
            "case_count": len({key[0] for key in record_map}),
            "all_attempts_retained": True,
        },
        "final_evaluation": final,
        "candidates": candidate_summaries,
    }
