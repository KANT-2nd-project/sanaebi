"""Deterministic aggregation for blinded generation-model selection runs."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from statistics import median
from typing import Any

VERDICTS = ("pass", "partial", "fail", "uncertain")
SEVERITIES = ("critical", "material", "omission", "style", "none")
ISSUE_KINDS = (
    "critical_error",
    "material_error",
    "required_omission",
    "over_abstention",
    "format_error",
    "style_relevance",
)
DIMENSION_IDS = (
    "format",
    "grounding",
    "scope_conditions",
    "completeness",
    "abstention",
    "action_boundary",
    "style",
    "relevance",
)
DIMENSION_STATUSES = ("pass", "fail", "na", "uncertain")


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}는 비어 있지 않은 문자열이어야 합니다.")
    return value


def _nonnegative_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field}는 유한한 0 이상의 숫자여야 합니다.")
    if not isfinite(value) or value < 0:
        raise ValueError(f"{field}는 유한한 0 이상의 숫자여야 합니다.")
    return float(value)


def _join_key(
    record: dict[str, Any], index: int, collection: str
) -> tuple[str, int, str]:
    if not isinstance(record, dict):
        raise TypeError(f"{collection}[{index}]는 객체여야 합니다.")
    case_id = _nonempty_string(record.get("case_id"), f"{collection}[{index}].case_id")
    candidate_id = _nonempty_string(
        record.get("candidate_id"), f"{collection}[{index}].candidate_id"
    )
    repeat = record.get("repeat")
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        raise ValueError(f"{collection}[{index}].repeat는 1 이상의 정수여야 합니다.")
    return case_id, repeat, candidate_id


def _validate_result(result: Any, index: int) -> None:
    # A None result is a retained failed/timeout attempt and remains in the denominator.
    if result is None:
        return
    if not isinstance(result, dict):
        raise TypeError(f"records[{index}].result는 객체 또는 None이어야 합니다.")
    status = result.get("status")
    if status is not None and not isinstance(status, str):
        raise TypeError(f"records[{index}].result.status는 문자열이어야 합니다.")


def _validate_call(call: Any, record_index: int, call_index: int) -> dict[str, Any]:
    if not isinstance(call, dict):
        raise TypeError(
            f"records[{record_index}].calls[{call_index}]는 객체여야 합니다."
        )
    estimated = call.get("estimated_dollars")
    if estimated is not None:
        _nonnegative_number(
            estimated, f"records[{record_index}].calls[{call_index}].estimated_dollars"
        )
    for field in ("usage", "metadata"):
        if call.get(field) is not None and not isinstance(call[field], dict):
            raise TypeError(
                f"records[{record_index}].calls[{call_index}].{field}는 객체 또는 None이어야 합니다."
            )
    return call


def _usage_candidates(
    usage: dict[str, Any], metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates = [usage, metadata]
    for parent in (usage, metadata):
        for key in ("token_usage", "usage", "usage_metadata"):
            nested = parent.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
    return candidates


def _token_value(
    candidates: list[dict[str, Any]], names: tuple[str, ...]
) -> int | None:
    for candidate in candidates:
        for name in names:
            value = candidate.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return None


def _reasoning_tokens(candidates: list[dict[str, Any]]) -> int | None:
    for candidate in candidates:
        for key in (
            "completion_tokens_details",
            "output_tokens_details",
            "output_token_details",
        ):
            details = candidate.get(key)
            if not isinstance(details, dict):
                continue
            for name in ("reasoning_tokens", "reasoning"):
                value = details.get(name)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    return value
    return None


def _record_derived(record: dict[str, Any], index: int) -> dict[str, Any]:
    elapsed = _nonnegative_number(record.get("elapsed_seconds"), "elapsed_seconds")
    calls_value = record.get("calls")
    if not isinstance(calls_value, list):
        raise TypeError("record.calls는 객체 목록이어야 합니다.")
    calls = [
        _validate_call(call, index, call_index)
        for call_index, call in enumerate(calls_value)
    ]
    if "result" not in record:
        raise ValueError(f"records[{index}].result가 없습니다.")
    _validate_result(record.get("result"), index)

    totals = {"input": 0, "output": 0, "reasoning": 0}
    unknown = {"input": 0, "output": 0, "reasoning": 0}
    cost_total = 0.0
    cost_unknown = 0
    for call in calls:
        estimated = call.get("estimated_dollars")
        if estimated is None:
            cost_unknown += 1
        else:
            cost_total += float(estimated)
        usage = call.get("usage") or {}
        metadata = call.get("metadata") or {}
        candidates = _usage_candidates(usage, metadata)
        token_values = {
            "input": _token_value(candidates, ("prompt_tokens", "input_tokens")),
            "output": _token_value(candidates, ("completion_tokens", "output_tokens")),
            "reasoning": _reasoning_tokens(candidates),
        }
        for name, value in token_values.items():
            if value is None:
                unknown[name] += 1
            else:
                totals[name] += value

    result = record.get("result")
    status = result.get("status") if isinstance(result, dict) else None
    error_type = record.get("error_type")
    generation_failed = (
        result is None or status != "completed" or error_type is not None
    )
    timed_out = status == "timeout" or (
        isinstance(error_type, str) and "timeout" in error_type.lower()
    )
    return {
        "elapsed": elapsed,
        "calls": calls,
        "token_totals": totals,
        "token_unknown": unknown,
        "cost_total": cost_total,
        "cost_unknown": cost_unknown,
        "status": status,
        "generation_failed": generation_failed,
        "timed_out": timed_out,
    }


def _validate_judgment(judgment: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(judgment, dict):
        raise TypeError(f"judgments[{index}]는 객체여야 합니다.")
    verdict = judgment.get("verdict")
    severity = judgment.get("severity")
    if verdict not in VERDICTS:
        raise ValueError(f"judgments[{index}].verdict는 {VERDICTS} 중 하나여야 합니다.")
    if severity not in SEVERITIES:
        raise ValueError(
            f"judgments[{index}].severity는 {SEVERITIES} 중 하나여야 합니다."
        )
    issues = judgment.get("issues")
    if not isinstance(issues, list):
        raise TypeError(f"judgments[{index}].issues는 객체 목록이어야 합니다.")
    for issue_index, issue in enumerate(issues):
        if not isinstance(issue, dict) or issue.get("kind") not in ISSUE_KINDS:
            raise ValueError(
                f"judgments[{index}].issues[{issue_index}].kind는 {ISSUE_KINDS} 중 하나여야 합니다."
            )

    dimensions = judgment.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSION_IDS):
        raise ValueError(
            f"judgments[{index}].dimensions는 지정된 8개 차원을 모두 포함해야 합니다."
        )
    for dimension_id, value in dimensions.items():
        if not isinstance(value, dict):
            raise TypeError(
                f"judgments[{index}].dimensions.{dimension_id}는 객체여야 합니다."
            )
        if value.get("status") not in DIMENSION_STATUSES:
            raise ValueError(
                f"judgments[{index}].dimensions.{dimension_id}.status는 {DIMENSION_STATUSES} 중 하나여야 합니다."
            )
        for field in ("evidence", "reason"):
            if not isinstance(value.get(field), str):
                raise TypeError(
                    f"judgments[{index}].dimensions.{dimension_id}.{field}는 문자열이어야 합니다."
                )
    return judgment


def _validate_record_judgment_consistency(
    record: dict[str, Any], judgment: dict[str, Any], key: tuple[str, int, str]
) -> None:
    verdict = judgment["verdict"]
    result = record["result"]
    result_status = result.get("status") if isinstance(result, dict) else None
    format_status = judgment["dimensions"]["format"]["status"]

    record_format_pass = record.get("format_pass")
    judgment_format_pass = judgment.get("format_pass")
    for location, value in (
        ("record.format_pass", record_format_pass),
        ("judgment.format_pass", judgment_format_pass),
    ):
        if value is not None and not isinstance(value, bool):
            raise TypeError(f"{location}는 bool 또는 None이어야 합니다: {key}")
    if (
        record_format_pass is not None
        and judgment_format_pass is not None
        and record_format_pass != judgment_format_pass
    ):
        raise ValueError(f"record와 judgment의 format_pass가 다릅니다: {key}")
    format_pass = (
        record_format_pass if record_format_pass is not None else judgment_format_pass
    )

    if verdict in ("pass", "partial"):
        if result is None or result_status != "completed":
            raise ValueError(
                f"실패 또는 완료되지 않은 실행을 {verdict}로 판정할 수 없습니다: {key}"
            )
        if format_pass is False:
            raise ValueError(
                f"format_pass=false인 실행을 {verdict}로 판정할 수 없습니다: {key}"
            )
        if format_status == "fail":
            raise ValueError(
                f"format 차원이 fail인 실행을 {verdict}로 판정할 수 없습니다: {key}"
            )
    if format_pass is False and format_status == "pass":
        raise ValueError(f"format_pass=false와 format 차원 pass가 충돌합니다: {key}")


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
