"""Execute frozen RAG parameter answer comparisons with bounded retries.

Input prompts are prepared and reviewed before execution. This module sends the
exact role-separated prompt through the existing managed provider and generation
JSON parser. It does not build prompts or change the server's routing policy.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import random
import re
import secrets
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIStatusError, AuthenticationError, RateLimitError

from generation.profiles import build_profile_prompt
from generation.providers import build_managed_model_call, to_messages
from generation.service import generate
from generation.types import GenerationPrompt, GenerationStatus, ModelResponse
from generation_evaluation.budget import (
    BudgetExceeded,
    BudgetLedger,
    actual_cost,
    reserve_cost,
)
from retrieval.experiments import answers as paired_answers

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
MAX_PLANNED_CALLS = 448
MAX_API_CALLS = 896
PHASE_CASE_COUNTS = {"development": 48, "confirmation": 40, "quick_context": 12}
PHASE_REPEATS = {"development": 2, "confirmation": 2, "quick_context": 1}
PHASE_VARIANT_COUNTS = {
    "development": (1, 3),
    "confirmation": (2, 2),
    "quick_context": (3, 3),
}
PHASE_PLANNED_CAPS = {"development": 288, "confirmation": 160, "quick_context": 36}
PHASE_MAX_API_CALLS = {"development": 896, "confirmation": 896, "quick_context": 72}
RETRYABLE_PROVIDER_ERRORS = (RateLimitError,)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FIXED_IDENTIFIERS = {
    "provider": "openai",
    "model_name": "gpt-6-luna",
    "prompt_profile": "examples_answer_scope_v5",
    "reasoning_effort": "xhigh",
    "max_output_tokens": 16_384,
    "output_mode": "prompt_json",
}
EXECUTION_MARKER = "execution.started.json"


class CalibrationError(RuntimeError):
    """The frozen inputs or execution environment do not meet the contract."""


class CalibrationStopped(RuntimeError):
    """A run stopped safely after a provider, accounting, or budget event."""


@dataclass(frozen=True)
class ValidatedInputs:
    raw: dict[str, Any]
    phase: str
    identifiers: dict[str, Any]
    cases: tuple[dict[str, Any], ...]
    variant_ids: tuple[str, ...]
    planned_calls: int
    max_attempts: int
    max_api_calls: int
    sha256: str


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    )
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"입력 파일을 읽을 수 없습니다: {path.name}") from exc


def validate_inputs(
    value: Any, *, root: Path = ROOT, runtime_config: dict[str, Any] | None = None
) -> ValidatedInputs:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise CalibrationError("inputs schema_version은 1이어야 합니다.")
    phase = value.get("phase")
    if phase not in PHASE_CASE_COUNTS:
        raise CalibrationError(
            "phase는 development, confirmation 또는 quick_context여야 합니다."
        )
    repeats = PHASE_REPEATS[phase]
    if value.get("repeats") != repeats:
        raise CalibrationError(f"{phase} phase는 정확히 {repeats}회 반복해야 합니다.")

    identifiers = value.get("identifiers")
    if not isinstance(identifiers, dict):
        raise CalibrationError("frozen identifiers 객체가 필요합니다.")
    if any(
        identifiers.get(key) != expected for key, expected in _FIXED_IDENTIFIERS.items()
    ):
        raise CalibrationError("Luna·v5·xhigh·16,384 고정 설정이 일치하지 않습니다.")
    if runtime_config is None:
        runtime_config = asdict(paired_answers._runtime_settings(root).config)
    if identifiers.get("runtime_config") != runtime_config:
        raise CalibrationError(
            "inputs runtime_config가 현재 GenerationConfig 전체 값과 다릅니다."
        )
    try:
        _canonical_bytes(identifiers)
    except (TypeError, ValueError) as exc:
        raise CalibrationError("frozen identifiers는 JSON 값이어야 합니다.") from exc

    cases = value.get("cases")
    expected_count = PHASE_CASE_COUNTS[phase]
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise CalibrationError(f"{phase} 문항은 정확히 {expected_count}개여야 합니다.")

    copied_cases: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    expected_variant_ids: tuple[str, ...] | None = None
    minimum_variants, maximum_variants = PHASE_VARIANT_COUNTS[phase]
    for case in cases:
        if not isinstance(case, dict):
            raise CalibrationError("각 case는 객체여야 합니다.")
        case_id = case.get("case_id")
        question = case.get("question")
        if (
            not isinstance(case_id, str)
            or not _SAFE_ID.fullmatch(case_id)
            or case_id in case_ids
        ):
            raise CalibrationError("case_id가 비어 있거나 중복 또는 안전하지 않습니다.")
        if not isinstance(question, str) or not question.strip():
            raise CalibrationError(f"{case_id}: question이 비어 있습니다.")
        if "answerable" in case and not isinstance(case["answerable"], bool):
            raise CalibrationError(f"{case_id}: answerable은 boolean이어야 합니다.")
        variants = case.get("variants")
        if (
            not isinstance(variants, list)
            or not minimum_variants <= len(variants) <= maximum_variants
        ):
            raise CalibrationError(f"{case_id}: phase에 허용된 variant 수가 아닙니다.")

        variant_ids: list[str] = []
        copied_variants: list[dict[str, Any]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                raise CalibrationError(f"{case_id}: variant는 객체여야 합니다.")
            variant_id = variant.get("variant_id")
            if (
                not isinstance(variant_id, str)
                or not _SAFE_ID.fullmatch(variant_id)
                or variant_id in variant_ids
            ):
                raise CalibrationError(f"{case_id}: variant_id가 잘못됐습니다.")
            variant_ids.append(variant_id)
            prompt_data = variant.get("prompt")
            if prompt_data is None:
                if (
                    variant.get("skipped_reason") != "empty_evidence"
                    or not isinstance(variant.get("fixed_response"), str)
                    or not variant["fixed_response"].strip()
                ):
                    raise CalibrationError(
                        f"{case_id}/{variant_id}: prompt=None은 empty_evidence만 허용합니다."
                    )
                copied_variants.append(
                    {
                        "variant_id": variant_id,
                        "prompt": None,
                        "skipped_reason": "empty_evidence",
                        "fixed_response": variant["fixed_response"],
                    }
                )
                continue
            if (
                not isinstance(prompt_data, dict)
                or not isinstance(prompt_data.get("system"), str)
                or not isinstance(prompt_data.get("user"), str)
                or not prompt_data["user"].strip()
            ):
                raise CalibrationError(
                    f"{case_id}/{variant_id}: prompt는 system/user 문자열이어야 합니다."
                )
            expected_system = build_profile_prompt(
                "prompt contract", [], "examples_answer_scope_v5"
            ).system
            if prompt_data["system"] != expected_system:
                raise CalibrationError(
                    f"{case_id}/{variant_id}: v5 system prompt가 고정값과 다릅니다."
                )
            copied_variants.append(
                {
                    "variant_id": variant_id,
                    "prompt": {
                        "system": prompt_data["system"],
                        "user": prompt_data["user"],
                    },
                }
            )

        current_ids = tuple(variant_ids)
        if expected_variant_ids is None:
            expected_variant_ids = current_ids
        elif current_ids != expected_variant_ids:
            raise CalibrationError("모든 문항의 비교 variant와 순서가 같아야 합니다.")
        case_ids.add(case_id)
        copied_case = {
            key: child for key, child in case.items() if key not in {"variants"}
        }
        copied_case["variants"] = copied_variants
        copied_cases.append(copied_case)

    planned = len(copied_cases) * len(expected_variant_ids or ()) * repeats
    phase_planned_cap = PHASE_PLANNED_CAPS[phase]
    max_api_calls = PHASE_MAX_API_CALLS[phase]
    if planned > phase_planned_cap:
        raise CalibrationError("phase별 정상 호출 계획 상한을 초과했습니다.")
    if phase in {"development", "confirmation"} and planned > MAX_PLANNED_CALLS:
        raise CalibrationError("전체 정상 호출 계획 상한을 초과했습니다.")
    if planned * 2 > max_api_calls:
        raise CalibrationError("재시도를 포함한 전체 호출 상한을 초과했습니다.")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "repeats": repeats,
        "identifiers": identifiers,
        "cases": copied_cases,
    }
    try:
        encoded = _canonical_bytes(normalized)
    except (TypeError, ValueError) as exc:
        raise CalibrationError("inputs는 유효한 JSON 값이어야 합니다.") from exc
    return ValidatedInputs(
        raw=normalized,
        phase=phase,
        identifiers=dict(identifiers),
        cases=tuple(copied_cases),
        variant_ids=expected_variant_ids or (),
        planned_calls=planned,
        max_attempts=planned * 2,
        max_api_calls=max_api_calls,
        sha256=_sha256(encoded),
    )


def build_slots(validated: ValidatedInputs) -> list[dict[str, Any]]:
    slots = []
    for case_index, case in enumerate(validated.cases):
        variants = case["variants"]
        for repeat in range(1, PHASE_REPEATS[validated.phase] + 1):
            offset = (case_index + repeat - 1) % len(variants)
            ordered_variants = variants[offset:] + variants[:offset]
            for variant in ordered_variants:
                slot_id = f"{case['case_id']}--{variant['variant_id']}--r{repeat}"
                slots.append(
                    {
                        "slot_id": slot_id,
                        "case_id": case["case_id"],
                        "question": case["question"],
                        "answerable": case.get("answerable"),
                        "review_context": case.get("review_context"),
                        "variant_id": variant["variant_id"],
                        "repeat": repeat,
                        "prompt": variant["prompt"],
                        "skipped_reason": variant.get("skipped_reason"),
                        "fixed_response": variant.get("fixed_response"),
                    }
                )
    return slots


def is_retryable_provider_error(error: BaseException) -> bool:
    """Only an explicit rate-limit rejection is safe to retry automatically."""
    return isinstance(error, RETRYABLE_PROVIDER_ERRORS)


def _known_rejection(error: BaseException) -> bool:
    if isinstance(error, AuthenticationError):
        return True
    if isinstance(error, APIStatusError):
        return 400 <= error.status_code < 500 and error.status_code not in {408, 429}
    return False


def _plan_file(ledger_path: Path) -> Path:
    return ledger_path.with_name(f"{ledger_path.name}.plans.json")


def _plan_lock_path(ledger_path: Path) -> Path:
    return ledger_path.with_name(f"{ledger_path.name}.plans.lock")


def _uses_shared_phase_ledger(phase: str) -> bool:
    return phase in {"development", "confirmation"}


def _validate_ledger_scope(
    phase: str, ledger_path: Path, plans: dict[str, Any]
) -> None:
    """Keep the quick-context 72-call experiment in a fresh isolated ledger."""
    plan_path = _plan_file(ledger_path)
    phases = plans["phases"]
    if phase == "quick_context":
        if (
            ledger_path.exists()
            or plan_path.exists()
            or phases
            or plans["planned_calls"]
        ):
            raise BudgetExceeded(
                "quick_context는 과거 호출 원장과 분리된 신규 원장이 필요합니다."
            )
        return
    if "quick_context" in phases:
        raise BudgetExceeded(
            "quick_context 전용 원장을 development/confirmation과 공유할 수 없습니다."
        )


def read_registered_plans(ledger_path: Path) -> dict[str, Any]:
    path = _plan_file(ledger_path)
    if not path.exists():
        return {"schema_version": 1, "planned_calls": 0, "phases": {}}
    value = _read_json(path)
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("phases"), dict)
        or not isinstance(value.get("planned_calls"), int)
    ):
        raise CalibrationError("공유 phase 계획 원장이 손상됐습니다.")
    return value


def register_plan(ledger_path: Path, value: Any) -> int:
    validated = validate_inputs(value)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _plan_lock_path(ledger_path)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            plans = read_registered_plans(ledger_path)
            _validate_ledger_scope(validated.phase, ledger_path, plans)
            if validated.phase in plans["phases"]:
                raise BudgetExceeded(
                    "해당 phase 계획은 이미 등록되어 재실행할 수 없습니다."
                )
            total = (
                validated.planned_calls
                if validated.phase == "quick_context"
                else plans["planned_calls"] + validated.planned_calls
            )
            global_cap = (
                PHASE_PLANNED_CAPS["quick_context"]
                if validated.phase == "quick_context"
                else MAX_PLANNED_CALLS
            )
            if total > global_cap:
                raise BudgetExceeded("두 phase의 정상 계획 호출 상한 448을 초과합니다.")
            plans["phases"][validated.phase] = {
                "input_sha256": validated.sha256,
                "planned_calls": validated.planned_calls,
                "max_attempts": validated.max_attempts,
            }
            plans["planned_calls"] = total
            _write_json(_plan_file(ledger_path), plans)
            return total
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _new_ledger(path: Path, *, max_api_calls: int) -> BudgetLedger:
    ledger = BudgetLedger(
        path,
        total_dollars=None,
        dev_dollars=None,
        total_seconds=None,
        dev_seconds=None,
        max_calls=max_api_calls,
    )
    ledger.bind_limits()
    ledger.ensure_identity()
    return ledger


def preflight(
    inputs_path: Path, ledger_path: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    """Estimate planned and retry-ceiling costs without files or provider calls."""
    value = _read_json(inputs_path)
    settings = paired_answers._runtime_settings(root)
    validated = validate_inputs(
        value, root=root, runtime_config=asdict(settings.config)
    )
    plans = read_registered_plans(ledger_path)
    _validate_ledger_scope(validated.phase, ledger_path, plans)
    if validated.phase in plans["phases"]:
        raise BudgetExceeded("해당 phase 계획은 이미 등록되어 재실행할 수 없습니다.")
    projected = plans["planned_calls"] + validated.planned_calls
    planned_cap = (
        PHASE_PLANNED_CAPS["quick_context"]
        if validated.phase == "quick_context"
        else MAX_PLANNED_CALLS
    )
    if projected > planned_cap:
        raise BudgetExceeded("두 phase의 정상 계획 호출 상한 448을 초과합니다.")

    planned_cost = 0.0
    api_slots = 0
    empty_context_slots = 0
    for slot in build_slots(validated):
        if slot["prompt"] is None:
            empty_context_slots += 1
            continue
        api_slots += 1
        prompt = GenerationPrompt(**slot["prompt"])
        planned_cost += reserve_cost(
            to_messages(prompt), settings.config.max_output_tokens
        )

    return {
        "status": "preflight_only",
        "phase": validated.phase,
        "inputs_sha256": validated.sha256,
        "identifiers": validated.identifiers,
        "scheduled_slots": validated.planned_calls,
        "api_slots": api_slots,
        "empty_context_slots": empty_context_slots,
        "normal_provider_calls": api_slots,
        "max_provider_calls_in_phase": min(api_slots * 2, validated.max_api_calls),
        "max_provider_calls_global": validated.max_api_calls,
        "registered_planned_calls": plans["planned_calls"],
        "projected_planned_calls": projected,
        "max_planned_calls_global": planned_cap,
        "ledger_scope": (
            "shared_development_confirmation"
            if _uses_shared_phase_ledger(validated.phase)
            else "isolated_quick_context"
        ),
        "reserved_cost_estimate_usd_normal": round(planned_cost, 8),
        "reserved_cost_estimate_usd_with_all_retries": round(planned_cost * 2, 8),
        "cost_cap_usd": None,
        "cost_method": "generation_evaluation.budget.reserve_cost long-tier conservative estimate",
        "creates_artifacts": False,
        "calls_provider": False,
    }


def _seed_for_domain(seed: str, domain: str) -> int:
    material = f"calibration-blinding-v1:{domain}:{seed}".encode()
    return int.from_bytes(hashlib.sha256(material).digest(), "big")


def _blind_map(validated: ValidatedInputs, seed: str) -> dict[str, dict[str, str]]:
    result = {}
    labels = [chr(ord("A") + index) for index in range(len(validated.variant_ids))]
    rng = random.Random(_seed_for_domain(seed, "variant-labels"))
    for case in validated.cases:
        shuffled = list(labels)
        rng.shuffle(shuffled)
        result[case["case_id"]] = dict(
            zip(validated.variant_ids, shuffled, strict=True)
        )
    return result


def _phase_ledger_name(phase: str) -> str:
    return "final" if phase == "confirmation" else "dev"


def _write_execution(output: Path, summary: dict[str, Any]) -> None:
    _write_json(output / "execution.json", summary)


def _slot_path(output: Path, slot_id: str) -> Path:
    return output / "slots" / f"{slot_id}.json"


def _mark_unstarted(slots: list[dict[str, Any]], start: int, output: Path) -> None:
    for slot in slots[start:]:
        slot_record = {
            "slot_id": slot["slot_id"],
            "case_id": slot["case_id"],
            "variant_id": slot["variant_id"],
            "repeat": slot["repeat"],
            "status": "not_run_after_stop",
            "attempts": [],
            "content": None,
            "generation_status": None,
        }
        _write_json(_slot_path(output, slot["slot_id"]), slot_record)


def _status_for_provider_error(error: BaseException) -> tuple[str, float | None]:
    if is_retryable_provider_error(error) or _known_rejection(error):
        return "provider_rejected", 0.0
    return "provider_error_unknown_cost", None


def execute_calibration(
    inputs_path: Path,
    artifact_root: Path,
    ledger_path: Path,
    env_file: Path,
    *,
    root: Path = ROOT,
    provider_factory=build_managed_model_call,
) -> dict[str, Any]:
    """Execute each frozen variant/repeat slot once, with at most one retry."""
    output = artifact_root.resolve()
    if not output.is_dir():
        raise CalibrationError("artifact-root 디렉터리가 미리 있어야 합니다.")
    marker_path = output / EXECUTION_MARKER
    if marker_path.exists():
        raise CalibrationError("이 artifact-root는 이미 실행을 시작했습니다.")
    if any(output.iterdir()):
        raise CalibrationError("새 artifact-root는 비어 있어야 합니다.")

    input_value = _read_json(inputs_path)
    settings = paired_answers._runtime_settings(root)
    validated = validate_inputs(
        input_value, root=root, runtime_config=asdict(settings.config)
    )
    plans = read_registered_plans(ledger_path)
    _validate_ledger_scope(validated.phase, ledger_path, plans)
    runtime_ids = {
        "provider": settings.config.provider.value,
        "model_name": settings.config.model_name,
        "prompt_profile": settings.prompt_profile,
        "reasoning_effort": settings.config.reasoning_effort,
        "max_output_tokens": settings.config.max_output_tokens,
        "output_mode": settings.config.output_mode.value,
    }
    if any(
        validated.identifiers.get(key) != value for key, value in runtime_ids.items()
    ):
        raise CalibrationError("inputs frozen identifiers가 현재 runtime과 다릅니다.")
    paired_answers._validate_provider_environment(env_file)
    load_dotenv(env_file, override=False)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise CalibrationError("실행 환경에서 API key를 확인할 수 없습니다.")

    slots = build_slots(validated)
    marker = {
        "started_at": datetime.now(UTC).isoformat(),
        "phase": validated.phase,
        "inputs_sha256": validated.sha256,
        "planned_calls": validated.planned_calls,
        "max_attempts": validated.max_attempts,
        "max_api_calls": validated.max_api_calls,
        "status": "running",
    }
    _write_json(marker_path, marker, exclusive=True)
    registered_total = register_plan(ledger_path, input_value)
    ledger = _new_ledger(ledger_path, max_api_calls=validated.max_api_calls)
    (output / "attempts").mkdir(exist_ok=True)
    (output / "slots").mkdir(exist_ok=True)
    (output / "private").mkdir(exist_ok=True)

    blinding_seed = secrets.token_hex(32)
    blind_map = _blind_map(validated, blinding_seed)
    _write_json(output / "inputs.json", validated.raw, exclusive=True)
    _write_json(output / "schedule.json", slots, exclusive=True)
    _write_json(
        output / "private" / "blinding.json",
        {"seed": blinding_seed},
        exclusive=True,
    )
    _write_json(output / "private" / "blind-map.json", blind_map, exclusive=True)
    for slot in slots:
        _write_json(
            _slot_path(output, slot["slot_id"]),
            {
                "slot_id": slot["slot_id"],
                "case_id": slot["case_id"],
                "variant_id": slot["variant_id"],
                "repeat": slot["repeat"],
                "status": "scheduled",
                "attempts": [],
                "content": None,
                "generation_status": None,
            },
            exclusive=True,
        )

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "phase": validated.phase,
        "status": "running",
        "started_at": marker["started_at"],
        "inputs_sha256": validated.sha256,
        "identifiers": validated.identifiers,
        "planned_calls": validated.planned_calls,
        "max_attempts": validated.max_attempts,
        "max_api_calls": validated.max_api_calls,
        "registered_total_planned_calls": registered_total,
        "ledger_identity": ledger.get_identity(),
        "provider_calls": 0,
        "completed_slots": 0,
        "empty_context_slots": 0,
        "stopped_reason": None,
    }
    _write_execution(output, summary)
    provider = None
    stopped_at_index = len(slots)
    phase_name = _phase_ledger_name(validated.phase)
    stop_run = False

    for index, slot in enumerate(slots):
        slot_record = _read_json(_slot_path(output, slot["slot_id"]))
        if slot["prompt"] is None:
            slot_record.update(
                status="empty_context",
                content=slot["fixed_response"],
                response_source="system_empty_context",
                llm_called=False,
            )
            _write_json(_slot_path(output, slot["slot_id"]), slot_record)
            summary["empty_context_slots"] += 1
            _write_execution(output, summary)
            continue

        prompt = GenerationPrompt(**slot["prompt"])
        prompt_sha = paired_answers._prompt_sha(prompt)
        for attempt_number in (1, 2):
            request_id = (
                f"cal-{validated.phase}-{validated.sha256[:12]}-"
                f"{slot['slot_id']}-a{attempt_number}"
            )
            attempt_path = (
                output / "attempts" / f"{slot['slot_id']}-attempt-{attempt_number}.json"
            )
            attempt_record = {
                "slot_id": slot["slot_id"],
                "case_id": slot["case_id"],
                "variant_id": slot["variant_id"],
                "repeat": slot["repeat"],
                "attempt": attempt_number,
                "request_id": request_id,
                "prompt_sha256": prompt_sha,
                "status": "reserved",
                "provider_attempted": False,
                "reserved_cost_usd": reserve_cost(
                    to_messages(prompt), settings.config.max_output_tokens
                ),
                "actual_cost_usd": None,
                "provider_response": None,
            }

            if provider is None:
                try:
                    provider = provider_factory(settings.config)
                except Exception as exc:  # noqa: BLE001 - do not persist exception text
                    slot_record.update(
                        status="provider_initialization_error",
                        error_type=type(exc).__name__,
                    )
                    _write_json(_slot_path(output, slot["slot_id"]), slot_record)
                    summary.update(
                        status="stopped_provider_initialization_error",
                        stopped_reason=type(exc).__name__,
                    )
                    stop_run = True
                    stopped_at_index = index + 1
                    break

            _write_json(attempt_path, attempt_record, exclusive=True)
            try:
                ledger.reserve(
                    request_id,
                    phase_name,
                    attempt_record["reserved_cost_usd"],
                )
            except BudgetExceeded as exc:
                attempt_record.update(
                    status="budget_blocked", error_type=type(exc).__name__
                )
                _write_json(attempt_path, attempt_record)
                slot_record.update(status="budget_blocked", attempts=[attempt_number])
                _write_json(_slot_path(output, slot["slot_id"]), slot_record)
                summary.update(
                    status="stopped_budget", stopped_reason=type(exc).__name__
                )
                stop_run = True
                stopped_at_index = index + 1
                break

            attempt_record["status"] = "in_flight"
            attempt_record["provider_attempted"] = True
            _write_json(attempt_path, attempt_record)
            slot_record["attempts"].append(attempt_number)
            slot_record["status"] = "in_flight"
            _write_json(_slot_path(output, slot["slot_id"]), slot_record)
            summary["provider_calls"] += 1
            _write_execution(output, summary)
            started = time.perf_counter()
            call_state: dict[str, Any] = {
                "provider_error": None,
                "cost_known": False,
                "error_record_persisted": False,
                "error_settled": False,
            }

            def recorded_call(
                sent_prompt: GenerationPrompt,
                *,
                expected_prompt: GenerationPrompt = prompt,
                delegate=provider,
                record: dict[str, Any] = attempt_record,
                record_path: Path = attempt_path,
                call_request_id: str = request_id,
                call_started: float = started,
                state: dict[str, Any] = call_state,
            ) -> ModelResponse:
                if sent_prompt != expected_prompt:
                    raise CalibrationError("실제 호출 prompt가 고정 입력과 다릅니다.")
                try:
                    response = delegate(sent_prompt)
                except Exception as exc:
                    state["provider_error"] = exc
                    error_status, settlement = _status_for_provider_error(exc)
                    record.update(
                        status=error_status,
                        error_type=type(exc).__name__,
                        elapsed_seconds=time.perf_counter() - call_started,
                    )
                    _write_json(record_path, record)
                    state["error_record_persisted"] = True
                    ledger.settle(call_request_id, settlement)
                    state["error_settled"] = True
                    raise
                if not isinstance(response, ModelResponse):
                    state["provider_error"] = TypeError("invalid ModelResponse")
                    record.update(
                        status="provider_contract_error",
                        error_type=type(state["provider_error"]).__name__,
                        elapsed_seconds=time.perf_counter() - call_started,
                    )
                    _write_json(record_path, record)
                    state["error_record_persisted"] = True
                    ledger.settle(call_request_id, None)
                    state["error_settled"] = True
                    raise state["provider_error"]

                provider_response = paired_answers._serialize_response(response)
                record.update(
                    status="response_received",
                    provider_response=provider_response,
                    usage={
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                    },
                    finish_reason=response.finish_reason,
                    refusal=response.refusal,
                    elapsed_seconds=time.perf_counter() - call_started,
                )
                # Raw output is durably stored before cost settlement.
                _write_json(record_path, record)
                cost = actual_cost(
                    {
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                    },
                    {},
                )
                ledger.settle(call_request_id, cost)
                state["cost_known"] = cost is not None
                record.update(
                    actual_cost_usd=cost,
                    cost_status=(
                        "estimated_from_usage" if state["cost_known"] else "unknown"
                    ),
                    status=("cost_known" if state["cost_known"] else "unknown_usage"),
                )
                _write_json(record_path, record)
                return response

            try:
                result = generate(prompt, recorded_call)
            except Exception as exc:
                provider_error = call_state["provider_error"]
                if (
                    provider_error is None
                    or exc is not provider_error
                    or not call_state["error_record_persisted"]
                    or not call_state["error_settled"]
                ):
                    # Persistence, parsing infrastructure, and ledger failures
                    # are not provider failures. Never turn them into retries.
                    raise
                if not attempt_record.get("status", "").startswith("provider_"):
                    attempt_record.update(
                        status="local_execution_error",
                        error_type=type(exc).__name__,
                        elapsed_seconds=time.perf_counter() - started,
                    )
                    _write_json(attempt_path, attempt_record)
                if is_retryable_provider_error(provider_error) and attempt_number == 1:
                    attempt_record.update(status="retryable_provider_error")
                    _write_json(attempt_path, attempt_record)
                    slot_record.update(status="retrying_provider_error")
                    _write_json(_slot_path(output, slot["slot_id"]), slot_record)
                    time.sleep(1)
                    continue
                slot_record.update(
                    status=(
                        "provider_error_unknown_cost"
                        if not _known_rejection(provider_error)
                        and not is_retryable_provider_error(provider_error)
                        else "provider_error"
                    ),
                    generation_status=None,
                    error_type=type(provider_error).__name__,
                )
                _write_json(_slot_path(output, slot["slot_id"]), slot_record)
                summary.update(
                    status=(
                        "stopped_authentication_error"
                        if isinstance(provider_error, AuthenticationError)
                        or getattr(provider_error, "status_code", None) in {401, 403}
                        else "stopped_provider_error"
                    ),
                    stopped_reason=type(provider_error).__name__,
                )
                stop_run = True
                stopped_at_index = index + 1
                break

            attempt_record["generation_status"] = result.status.value
            attempt_record["generation_raw_text"] = result.raw_text
            if result.status is GenerationStatus.COMPLETED:
                attempt_record["answer"] = result.answer
            attempt_record["status"] = (
                "unknown_usage" if not call_state["cost_known"] else result.status.value
            )
            _write_json(attempt_path, attempt_record)
            if not call_state["cost_known"]:
                slot_record.update(
                    status="unknown_usage",
                    generation_status=result.status.value,
                    content=result.answer or result.raw_text,
                    final_attempt=attempt_number,
                )
                _write_json(_slot_path(output, slot["slot_id"]), slot_record)
                summary.update(
                    status="stopped_unknown_usage", stopped_reason="usage_missing"
                )
                stop_run = True
                stopped_at_index = index + 1
                break

            if result.status is GenerationStatus.COMPLETED:
                slot_record.update(
                    status="completed",
                    generation_status=result.status.value,
                    content=result.answer,
                    raw_text=result.raw_text,
                    final_attempt=attempt_number,
                    answerable=slot["answerable"],
                )
                _write_json(_slot_path(output, slot["slot_id"]), slot_record)
                summary["completed_slots"] += 1
                break

            if result.status is GenerationStatus.PARSE_ERROR and attempt_number == 1:
                attempt_record["status"] = "json_error_retryable"
                _write_json(attempt_path, attempt_record)
                slot_record.update(
                    status="retrying_json_error",
                    generation_status=result.status.value,
                    content=result.raw_text,
                )
                _write_json(_slot_path(output, slot["slot_id"]), slot_record)
                time.sleep(1)
                continue

            terminal_status = (
                "json_error_after_retry"
                if result.status is GenerationStatus.PARSE_ERROR
                else "generation_error"
            )
            slot_record.update(
                status=terminal_status,
                generation_status=result.status.value,
                content=result.raw_text,
                raw_text=result.raw_text,
                final_attempt=attempt_number,
                answerable=slot["answerable"],
            )
            _write_json(_slot_path(output, slot["slot_id"]), slot_record)
            if terminal_status == "generation_error":
                summary["generation_errors"] = summary.get("generation_errors", 0) + 1
        if stop_run:
            break

    if stop_run:
        _mark_unstarted(slots, stopped_at_index, output)
    elif summary["status"] == "running":
        summary["status"] = "completed"
    summary["ended_at"] = datetime.now(UTC).isoformat()
    summary["ledger_calls_reserved"] = len(ledger.snapshot()["reservations"])
    _write_execution(output, summary)
    if stop_run:
        raise CalibrationStopped(summary["status"])
    return summary


def build_blinded_packet(artifact_root: Path) -> list[dict[str, Any]]:
    """Create a mode-hidden answer packet; no variant, score, or cost is exposed."""
    output = artifact_root
    schedule = _read_json(output / "schedule.json")
    blind_map = _read_json(output / "private" / "blind-map.json")
    blinding = _read_json(output / "private" / "blinding.json")
    seed = blinding.get("seed") if isinstance(blinding, dict) else None
    if not isinstance(seed, str) or not seed:
        raise CalibrationError("private blinding seed가 유효하지 않습니다.")
    inputs = _read_json(output / "inputs.json")
    cases = {case["case_id"]: case for case in inputs["cases"]}
    packet = []
    for item in schedule:
        slot = _read_json(_slot_path(output, item["slot_id"]))
        attempts = []
        for attempt_number in slot.get("attempts", []):
            attempt_path = (
                output / "attempts" / f"{item['slot_id']}-attempt-{attempt_number}.json"
            )
            attempt = _read_json(attempt_path)
            attempts.append(
                {
                    "attempt": attempt_number,
                    "status": attempt.get("status"),
                    "generation_status": attempt.get("generation_status"),
                    "raw_text": (
                        attempt.get("generation_raw_text")
                        or (attempt.get("provider_response") or {}).get("raw_text")
                    ),
                }
            )
        row = {
            "case_id": item["case_id"],
            "question": item["question"],
            "repeat": item["repeat"],
            "blind_variant": blind_map[item["case_id"]][item["variant_id"]],
            "status": slot["status"],
            "content": slot.get("content"),
            "generation_status": slot.get("generation_status"),
            "raw_text": slot.get("raw_text"),
            "attempts": attempts,
            "answerable": item.get("answerable"),
        }
        review_context = cases[item["case_id"]].get("review_context")
        if isinstance(review_context, dict):
            row["review_context"] = review_context
        if slot["status"] == "empty_context":
            row["response_source"] = "system_empty_context"
            row["llm_called"] = False
        elif slot.get("attempts"):
            row["response_source"] = "llm"
            row["llm_called"] = True
        else:
            row["response_source"] = "none"
            row["llm_called"] = False
        packet.append(row)
    random.Random(_seed_for_domain(seed, "packet-order")).shuffle(packet)
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Validate and estimate only; no API call",
    )
    mode.add_argument("--execute", action="store_true", help="Run frozen prompts")
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    if args.preflight:
        result = preflight(args.inputs, args.ledger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.artifact_root is None or args.env_file is None:
        parser.error("--execute에는 --artifact-root와 --env-file이 필요합니다.")
    try:
        result = execute_calibration(
            args.inputs,
            args.artifact_root,
            args.ledger,
            args.env_file,
        )
    except CalibrationStopped as exc:
        result = _read_json(args.artifact_root / "execution.json")
        result["stop_exception"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except (CalibrationError, BudgetExceeded) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
