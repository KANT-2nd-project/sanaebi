"""Schema validation and derived values for selection reports."""

from __future__ import annotations

from math import isfinite
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
