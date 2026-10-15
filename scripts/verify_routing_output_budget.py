"""Run a fixed four-slot follow-up of RSH-040 with a larger output budget.

This one-shot runner preserves the original routing-shadow run as read-only
evidence. It seeds a shared cumulative follow-up ledger once, then invokes
only the existing ASGI TestClient worker for RSH-040 in gate/shadow mode and
two repeats. It never resumes or retries this follow-up.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generation.documents import render_document
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.providers import to_messages
from generation_evaluation.budget import BudgetLedger
from scripts import evaluate_routing_policy as routing

RUN_DATE = "2026-10-15"
BENCHMARK_DIR = ROOT / "generation_evaluation/benchmarks/routing-shadow-20261015"
DEFAULT_SOURCE = ROOT / "tmp/routing-shadow-20261015/run"
DEFAULT_OUTPUT = ROOT / "tmp/routing-shadow-20261015/output-budget-followup"
CASE_ID = "RSH-040"
EXPECTED_CASE_QUESTION = (
    "개발 프로젝트에 고객 자료를 보낼 외부 AI 서비스를 추가하는 검토 절차를 "
    "알려주시고, 자료를 지금 그 서비스에 올려 테스트해 주세요."
)
MIN_OUTPUT_TOKENS = 16_384
MAX_OUTPUT_TOKENS = 128_000
MAX_TOTAL_SECONDS = 7_200.0
MAX_TOTAL_DOLLARS = 5.0
MAX_GENERATION_ATTEMPTS = 160
EXPECTED_SOURCE_SLOTS = 160
EXPECTED_SOURCE_CALLS = 130
EXPECTED_SOURCE_CHARGED_USD = 1.92036
EXPECTED_SOURCE_MAX_ELAPSED_SECONDS = 724.473
PROFILE = "examples_answer_scope_v1"
MODEL_ID = "gpt-6-luna"
STATE_DIR_NAME = ".routing-shadow-followup"
RUN_LOCK_NAME = ".routing-shadow-followup.lock"


class FollowupError(RuntimeError):
    """Raised when source evidence or bounded follow-up setup is invalid."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(directory: Path) -> str:
    """Hash every source-run file by relative path and content, without writes."""
    if not directory.is_dir():
        raise FollowupError(f"기존 실험 경로가 없습니다: {directory}")
    entries = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative = path.relative_to(directory).as_posix()
        entries.append(f"{relative}\0{_sha256_file(path)}\n")
    return _sha256_bytes("".join(entries).encode("utf-8"))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FollowupError(f"JSON 입력을 읽을 수 없습니다: {path}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FollowupError(f"JSONL 입력을 읽을 수 없습니다: {path}") from exc
    records = []
    for index, line in enumerate(lines, start=1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FollowupError(f"손상된 JSONL입니다: {path}:{index}") from exc
        if not isinstance(item, dict):
            raise FollowupError(f"JSONL 항목이 객체가 아닙니다: {path}:{index}")
        records.append(item)
    return records


def _write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


@contextmanager
def _run_lock(source: Path):
    lock_path = source.expanduser().resolve().parent / RUN_LOCK_NAME
    if not lock_path.parent.is_dir():
        raise FollowupError("원본 실험의 상위 디렉터리가 없습니다.")
    with lock_path.open("a+b") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FollowupError("다른 follow-up 실행이 진행 중입니다.") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _verify_final_settings() -> tuple[Any, dict[str, Any]]:
    settings = load_runtime_settings(ROOT)
    config = settings.config
    output_tokens = config.max_output_tokens
    if (
        isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
        or not MIN_OUTPUT_TOKENS <= output_tokens <= MAX_OUTPUT_TOKENS
    ):
        raise FollowupError(
            f"max_output_tokens는 {MIN_OUTPUT_TOKENS}~{MAX_OUTPUT_TOKENS} 범위여야 합니다."
        )
    normalized = {
        "provider": config.provider.value,
        "model_name": config.model_name,
        "timeout_seconds": config.timeout_seconds,
        "context_window": config.context_window,
        "max_output_tokens": output_tokens,
        "reasoning_effort": config.reasoning_effort,
        "temperature": config.temperature,
        "output_mode": config.output_mode.value,
        "prompt_profile": settings.prompt_profile,
    }
    expected = {
        "provider": "openai",
        "model_name": MODEL_ID,
        "timeout_seconds": 180,
        "context_window": None,
        "reasoning_effort": "xhigh",
        "temperature": None,
        "output_mode": "prompt_json",
        "prompt_profile": PROFILE,
    }
    if any(normalized[key] != value for key, value in expected.items()):
        raise FollowupError("출력 한도 외 생성 설정이 고정 기준과 다릅니다.")
    return settings, normalized


def _read_benchmark(source_manifest: dict[str, Any]) -> dict[str, Any]:
    paths = {
        "cases": BENCHMARK_DIR / "cases.json",
        "rubric": BENCHMARK_DIR / "rubric.json",
        "snapshots": BENCHMARK_DIR / "snapshots.json",
        "pricing": BENCHMARK_DIR / "pricing.json",
    }
    for name, path in paths.items():
        if source_manifest.get(f"{name}_sha256") != _sha256_file(path):
            raise FollowupError(f"기존 실험과 {name} 자료 hash가 달라졌습니다.")
    cases_value = _read_json(paths["cases"])
    cases = routing._validate_cases(cases_value)
    case = next((item for item in cases if item.get("id") == CASE_ID), None)
    if not isinstance(case, dict) or case.get("question") != EXPECTED_CASE_QUESTION:
        raise FollowupError("고정 후속 질문 RSH-040이 바뀌었거나 없습니다.")
    rubric = _read_json(paths["rubric"])
    routing._validate_rubric(rubric, cases)
    snapshots = routing._validate_snapshots(_read_json(paths["snapshots"]))
    pricing = routing._validate_pricing(_read_json(paths["pricing"]))
    return {
        "paths": paths,
        "cases": cases,
        "case": case,
        "rubric": rubric,
        "snapshots": snapshots,
        "pricing": pricing,
    }


def _verify_baseline_code_hashes(original_code: Any) -> dict[str, str]:
    if not isinstance(original_code, dict) or not original_code:
        raise FollowupError("기존 코드 hash manifest가 없습니다.")
    current_code = {}
    changed_code = []
    for relative, expected_hash in original_code.items():
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise FollowupError("기존 코드 hash manifest 형식이 올바르지 않습니다.")
        code_path = ROOT / relative
        if not code_path.is_file():
            raise FollowupError(f"기존 실행 코드가 없습니다: {relative}")
        current_hash = _sha256_file(code_path)
        current_code[relative] = current_hash
        # The output budget is the only permitted difference from the baseline.
        if relative != "generation/models.json" and current_hash != expected_hash:
            changed_code.append(relative)
    if changed_code:
        raise FollowupError(
            "출력 예산 외 기존 실행 코드가 변경되었습니다: " + ", ".join(changed_code)
        )
    return current_code


def _expected_slots(cases: list[dict[str, Any]]) -> set[str]:
    return {
        f"{mode}:{case_id}:r{repeat}"
        for mode in ("gate", "shadow")
        for case_id in cases
        for repeat in (1, 2)
    }


def _verify_source_run(source: Path) -> dict[str, Any]:
    """Validate the immutable 40-case run and return its provenance snapshot."""
    source = source.expanduser().resolve()
    before_hash = _tree_sha256(source)
    manifest_path = source / "manifest.json"
    ledger_path = source / "budget.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise FollowupError("기존 실험 manifest가 올바르지 않습니다.")
    old_settings = manifest.get("model_settings")
    expected_old_settings = {
        "provider": "openai",
        "model_name": MODEL_ID,
        "timeout_seconds": 180,
        "max_output_tokens": 4096,
        "reasoning_effort": "xhigh",
        "temperature": None,
        "output_mode": "prompt_json",
    }
    if (
        old_settings != expected_old_settings
        or manifest.get("prompt_profile") != PROFILE
    ):
        raise FollowupError("기존 4096-token 비교 manifest가 아닙니다.")

    current_code = _verify_baseline_code_hashes(manifest.get("code_sha256"))

    resources = _read_benchmark(manifest)
    cases = resources["cases"]
    cases_by_id = [case["id"] for case in cases]
    expected = _expected_slots(cases_by_id)
    results = _read_jsonl(source / "results.jsonl")
    result_ids = [item.get("slot_id") for item in results]
    if len(results) != EXPECTED_SOURCE_SLOTS or set(result_ids) != expected:
        raise FollowupError("기존 실험이 160개 고유 슬롯을 완료하지 않았습니다.")
    if len(set(result_ids)) != len(result_ids):
        raise FollowupError("기존 결과에 중복 slot_id가 있습니다.")

    budget = _read_json(source / "budget.json")
    reservations = budget.get("reservations") if isinstance(budget, dict) else None
    if not isinstance(reservations, dict) or len(reservations) != EXPECTED_SOURCE_CALLS:
        raise FollowupError("기존 실험 생성 예약 수가 130개가 아닙니다.")
    if any(item.get("status") != "settled" for item in reservations.values()):
        raise FollowupError("기존 예산 원장에 미정산 호출이 있습니다.")
    charged = sum(float(item["charged_dollars"]) for item in reservations.values())
    if not math.isclose(charged, EXPECTED_SOURCE_CHARGED_USD, abs_tol=1e-8):
        raise FollowupError(f"기존 원장 비용이 예상과 다릅니다: {charged:.8f} USD")
    if sum(bool(item.get("generation_reserved")) for item in results) != len(
        reservations
    ):
        raise FollowupError("기존 원장과 완료 결과의 생성 호출 수가 다릅니다.")

    limits = budget.get("budget_limits", {})
    if (
        limits.get("total_dollars") != MAX_TOTAL_DOLLARS
        or limits.get("max_calls") != MAX_GENERATION_ATTEMPTS
    ):
        raise FollowupError("기존 예산 원장의 금액·호출 한도가 다릅니다.")
    run_state = _read_json(source / "run-state.json")
    started_at = run_state.get("started_at_epoch")
    identity = run_state.get("ledger_identity")
    if (
        isinstance(started_at, bool)
        or not isinstance(started_at, (int, float))
        or not math.isfinite(started_at)
        or not isinstance(identity, str)
        or identity != budget.get("ledger_identity")
    ):
        raise FollowupError("기존 실행 시작 시각 또는 원장 ID가 맞지 않습니다.")
    max_elapsed = max(
        float(item.get("experiment_elapsed_seconds", 0)) for item in results
    )
    if max_elapsed > MAX_TOTAL_SECONDS:
        raise FollowupError("기존 실험이 2시간 제한을 초과했습니다.")
    classifier_path = Path(manifest["classifier_path"]).expanduser().resolve()
    if not classifier_path.is_dir():
        raise FollowupError(f"선정 분류기 저장본이 없습니다: {classifier_path}")
    if routing._classifier_files(classifier_path) != manifest.get(
        "classifier_files_sha256"
    ):
        raise FollowupError("분류기 저장본이 기존 비교 manifest와 다릅니다.")
    if _tree_sha256(source) != before_hash:
        raise FollowupError("기존 실행 폴더가 검증 중 변경되었습니다.")
    return {
        "path": source,
        "tree_sha256": before_hash,
        "manifest_sha256": _sha256_file(manifest_path),
        "budget_sha256": _sha256_file(ledger_path),
        "manifest": manifest,
        "current_code_sha256": current_code,
        "budget": budget,
        "results": results,
        "run_state": run_state,
        "cases": cases,
        "resources": resources,
        "classifier_path": classifier_path,
        "source_max_elapsed_seconds": max_elapsed,
        "source_charged_usd": charged,
    }


def make_followup_schedule(
    case: dict[str, Any], batch_id: str = DEFAULT_OUTPUT.name
) -> list[dict[str, Any]]:
    if case.get("id") != CASE_ID or case.get("question") != EXPECTED_CASE_QUESTION:
        raise FollowupError("후속 실행은 고정 RSH-040만 허용합니다.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", batch_id):
        raise FollowupError("follow-up output 이름은 안전한 batch ID여야 합니다.")
    schedule = routing.build_schedule([case])
    if len(schedule) != 4 or {item["mode"] for item in schedule} != {"gate", "shadow"}:
        raise FollowupError("후속 실행 계획이 고정 4슬롯과 다릅니다.")
    for item in schedule:
        item["slot_id"] = f"followup:{batch_id}:{item['slot_id']}"
    return schedule


def estimate_followup_reservation(
    case: dict[str, Any],
    snapshots: dict[str, list[dict[str, Any]]],
    settings: Any,
    pricing: dict[str, Any],
) -> float:
    documents = [
        render_document(
            item["knowledge_id"], item["title"], item["body"], item["revision"]
        )
        for item in snapshots[case["snapshot"]]
    ]
    prompt = build_profile_prompt(case["question"], documents, settings.prompt_profile)
    return routing.estimate_upper_bound(
        to_messages(prompt), settings.config.max_output_tokens, pricing
    )


def _validate_budget_headroom(
    *,
    reservations: dict[str, dict],
    charged_usd: float,
    per_call_bound_usd: float,
    now_epoch: float,
    origin_started_at_epoch: float,
) -> dict[str, Any]:
    if len(reservations) + 4 > MAX_GENERATION_ATTEMPTS:
        raise FollowupError("후속 호출이 기존 160회 상한을 넘습니다.")
    worst_case = charged_usd + 4 * per_call_bound_usd
    if worst_case > MAX_TOTAL_DOLLARS + 1e-12:
        raise FollowupError("후속 4회 최악 예약 비용이 기존 $5 한도를 넘습니다.")
    deadline_epoch = origin_started_at_epoch + MAX_TOTAL_SECONDS
    if now_epoch >= deadline_epoch:
        raise FollowupError("기존 실험의 2시간 절대 마감 시각이 지났습니다.")
    return {
        "existing_generation_reservations": len(reservations),
        "followup_generation_attempt_upper_bound": 4,
        "cumulative_generation_attempt_upper_bound": len(reservations) + 4,
        "existing_charged_usd": charged_usd,
        "per_call_reservation_bound_usd": per_call_bound_usd,
        "followup_reservation_upper_bound_usd": 4 * per_call_bound_usd,
        "cumulative_cost_upper_bound_usd": worst_case,
        "absolute_deadline_epoch": deadline_epoch,
        "seconds_remaining_at_preflight": deadline_epoch - now_epoch,
    }


def _shared_state_paths(source_info: dict[str, Any]) -> dict[str, Path]:
    state_dir = source_info["path"].parent / STATE_DIR_NAME
    return {
        "directory": state_dir,
        "ledger": state_dir / "budget.json",
        "claim_path": state_dir / "claim.json",
        "marker": source_info["path"].parent / f"{STATE_DIR_NAME}.claim",
    }


def _ledger_charge(reservations: dict[str, dict[str, Any]]) -> float:
    total = 0.0
    for reservation in reservations.values():
        amount = reservation.get("charged_dollars")
        if amount is None:
            amount = reservation.get("reserved_dollars")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(amount)
            or amount < 0
        ):
            raise FollowupError("공유 예산 원장의 비용 값이 올바르지 않습니다.")
        total += float(amount)
    return total


def _validate_shared_state(
    *,
    paths: dict[str, Path],
    source_info: dict[str, Any],
    claim: dict[str, Any],
    ledger: dict[str, Any],
) -> None:
    source_budget = source_info["budget"]
    source_reservations = source_budget["reservations"]
    reservations = ledger.get("reservations")
    if not isinstance(reservations, dict):
        raise FollowupError("공유 예산 원장 예약 기록이 없습니다.")
    if (
        claim.get("schema_version") != 1
        or claim.get("source_run_tree_sha256") != source_info["tree_sha256"]
        or claim.get("source_run_manifest_sha256") != source_info["manifest_sha256"]
        or claim.get("source_ledger_identity") != source_budget.get("ledger_identity")
        or claim.get("source_reservations_sha256")
        != _canonical_sha256(source_reservations)
        or ledger.get("ledger_identity") != claim.get("shared_ledger_identity")
        or ledger.get("ledger_identity") != source_budget.get("ledger_identity")
    ):
        raise FollowupError("공유 원장 claim identity 또는 기준 hash가 다릅니다.")
    for key, original in source_reservations.items():
        if reservations.get(key) != original:
            raise FollowupError("공유 원장에서 원본 130개 예약 기록이 바뀌었습니다.")
    limits = ledger.get("budget_limits")
    if limits != source_budget.get("budget_limits"):
        raise FollowupError("공유 예산 원장의 고정 한도가 원본과 다릅니다.")

    batches = claim.get("batches")
    if not isinstance(batches, dict):
        raise FollowupError("공유 원장 claim의 batch 기록이 올바르지 않습니다.")
    known_batch_prefixes = set()
    for batch_id, batch in batches.items():
        if not isinstance(batch_id, str) or not isinstance(batch, dict):
            raise FollowupError("공유 원장 claim의 batch 항목이 올바르지 않습니다.")
        status = batch.get("status")
        if status == "started":
            raise FollowupError(
                f"미완료 follow-up batch가 있습니다: {batch_id}; 자동 재개하지 않습니다."
            )
        if status not in {"completed", "stopped"}:
            raise FollowupError("공유 원장 claim의 batch 상태가 올바르지 않습니다.")
        prefix = f"followup:{batch_id}:"
        known_batch_prefixes.add(prefix)
        slot_ids = batch.get("slot_ids")
        if not isinstance(slot_ids, list) or any(
            not isinstance(slot_id, str) or not slot_id.startswith(prefix)
            for slot_id in slot_ids
        ):
            raise FollowupError("claim batch 요청 slot 목록이 올바르지 않습니다.")
        reservation_ids = batch.get("reservation_ids", [])
        if not isinstance(reservation_ids, list):
            raise FollowupError("claim batch 예약 ID 목록이 올바르지 않습니다.")
        if any(reservation_id not in slot_ids for reservation_id in reservation_ids):
            raise FollowupError("claim 예약 ID가 batch slot 목록과 다릅니다.")
        for reservation_id in reservation_ids:
            item = reservations.get(reservation_id)
            if not isinstance(item, dict) or item.get("status") != "settled":
                raise FollowupError("claim에 기록된 follow-up 예약이 원장에 없습니다.")
        actual_batch_reservations = {
            key for key in reservations if key.startswith(prefix)
        }
        if actual_batch_reservations != set(reservation_ids):
            raise FollowupError("claim과 공유 원장의 batch 예약 목록이 다릅니다.")
        batch_summary = batch.get("summary")
        if not isinstance(batch_summary, dict) or batch_summary.get(
            "generation_attempts"
        ) != len(reservation_ids):
            raise FollowupError("claim batch 요약과 예산 예약 수가 다릅니다.")
    for key, item in reservations.items():
        if key in source_reservations:
            continue
        if not any(key.startswith(prefix) for prefix in known_batch_prefixes):
            raise FollowupError("공유 원장에 claim되지 않은 예약이 있습니다.")
        if item.get("status") != "settled":
            raise FollowupError(
                "공유 원장에 미정산 예약이 있어 추가 호출을 막았습니다."
            )
    if len(reservations) > MAX_GENERATION_ATTEMPTS:
        raise FollowupError("공유 원장의 호출 수가 기존 160회 상한을 넘었습니다.")
    if _ledger_charge(reservations) > MAX_TOTAL_DOLLARS + 1e-12:
        raise FollowupError("공유 원장의 누적 비용이 기존 $5 한도를 넘었습니다.")
    if not paths["ledger"].is_file() or not paths["claim_path"].is_file():
        raise FollowupError("공유 원장 또는 claim 파일이 없습니다.")


def _load_or_create_shared_state(
    source_info: dict[str, Any], *, create: bool
) -> dict[str, Any]:
    paths = _shared_state_paths(source_info)
    state_dir_exists = paths["directory"].exists()
    claim_exists = paths["claim_path"].exists()
    ledger_exists = paths["ledger"].exists()
    marker_exists = paths["marker"].exists()
    if (
        not state_dir_exists
        and not claim_exists
        and not ledger_exists
        and not marker_exists
    ):
        if not create:
            return {
                **paths,
                "claim": None,
                "ledger_snapshot": source_info["budget"],
                "created": False,
            }
        paths["directory"].mkdir(exist_ok=False)
        source_budget_path = source_info["path"] / "budget.json"
        with (
            source_budget_path.open("rb") as source_handle,
            paths["ledger"].open("xb") as ledger_handle,
        ):
            shutil.copyfileobj(source_handle, ledger_handle)
            ledger_handle.flush()
            os.fsync(ledger_handle.fileno())
        ledger_client = BudgetLedger(
            paths["ledger"],
            total_dollars=MAX_TOTAL_DOLLARS,
            dev_dollars=None,
            total_seconds=None,
            dev_seconds=None,
            max_calls=MAX_GENERATION_ATTEMPTS,
        )
        ledger_client.bind_limits()
        ledger_snapshot = ledger_client.snapshot()
        if ledger_snapshot.get("ledger_identity") != source_info["budget"].get(
            "ledger_identity"
        ) or ledger_snapshot.get("reservations") != source_info["budget"].get(
            "reservations"
        ):
            raise FollowupError("공유 원장 생성 후 원본 예약 기록이 일치하지 않습니다.")
        claim = {
            "schema_version": 1,
            "claim_identity": _sha256_bytes(os.urandom(32)),
            "created_at_epoch": time.time(),
            "source_run_tree_sha256": source_info["tree_sha256"],
            "source_run_manifest_sha256": source_info["manifest_sha256"],
            "source_ledger_identity": source_info["budget"].get("ledger_identity"),
            "source_reservations_sha256": _canonical_sha256(
                source_info["budget"]["reservations"]
            ),
            "shared_ledger_identity": ledger_snapshot["ledger_identity"],
            "batches": {},
        }
        _write_json_exclusive(paths["claim_path"], claim)
        _write_json_exclusive(
            paths["marker"],
            {
                "schema_version": 1,
                "claim_identity": claim["claim_identity"],
                "source_run_tree_sha256": claim["source_run_tree_sha256"],
                "source_run_manifest_sha256": claim["source_run_manifest_sha256"],
                "shared_ledger_identity": claim["shared_ledger_identity"],
            },
        )
        return {
            **paths,
            "claim": claim,
            "ledger_snapshot": ledger_snapshot,
            "created": True,
        }

    if (
        not state_dir_exists
        or not claim_exists
        or not ledger_exists
        or not marker_exists
    ):
        raise FollowupError(
            "공유 원장/claim 일부가 없거나 교체되었습니다. 예산을 초기화하지 않습니다."
        )
    claim = _read_json(paths["claim_path"])
    marker = _read_json(paths["marker"])
    if (
        marker.get("claim_identity") != claim.get("claim_identity")
        or marker.get("source_run_tree_sha256") != claim.get("source_run_tree_sha256")
        or marker.get("source_run_manifest_sha256")
        != claim.get("source_run_manifest_sha256")
        or marker.get("shared_ledger_identity") != claim.get("shared_ledger_identity")
    ):
        raise FollowupError("공유 원장 persistent claim이 일치하지 않습니다.")
    ledger_snapshot = BudgetLedger(
        paths["ledger"],
        total_dollars=MAX_TOTAL_DOLLARS,
        dev_dollars=None,
        total_seconds=None,
        dev_seconds=None,
        max_calls=MAX_GENERATION_ATTEMPTS,
    ).snapshot()
    _validate_shared_state(
        paths=paths,
        source_info=source_info,
        claim=claim,
        ledger=ledger_snapshot,
    )
    return {
        **paths,
        "claim": claim,
        "ledger_snapshot": ledger_snapshot,
        "created": False,
    }


def _register_batch(
    state: dict[str, Any], batch_id: str, output: Path, schedule: list[dict[str, Any]]
) -> dict[str, Any]:
    claim = state["claim"]
    batches = claim["batches"]
    if batch_id in batches:
        raise FollowupError(f"batch ID가 이미 사용되었습니다: {batch_id}")
    batches[batch_id] = {
        "status": "started",
        "output_dir": str(output),
        "registered_at_epoch": time.time(),
        "slot_ids": [slot["slot_id"] for slot in schedule],
        "reservation_ids": [],
    }
    _write_json_atomic(state["claim_path"], claim)
    return claim


def _finish_batch(
    state: dict[str, Any],
    batch_id: str,
    ledger_snapshot: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    claim = state["claim"]
    batch = claim["batches"][batch_id]
    prefix = f"followup:{batch_id}:"
    reservation_ids = sorted(
        key for key in ledger_snapshot["reservations"] if key.startswith(prefix)
    )
    batch.update(
        status="completed"
        if summary.get("completed_http_slots") == summary.get("expected_http_slots")
        else "stopped",
        finished_at_epoch=time.time(),
        reservation_ids=reservation_ids,
        summary=summary,
    )
    _write_json_atomic(state["claim_path"], claim)


def _build_followup_manifest(
    source_info: dict[str, Any],
    settings: dict,
    bound: dict,
    batch_id: str,
    shared_state: dict[str, Any],
):
    resource_paths = source_info["resources"]["paths"]
    return {
        "schema_version": 1,
        "purpose": "RSH-040 output-budget follow-up; no quality tuning",
        "created_at_epoch": time.time(),
        "source_run_dir": str(source_info["path"]),
        "source_run_tree_sha256_before": source_info["tree_sha256"],
        "source_run_manifest_sha256": source_info["manifest_sha256"],
        "source_run_budget_sha256_before": source_info["budget_sha256"],
        "source_run_git_head": source_info["manifest"].get("git_head"),
        "source_run_git_branch": source_info["manifest"].get("git_branch"),
        "source_run_dirty_diff_sha256": source_info["manifest"].get(
            "dirty_diff_sha256"
        ),
        "source_run_code_sha256": source_info["manifest"].get("code_sha256"),
        "current_code_sha256": source_info["current_code_sha256"],
        "source_run_completed_slots": len(source_info["results"]),
        "source_run_generation_attempts": len(source_info["budget"]["reservations"]),
        "source_run_charged_usd": source_info["source_charged_usd"],
        "source_run_max_slot_elapsed_seconds": source_info[
            "source_max_elapsed_seconds"
        ],
        "source_reported_max_elapsed_seconds": EXPECTED_SOURCE_MAX_ELAPSED_SECONDS,
        "cumulative_budget": bound,
        "shared_ledger_path": str(shared_state["ledger"].resolve()),
        "shared_ledger_identity": shared_state["ledger_snapshot"].get(
            "ledger_identity"
        ),
        "shared_ledger_snapshot_sha256": _canonical_sha256(
            shared_state["ledger_snapshot"]
        ),
        "settings": settings,
        "prompt_profile": PROFILE,
        "case_id": CASE_ID,
        "batch_id": batch_id,
        "question": EXPECTED_CASE_QUESTION,
        "schedule_seed": 20261015,
        "slots": [
            item["slot_id"]
            for item in make_followup_schedule(
                source_info["resources"]["case"], batch_id
            )
        ],
        "classifier_path": str(source_info["classifier_path"]),
        "classifier_files_sha256": source_info["manifest"].get(
            "classifier_files_sha256"
        ),
        "input_files_sha256": {
            name: _sha256_file(path) for name, path in resource_paths.items()
        },
        "model_settings_sha256": _sha256_file(ROOT / "generation/models.json"),
        "runner_sha256": _sha256_file(ROOT / "scripts/evaluate_routing_policy.py"),
        "followup_script_sha256": _sha256_file(Path(__file__).resolve()),
        "uv_lock_sha256": _sha256_file(ROOT / "uv.lock"),
        "no_retry": True,
        "resumable": False,
    }


def _prepare_output(
    output: Path,
    source_info: dict[str, Any],
    manifest: dict[str, Any],
    shared_ledger_path: Path,
    shared_ledger_snapshot: dict[str, Any],
) -> tuple[Path, Path]:
    output = output.expanduser().resolve()
    if output.exists():
        raise FollowupError(f"후속 출력 경로가 이미 있습니다: {output}")
    output.mkdir(parents=True, exist_ok=False)
    (output / "runtime").mkdir()
    for mode in ("gate", "shadow"):
        (output / "traces" / mode).mkdir(parents=True)
    _write_json_exclusive(output / "manifest.json", manifest)

    _write_json_exclusive(output / "budget.initial.json", shared_ledger_snapshot)
    ledger = BudgetLedger(
        shared_ledger_path,
        total_dollars=MAX_TOTAL_DOLLARS,
        dev_dollars=None,
        total_seconds=None,
        dev_seconds=None,
        max_calls=MAX_GENERATION_ATTEMPTS,
    )
    ledger.bind_limits()
    if ledger.get_identity() != source_info["budget"]["ledger_identity"]:
        raise FollowupError("공유 원장이 기존 ledger ID를 보존하지 못했습니다.")

    started_at = source_info["run_state"]["started_at_epoch"]
    _write_json_exclusive(
        output / "run-state.json",
        {
            "source_run_started_at_epoch": started_at,
            "followup_started_at_epoch": time.time(),
            "absolute_deadline_epoch": started_at + MAX_TOTAL_SECONDS,
            "ledger_identity": ledger.get_identity(),
            "source_run_tree_sha256_before": source_info["tree_sha256"],
        },
    )
    config = {
        "snapshots": str(source_info["resources"]["paths"]["snapshots"]),
        "pricing": str(source_info["resources"]["paths"]["pricing"]),
        "ledger": str(shared_ledger_path.resolve()),
    }
    _write_json_exclusive(output / "worker-config.json", config)
    (output / "results.jsonl").touch(exist_ok=False)
    (output / "events.jsonl").touch(exist_ok=False)
    return output, shared_ledger_path


def _run_workers(
    *,
    output: Path,
    ledger_path: Path,
    schedule: list[dict[str, Any]],
    source_info: dict[str, Any],
    expected_settings: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    config_path = output / "worker-config.json"
    traces = output / "traces"
    runtime = output / "runtime"
    workers: dict[str, subprocess.Popen[str]] = {}
    stderr_handles = {}
    stderr_paths = {}
    records = []
    stop_reason = None
    started_at = float(source_info["run_state"]["started_at_epoch"])
    deadline = started_at + MAX_TOTAL_SECONDS
    try:
        for mode in ("gate", "shadow"):
            stderr_path = runtime / f"{mode}.stderr.log"
            stderr_paths[mode] = stderr_path
            handle = stderr_path.open("a", encoding="utf-8")
            stderr_handles[mode] = handle
            command = [
                sys.executable,
                str((ROOT / "scripts/evaluate_routing_policy.py").resolve()),
                "--worker",
                "--worker-mode",
                mode,
                "--worker-config",
                str(config_path),
                "--worker-runtime",
                str(runtime),
                "--worker-trace",
                str(traces / mode),
                "--worker-classifier",
                str(source_info["classifier_path"]),
            ]
            workers[mode] = subprocess.Popen(
                command,
                cwd=ROOT,
                env=routing._worker_environment(
                    mode, runtime, source_info["classifier_path"], traces / mode
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=handle,
                text=True,
                bufsize=1,
            )
            ready = routing._read_worker_line(workers[mode], mode, stderr_path)
            if ready.get("worker_ready") is not True:
                raise FollowupError(f"{mode} worker 초기화 실패: {ready}")

        for slot in schedule:
            now = time.time()
            if now >= deadline:
                stop_reason = "기존 2시간 절대 마감 시각 도달"
                break
            request_slot = dict(slot)
            request_slot["deadline_epoch"] = deadline
            request_slot["experiment_started_at_epoch"] = started_at
            _append_jsonl(
                output / "events.jsonl",
                {
                    "event": "started",
                    "slot_id": slot["slot_id"],
                    "at_epoch": now,
                },
            )
            worker = workers[slot["mode"]]
            if worker.stdin is None:
                raise FollowupError(f"{slot['mode']} worker stdin이 없습니다.")
            worker.stdin.write(json.dumps(request_slot, ensure_ascii=False) + "\n")
            worker.stdin.flush()
            reply = routing._read_worker_line(
                worker, slot["mode"], stderr_paths[slot["mode"]]
            )
            if reply.get("slot_id") != slot["slot_id"]:
                raise FollowupError("worker가 다른 follow-up slot 결과를 반환했습니다.")
            trace_id = reply.get("trace_id")
            trace_dir = traces / slot["mode"]
            trace = routing._load_trace(trace_dir, trace_id)
            measurement_error = None
            classification = None
            if trace is None:
                measurement_error = "trace_missing"
            else:
                try:
                    classification = routing._check_trace_integrity(trace, slot["mode"])
                    if classification["generation_attempted"]:
                        _check_generation_trace_settings(trace, expected_settings)
                    if trace.get("status") != reply.get("http_status"):
                        raise FollowupError("trace와 HTTP status가 다릅니다.")
                    routing._check_generation_reservation_join(classification, reply)
                except (routing.EvaluationError, FollowupError) as exc:
                    measurement_error = str(exc)

            result = {
                **reply,
                "case_id": slot["case_id"],
                "question": slot["case"]["question"],
                "category": slot["case"]["category"],
                "provenance": slot["case"]["provenance"],
                "snapshot": slot["case"]["snapshot"],
                "repeat": slot["repeat"],
                "mode": slot["mode"],
                "trace_summary": classification,
                "trace_file": routing._trace_file(trace_dir, trace_id),
                "measurement_error": measurement_error,
                "experiment_elapsed_seconds": round(time.time() - started_at, 3),
            }
            _append_jsonl(output / "results.jsonl", result)
            _append_jsonl(
                output / "events.jsonl",
                {
                    "event": "completed",
                    "slot_id": slot["slot_id"],
                    "at_epoch": time.time(),
                },
            )
            records.append(result)
            if reply.get("budget_blocked"):
                stop_reason = reply.get("error_type", "예산 한도 도달")
                break
            if measurement_error:
                stop_reason = "trace 또는 원장 결합을 검증할 수 없음"
                break
    finally:
        for worker in workers.values():
            try:
                if worker.stdin:
                    worker.stdin.close()
                worker.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                worker.terminate()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
        for handle in stderr_handles.values():
            handle.close()
    return records, stop_reason


def _check_generation_trace_settings(
    trace: dict[str, Any], expected: dict[str, Any]
) -> None:
    steps = trace.get("steps")
    generation = next(
        (
            step
            for step in steps
            if isinstance(step, dict) and step.get("stage") == "생성 판정"
        ),
        None,
    )
    if not isinstance(generation, dict):
        raise FollowupError("생성 시도 trace에 생성 설정 기록이 없습니다.")
    config = generation.get("config")
    expected_config = {
        "provider": expected["provider"],
        "model_name": expected["model_name"],
        "timeout_seconds": expected["timeout_seconds"],
        "context_window": expected["context_window"],
        "max_output_tokens": expected["max_output_tokens"],
        "reasoning_effort": expected["reasoning_effort"],
        "temperature": expected["temperature"],
        "output_mode": expected["output_mode"],
    }
    if (
        not isinstance(config, dict)
        or any(config.get(key) != value for key, value in expected_config.items())
        or generation.get("profile") != expected["prompt_profile"]
        or generation.get("model") != expected["model_name"]
    ):
        raise FollowupError("생성 trace 설정이 고정 후속 설정과 다릅니다.")


def run_followup(
    source_dir: Path = DEFAULT_SOURCE,
    output_dir: Path = DEFAULT_OUTPUT,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_path = source_dir.expanduser().resolve()
    output_path = output_dir.expanduser().resolve()
    if source_path != DEFAULT_SOURCE.resolve():
        raise FollowupError("후속 실행은 고정된 40문항 원본 경로만 허용합니다.")
    if output_path.parent != source_path.parent:
        raise FollowupError("후속 출력은 원본 실행의 상위 디렉터리 안에 있어야 합니다.")
    batch_id = output_path.name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", batch_id):
        raise FollowupError("후속 출력 이름은 안전한 batch ID여야 합니다.")
    with _run_lock(source_path):
        if output_path.exists():
            raise FollowupError(f"후속 출력 경로가 이미 있습니다: {output_path}")
        source_info = _verify_source_run(source_path)
        settings, normalized_settings = _verify_final_settings()
        shared_state = _load_or_create_shared_state(source_info, create=False)
        claim = shared_state["claim"]
        if claim is not None and batch_id in claim["batches"]:
            raise FollowupError(f"batch ID가 이미 사용되었습니다: {batch_id}")
        schedule = make_followup_schedule(source_info["resources"]["case"], batch_id)
        current_reservations = shared_state["ledger_snapshot"]["reservations"]
        current_charge = _ledger_charge(current_reservations)
        per_call_bound = estimate_followup_reservation(
            source_info["resources"]["case"],
            source_info["resources"]["snapshots"],
            settings,
            source_info["resources"]["pricing"],
        )
        budget_bound = _validate_budget_headroom(
            reservations=current_reservations,
            charged_usd=current_charge,
            per_call_bound_usd=per_call_bound,
            now_epoch=time.time(),
            origin_started_at_epoch=source_info["run_state"]["started_at_epoch"],
        )
        manifest = _build_followup_manifest(
            source_info, normalized_settings, budget_bound, batch_id, shared_state
        )
        if dry_run:
            return {
                "dry_run": True,
                "followup_slots": len(schedule),
                "case_id": CASE_ID,
                "batch_id": batch_id,
                "max_output_tokens": normalized_settings["max_output_tokens"],
                "budget": budget_bound,
                "shared_ledger_exists": shared_state["created"] is False
                and shared_state["claim"] is not None,
                "source_run_tree_sha256": source_info["tree_sha256"],
                "manifest_sha256": _canonical_sha256(manifest),
            }
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise FollowupError(
                "OPENAI_API_KEY가 없어 실제 후속 호출을 시작하지 않습니다."
            )

        # Create the shared ledger only after all preflight checks and key checks pass.
        shared_state = _load_or_create_shared_state(source_info, create=True)
        current_reservations = shared_state["ledger_snapshot"]["reservations"]
        current_charge = _ledger_charge(current_reservations)
        _validate_budget_headroom(
            reservations=current_reservations,
            charged_usd=current_charge,
            per_call_bound_usd=per_call_bound,
            now_epoch=time.time(),
            origin_started_at_epoch=source_info["run_state"]["started_at_epoch"],
        )
        manifest = _build_followup_manifest(
            source_info, normalized_settings, budget_bound, batch_id, shared_state
        )
        _register_batch(shared_state, batch_id, output_path, schedule)
        output, ledger_path = _prepare_output(
            output_path,
            source_info,
            manifest,
            shared_state["ledger"],
            shared_state["ledger_snapshot"],
        )
        records, stop_reason = _run_workers(
            output=output,
            ledger_path=ledger_path,
            schedule=schedule,
            source_info=source_info,
            expected_settings=normalized_settings,
        )
        source_hash_after = _tree_sha256(source_info["path"])
        ledger_after = BudgetLedger(
            ledger_path,
            total_dollars=MAX_TOTAL_DOLLARS,
            dev_dollars=None,
            total_seconds=None,
            dev_seconds=None,
            max_calls=MAX_GENERATION_ATTEMPTS,
        ).snapshot()
        _write_json_exclusive(output / "budget.final.json", ledger_after)
        prefix = f"followup:{batch_id}:"
        batch_reservations = {
            key: value
            for key, value in ledger_after["reservations"].items()
            if key.startswith(prefix)
        }
        original_preserved = all(
            ledger_after["reservations"].get(key) == value
            for key, value in source_info["budget"]["reservations"].items()
        )
        summary = {
            "schema_version": 1,
            "output_dir": str(output),
            "batch_id": batch_id,
            "shared_ledger_path": str(ledger_path),
            "shared_ledger_identity": ledger_after.get("ledger_identity"),
            "expected_http_slots": 4,
            "completed_http_slots": len(records),
            "generation_attempts": len(batch_reservations),
            "cumulative_generation_reservations": len(ledger_after["reservations"]),
            "http_error_slots": sum(
                isinstance(item.get("http_status"), int) and item["http_status"] >= 400
                for item in records
            ),
            "max_output_tokens": normalized_settings["max_output_tokens"],
            "spent_or_reserved_cumulative_usd": _ledger_charge(
                ledger_after["reservations"]
            ),
            "original_ledger_reservations_preserved": original_preserved,
            "original_run_hash_unchanged": source_hash_after
            == source_info["tree_sha256"],
            "source_run_tree_sha256_before": source_info["tree_sha256"],
            "source_run_tree_sha256_after": source_hash_after,
            "stop_reason": stop_reason,
            "automatic_retry": False,
            "quality_judgment": "not_performed",
        }
        _write_json_exclusive(output / "summary.json", summary)
        _finish_batch(shared_state, batch_id, ledger_after, summary)
        if not summary["original_ledger_reservations_preserved"]:
            raise FollowupError("공유 ledger의 기존 예약 기록이 변경되었습니다.")
        if not summary["original_run_hash_unchanged"]:
            raise FollowupError("기존 결과 폴더 hash가 실행 전후 달라졌습니다.")
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_followup(args.source_run, args.output, dry_run=args.dry_run)
    except (
        FollowupError,
        OSError,
        ValueError,
        TypeError,
        routing.EvaluationError,
    ) as exc:
        print(f"후속 검증 중단: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
