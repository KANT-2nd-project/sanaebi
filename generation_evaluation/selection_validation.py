"""Input validation for current selection experiments."""

import hashlib
import json


def _validate_cases(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases는 하나 이상의 평가 문항 목록이어야 합니다.")
    case_ids = []
    for case in cases:
        if not isinstance(case, dict):
            raise TypeError("각 평가 문항은 JSON 객체여야 합니다.")
        case_id = case.get("case_id")
        question = case.get("question")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("모든 평가 문항에는 비어 있지 않은 case_id가 필요합니다.")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{case_id}의 question이 비어 있습니다.")
        case_ids.append(case_id)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Duplicate case_id")
    return set(case_ids)


def _validate_rubric(path, cases, *, required):
    if path is None:
        if required:
            raise ValueError("이 후보에는 --rubric이 필요합니다.")
        return None

    try:
        raw = path.read_bytes()
        rubric = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("rubric 파일을 읽을 수 없거나 JSON 형식이 아닙니다.") from exc
    if not isinstance(rubric, dict) or not rubric:
        raise ValueError("rubric은 비어 있지 않은 JSON 객체여야 합니다.")
    if "response_contract" in rubric and not isinstance(
        rubric["response_contract"], dict
    ):
        raise ValueError("rubric.response_contract는 JSON 객체여야 합니다.")
    if "dimensions" in rubric and not isinstance(rubric["dimensions"], list):
        raise ValueError("rubric.dimensions는 목록이어야 합니다.")

    requested_ids = {case["case_id"] for case in cases}
    declared_ids = rubric.get("case_ids")
    rubric_cases = rubric.get("cases")
    if declared_ids is None:
        if isinstance(rubric_cases, dict):
            declared_ids = list(rubric_cases)
        elif isinstance(rubric_cases, list):
            declared_ids = [
                item["case_id"]
                for item in rubric_cases
                if isinstance(item, dict) and isinstance(item.get("case_id"), str)
            ]
    if declared_ids is not None:
        if (
            not isinstance(declared_ids, list)
            or any(
                not isinstance(item, str) or not item.strip() for item in declared_ids
            )
            or len(declared_ids) != len(set(declared_ids))
        ):
            raise ValueError("rubric.case_ids는 중복 없는 문자열 목록이어야 합니다.")
        missing_ids = requested_ids - set(declared_ids)
        if missing_ids:
            raise ValueError(
                "rubric에 평가 문항이 없습니다: " + ", ".join(sorted(missing_ids))
            )
    elif required:
        raise ValueError("후속 실험 rubric에는 case_ids가 필요합니다.")

    if rubric_cases is not None:
        if isinstance(rubric_cases, list):
            rubric_cases = {
                item.get("case_id"): item
                for item in rubric_cases
                if isinstance(item, dict) and isinstance(item.get("case_id"), str)
            }
        if not isinstance(rubric_cases, dict):
            raise ValueError("rubric.cases는 case_id를 키로 가진 객체여야 합니다.")
        if declared_ids is not None and set(rubric_cases) - set(declared_ids):
            raise ValueError("rubric.cases에 선언되지 않은 case_id가 있습니다.")
        for case in cases:
            details = rubric_cases.get(case["case_id"])
            if details is None:
                continue
            if not isinstance(details, dict):
                raise TypeError(
                    f"rubric.cases.{case['case_id']}는 JSON 객체여야 합니다."
                )
            if (
                "evidence" in details
                and "evidence" in case
                and details["evidence"] != case["evidence"]
            ):
                raise ValueError(
                    f"rubric와 평가 문항의 근거가 다릅니다: {case['case_id']}"
                )
    return hashlib.sha256(raw).hexdigest()
