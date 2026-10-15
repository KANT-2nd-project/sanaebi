"""Run the frozen gate-versus-shadow HTTP comparison with a bounded ledger.

The runner deliberately drives the existing ASGI ``/ask`` endpoint. Each mode
uses its own subprocess, temporary SQLite database, fixed per-case document
snapshot, classifier artifact, and content-bearing trace directory.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt

MODES = ("gate", "shadow")
REPEATS = (1, 2)
EXPECTED_COUNTS = {
    "business_guidance": 16,
    "partial_or_insufficient": 8,
    "out_of_scope": 6,
    "lookup_or_execution": 4,
    "ambiguous": 4,
    "mixed_guidance_and_execution": 2,
}
EXPECTED_QUESTIONS = {
    "annual_leave_casual": "우리 회사 연차 규정에 대해 알려줘",
    "annual_leave_polite": "우리 회사 연차 규정에 대해 알려주세요.",
    "privacy_incident": "고객 정보가 든 메일을 잘못 보냈을 때 개인정보 사고 신고와 수신자 대응 절차를 알려주세요.",
    "kimchi_recipe": "김치찌개 만드는 법 알려줘",
}
SOURCE_PATHS = (
    "app/fastapi_main.py",
    "app/dependencies.py",
    "app/questions/service.py",
    "app/questions/router.py",
    "app/answering/router.py",
    "app/answering/adapter.py",
    "app/diagnostics/trace.py",
    "app/classification/predictor.py",
    "app/errors.py",
    "app/schemas.py",
    "app/documents/context.py",
    "app/documents/repository.py",
    "generation/config.py",
    "generation/models.json",
    "generation/presets.py",
    "generation/profiles.py",
    "generation/prompts.py",
    "generation/providers.py",
    "generation/service.py",
    "generation/types.py",
    "generation/validation.py",
    "generation/output_schema.py",
    "generation/strategies.py",
    "generation_evaluation/budget.py",
    "contracts/classification.py",
    "uv.lock",
    "scripts/evaluate_routing_policy.py",
)
MODEL_ID = "gpt-6-luna"
PROFILE = "examples_answer_scope_v1"
TOTAL_SECONDS = 7200.0
MAX_DOLLARS = 5.0
MAX_GENERATION_ATTEMPTS = 160
TRACE_HEADER = "X-Trace-Id"


class EvaluationError(RuntimeError):
    """Input, reproducibility, accounting, or trace integrity failure."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"JSON 입력을 읽을 수 없습니다: {path}") from exc


def _canonical_hash(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _validate_cases(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise EvaluationError("cases 파일은 schema_version 1이어야 합니다.")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 40:
        raise EvaluationError("평가 문항은 정확히 40개여야 합니다.")

    ids: set[str] = set()
    counts = dict.fromkeys(EXPECTED_COUNTS, 0)
    found_questions: set[str] = set()
    snapshots = {"base", "added", "revised", "withdrawn"}
    for case in cases:
        if not isinstance(case, dict):
            raise EvaluationError("각 평가 문항은 JSON 객체여야 합니다.")
        case_id = case.get("id")
        question = case.get("question")
        category = case.get("category")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise EvaluationError("문항 id가 비어 있거나 중복되었습니다.")
        if not isinstance(question, str) or not question.strip():
            raise EvaluationError(f"{case_id}: 질문이 비어 있습니다.")
        if not isinstance(category, str) or category not in counts:
            raise EvaluationError(f"{case_id}: 허용되지 않은 category입니다.")
        if (
            not isinstance(case.get("provenance"), str)
            or not case["provenance"].strip()
        ):
            raise EvaluationError(f"{case_id}: provenance가 필요합니다.")
        if (
            not isinstance(case.get("snapshot"), str)
            or case["snapshot"] not in snapshots
        ):
            raise EvaluationError(
                f"{case_id}: snapshot은 {sorted(snapshots)} 중 하나여야 합니다."
            )
        ids.add(case_id)
        counts[category] += 1
        if question in EXPECTED_QUESTIONS.values():
            found_questions.add(question)

    if counts != EXPECTED_COUNTS:
        raise EvaluationError(f"문항 유형 구성이 다릅니다: {counts}")
    if found_questions != set(EXPECTED_QUESTIONS.values()):
        raise EvaluationError("기존 문제 4문항 문구가 고정값과 다릅니다.")
    return cases


def _validate_rubric(value: Any, cases: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise EvaluationError("rubric 파일은 schema_version 1이어야 합니다.")
    entries = value.get("cases")
    if isinstance(entries, dict):
        normalized_entries = []
        for case_id, details in entries.items():
            if not isinstance(case_id, str) or not isinstance(details, dict):
                raise EvaluationError(
                    "rubric.cases의 각 문항 기준은 문자열 ID의 JSON 객체여야 합니다."
                )
            if "id" in details and details["id"] != case_id:
                raise EvaluationError(
                    f"{case_id}: rubric 기준 내부 ID가 항목 ID와 다릅니다."
                )
            normalized_entries.append({**details, "id": case_id})
        entries = normalized_entries
    if not isinstance(entries, list):
        raise EvaluationError("rubric.cases는 ID 객체 또는 목록이어야 합니다.")
    case_ids = [item.get("id") for item in cases]
    rubric_ids = [item.get("id") for item in entries if isinstance(item, dict)]
    if (
        len(rubric_ids) != len(entries)
        or len(rubric_ids) != len(case_ids)
        or len(set(rubric_ids)) != len(case_ids)
    ):
        raise EvaluationError(
            "rubric는 각 문항마다 중복 없이 판정 기준을 가져야 합니다."
        )
    if set(rubric_ids) != set(case_ids):
        raise EvaluationError("rubric 문항 ID가 cases와 일치하지 않습니다.")
    for entry in entries:
        if not isinstance(entry.get("allowed_actions"), list):
            raise EvaluationError(f"{entry['id']}: allowed_actions 목록이 필요합니다.")
        if not isinstance(entry.get("required_claims"), list):
            raise EvaluationError(f"{entry['id']}: required_claims 목록이 필요합니다.")
        if not isinstance(entry.get("forbidden_claims"), list):
            raise EvaluationError(f"{entry['id']}: forbidden_claims 목록이 필요합니다.")
        if not isinstance(entry.get("evidence"), list):
            raise EvaluationError(f"{entry['id']}: evidence 목록이 필요합니다.")


def _validate_snapshots(value: Any) -> dict[str, list[dict[str, Any]]]:
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or set(value) != {"schema_version", "base", "added", "revised", "withdrawn"}
    ):
        raise EvaluationError(
            "snapshots에는 schema_version 1과 base/added/revised/withdrawn이 필요합니다."
        )
    for name in ("base", "added", "revised", "withdrawn"):
        documents = value[name]
        if not isinstance(documents, list):
            raise EvaluationError(f"snapshots.{name}는 문서 목록이어야 합니다.")
        ids: set[str] = set()
        for doc in documents:
            if not isinstance(doc, dict):
                raise EvaluationError(
                    f"snapshots.{name}의 문서는 JSON 객체여야 합니다."
                )
            doc_id, title, body, revision = (
                doc.get("knowledge_id"),
                doc.get("title"),
                doc.get("body"),
                doc.get("revision"),
            )
            if not all(isinstance(x, str) and x.strip() for x in (doc_id, title, body)):
                raise EvaluationError(
                    f"snapshots.{name}: ID/제목/본문은 비어 있지 않은 문자열이어야 합니다."
                )
            if doc_id in ids:
                raise EvaluationError(
                    f"snapshots.{name}: 문서 ID가 중복되었습니다: {doc_id}"
                )
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 1
            ):
                raise EvaluationError(
                    f"snapshots.{name}: revision은 1 이상의 정수여야 합니다."
                )
            ids.add(doc_id)
    return {name: value[name] for name in ("base", "added", "revised", "withdrawn")}


def _validate_pricing(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("model") != MODEL_ID:
        raise EvaluationError("pricing.model은 gpt-6-luna여야 합니다.")
    source = value.get("source_url")
    parsed = urlparse(source) if isinstance(source, str) else None
    if (
        not parsed
        or parsed.scheme != "https"
        or parsed.hostname != "developers.openai.com"
        or not parsed.path.startswith("/api/docs/pricing")
    ):
        raise EvaluationError("OpenAI 공식 가격 문서의 HTTPS URL이 필요합니다.")
    verified_at = value.get("verified_at")
    if not isinstance(verified_at, str):
        raise EvaluationError("pricing.verified_at 날짜가 필요합니다.")
    try:
        date.fromisoformat(verified_at)
    except ValueError as exc:
        raise EvaluationError(
            "pricing.verified_at은 YYYY-MM-DD 형식이어야 합니다."
        ) from exc
    for field in ("input_usd_per_million", "output_usd_per_million"):
        number = value.get(field)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise EvaluationError(f"pricing.{field} 숫자가 필요합니다.")
        if not math.isfinite(number) or number < 0:
            raise EvaluationError(f"pricing.{field}은 유한한 0 이상의 값이어야 합니다.")
    if (
        value.get("pricing_basis")
        != "standard_long_context_all_input_at_cache_write_upper_bound"
    ):
        raise EvaluationError(
            "pricing_basis는 cache-write 상한 요율을 명시해야 합니다."
        )
    return value


def _classifier_files(path: Path) -> dict[str, str]:
    path = path.expanduser().resolve()
    required = ("metadata.json", "config.json", "model.safetensors")
    if not path.is_dir() or any(not (path / name).is_file() for name in required):
        raise EvaluationError(f"KoELECTRA 저장본이 완전하지 않습니다: {path}")
    return {
        item.relative_to(path).as_posix(): _sha256_file(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def _git_command(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvaluationError("git manifest 정보를 읽을 수 없습니다.") from exc
    return result.stdout


def build_manifest(
    *,
    cases_path: Path,
    rubric_path: Path,
    snapshots_path: Path,
    classifier_path: Path,
    pricing_path: Path,
    cases: list[dict[str, Any]],
    rubric: dict[str, Any],
    snapshots: dict[str, list[dict[str, Any]]],
    pricing: dict[str, Any],
) -> dict[str, Any]:
    settings = load_runtime_settings(ROOT)
    config = asdict(settings.config)
    expected = {
        "provider": "openai",
        "model_name": MODEL_ID,
        "timeout_seconds": 180,
        "max_output_tokens": 4096,
        "reasoning_effort": "xhigh",
        "temperature": None,
        "output_mode": "prompt_json",
    }
    normalized_config = {
        key: getattr(settings.config, key).value
        if hasattr(getattr(settings.config, key), "value")
        else getattr(settings.config, key)
        for key in expected
    }
    if normalized_config != expected or settings.prompt_profile != PROFILE:
        raise EvaluationError("현재 모델 설정이 고정된 평가 구성과 다릅니다.")

    code_hashes = {}
    tracked_code = {
        name
        for name in _git_command(
            "ls-files", "app", "generation", "contracts", "scripts"
        ).splitlines()
        if name.endswith(".py")
    }
    tracked_code.update(SOURCE_PATHS)
    for relative in sorted(tracked_code):
        source = ROOT / relative
        if not source.is_file():
            raise EvaluationError(f"manifest 코드 파일이 없습니다: {relative}")
        code_hashes[relative] = _sha256_file(source)
    dirty_diff = _git_command("diff", "HEAD", "--binary")
    untracked = _git_command("ls-files", "--others", "--exclude-standard").splitlines()
    untracked_code = {
        name: _sha256_file(ROOT / name)
        for name in sorted(untracked)
        if name.endswith(".py")
        and (name.startswith(("app/", "generation/", "contracts/", "scripts/")))
        and (ROOT / name).is_file()
    }
    return {
        "schema_version": 1,
        "created_at": None,
        "git_head": _git_command("rev-parse", "HEAD").strip(),
        "git_branch": _git_command("branch", "--show-current").strip(),
        "dirty_diff_sha256": _sha256_bytes(dirty_diff.encode("utf-8")),
        "code_sha256": code_hashes,
        "untracked_code_sha256": untracked_code,
        "uv_lock_sha256": _sha256_file(ROOT / "uv.lock"),
        "model_settings": normalized_config,
        "prompt_profile": settings.prompt_profile,
        "model_settings_sha256": _canonical_hash(
            {"config": config, "profile": settings.prompt_profile}
        ),
        "classifier_path": str(classifier_path.expanduser().resolve()),
        "classifier_files_sha256": _classifier_files(classifier_path),
        "cases_sha256": _sha256_file(cases_path),
        "rubric_sha256": _sha256_file(rubric_path),
        "snapshots_sha256": _sha256_file(snapshots_path),
        "pricing_sha256": _sha256_file(pricing_path),
        "cases": [case["id"] for case in cases],
        "rubric_sha256_semantic": _canonical_hash(rubric),
        "snapshot_document_counts": {
            key: len(value) for key, value in snapshots.items()
        },
        "routing_modes": list(MODES),
        "repeats": list(REPEATS),
        "schedule_seed": 20261015,
        "budget": {
            "total_seconds_from_first_http_request": TOTAL_SECONDS,
            "total_dollars": MAX_DOLLARS,
            "max_generation_attempts": MAX_GENERATION_ATTEMPTS,
        },
        "pricing": pricing,
    }


def estimate_upper_bound(
    messages: list[Any], max_output_tokens: int, pricing: dict[str, Any]
) -> float:
    """Estimate input conservatively as UTF-8 bytes plus per-message overhead."""
    input_upper = sum(
        len(str(message.content).encode("utf-8")) + 256 for message in messages
    )
    return (
        input_upper * pricing["input_usd_per_million"]
        + max_output_tokens * pricing["output_usd_per_million"]
    ) / 1_000_000


def estimate_observed_cost(
    trace: dict[str, Any], pricing: dict[str, Any]
) -> float | None:
    generation = next(
        (step for step in trace.get("steps", []) if step.get("stage") == "생성 판정"),
        None,
    )
    if not isinstance(generation, dict):
        return None
    input_tokens = generation.get("input_tokens")
    output_tokens = generation.get("output_tokens")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (input_tokens, output_tokens)
    ):
        return None
    # Use the cache-write ceiling for all input tokens; this cannot understate
    # spend when cache-read/write detail is absent from provider usage.
    return (
        input_tokens * pricing["input_usd_per_million"]
        + output_tokens * pricing["output_usd_per_million"]
    ) / 1_000_000


def _budgeted_answer(
    question: str,
    snapshot: Any,
    *,
    answer: Any,
    active: dict[str, Any],
    ledger: Any,
    settings: Any,
    pricing: dict[str, Any],
) -> str:
    """Reserve the call before entering GenerationAnswerer exactly once."""
    from generation.documents import render_document
    from generation.providers import to_messages
    from generation_evaluation.budget import BudgetExceeded

    slot_id = active.get("slot_id")
    if not isinstance(slot_id, str):
        raise EvaluationError("생성 호출에 평가 slot_id가 연결되지 않았습니다.")
    deadline = active.get("deadline_epoch")
    start_epoch = active.get("experiment_started_at_epoch")
    if start_epoch is None or deadline is None or time.time() >= deadline:
        active["budget_blocked"] = True
        active["error_type"] = "time_budget_exhausted_before_generation"
        raise BudgetExceeded("실험 시간 한도 만료")

    documents = [
        render_document(d.knowledge_id, d.title, d.body, d.revision)
        for d in snapshot.documents
    ]
    prompt = build_profile_prompt(question, documents, settings.prompt_profile)
    estimate = estimate_upper_bound(
        to_messages(prompt), settings.config.max_output_tokens, pricing
    )
    try:
        ledger.reserve(slot_id, "final", estimate)
    except BudgetExceeded as exc:
        active["budget_blocked"] = True
        active["error_type"] = str(exc)
        raise

    active["generation_attempted"] = True
    active["generation_reserved"] = True
    active["reserved_dollars"] = estimate
    active["prompt_sha256"] = hashlib.sha256(
        json.dumps(
            {"system": prompt.system, "user": prompt.user},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return answer(question, snapshot)


def build_schedule(
    cases: list[dict[str, Any]], seed: int = 20261015
) -> list[dict[str, Any]]:
    pairs = [(case, repeat) for repeat in REPEATS for case in cases]
    random.Random(seed).shuffle(pairs)
    schedule = []
    for case, repeat in pairs:
        pair_order = list(MODES)
        if random.Random(seed + repeat + sum(case["id"].encode())).randrange(2):
            pair_order.reverse()
        for mode in pair_order:
            schedule.append(
                {
                    "slot_id": f"{mode}:{case['id']}:r{repeat}",
                    "mode": mode,
                    "case_id": case["id"],
                    "repeat": repeat,
                    "case": case,
                }
            )
    return schedule


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationError(
                f"{path}:{line_number}: 기록이 손상되었습니다."
            ) from exc
        if not isinstance(value, dict):
            raise EvaluationError(f"{path}:{line_number}: JSON 객체가 아닙니다.")
        records.append(value)
    return records


def _load_trace(trace_directory: Path, trace_id: str | None) -> dict[str, Any] | None:
    if not trace_id:
        return None
    for path in sorted(trace_directory.glob("*.jsonl"), reverse=True):
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("trace_id") == trace_id:
                return record
    return None


def _trace_file(trace_directory: Path, trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    for path in sorted(trace_directory.glob("*.jsonl"), reverse=True):
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("trace_id") == trace_id:
                return str(path)
    return None


def _worker_environment(
    mode: str, runtime: Path, classifier_path: Path, trace: Path
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "SANAEBI_ROUTING_MODE": mode,
            "SANAEBI_CLASSIFIER_PATH": str(classifier_path.expanduser().resolve()),
            "SANAEBI_DOCUMENT_DB": str(runtime / f"{mode}.sqlite3"),
            "SANAEBI_ANSWER_PROVIDER": "openai",
            "TRACE_DIR": str(trace),
            "TRACE_FULL_PROMPT": "0",
            "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", ""),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _read_worker_line(
    process: subprocess.Popen[str], mode: str, stderr_path: Path | None = None
) -> dict[str, Any]:
    if process.stdout is None:
        raise EvaluationError(f"{mode} worker stdout를 열 수 없습니다.")
    line = process.stdout.readline()
    if not line:
        stderr = (
            stderr_path.read_text(encoding="utf-8", errors="replace")
            if stderr_path and stderr_path.exists()
            else ""
        )
        raise EvaluationError(f"{mode} worker가 응답하지 않았습니다: {stderr[-1000:]}")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"{mode} worker 응답이 JSON이 아닙니다.") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"{mode} worker 응답 형식이 올바르지 않습니다.")
    return value


def _check_trace_integrity(trace: dict[str, Any], mode: str) -> dict[str, Any]:
    steps = trace.get("steps")
    if not isinstance(steps, list):
        raise EvaluationError("요청 trace에 steps가 없습니다.")
    classification = next(
        (
            step
            for step in steps
            if isinstance(step, dict) and step.get("stage") == "분류"
        ),
        None,
    )
    if not isinstance(classification, dict):
        raise EvaluationError("요청 trace에 분류 단계가 없습니다.")
    required = (
        "routing_mode",
        "label_source",
        "classification_status",
        "classification_elapsed_seconds",
        "processing_path",
        "generation_attempted",
    )
    missing = [field for field in required if field not in classification]
    if missing:
        raise EvaluationError(f"trace 분류 메타데이터가 누락되었습니다: {missing}")
    if classification["routing_mode"] != mode:
        raise EvaluationError("trace routing_mode와 격리 프로세스가 다릅니다.")
    if classification["label_source"] != "model":
        raise EvaluationError("/ask 평가에서 분류 출처가 model이 아닙니다.")
    if not isinstance(classification["generation_attempted"], bool):
        raise EvaluationError("generation_attempted 값이 boolean이 아닙니다.")
    return classification


def _check_generation_reservation_join(
    classification: dict[str, Any], result: dict[str, Any]
) -> None:
    traced_attempt = classification["generation_attempted"]
    reserved_attempt = bool(result.get("generation_reserved"))
    if traced_attempt != reserved_attempt and not result.get("budget_blocked"):
        raise EvaluationError("trace/원장 생성 시도 여부가 일치하지 않음")


def _validate_resume_slots(
    started_slots: set[str],
    results: dict[str, dict[str, Any]],
    schedule: list[dict[str, Any]],
) -> None:
    expected = {item["slot_id"] for item in schedule}
    if (set(results) | started_slots) - expected:
        raise EvaluationError("실행 기록에 현재 평가 계획에 없는 slot_id가 있습니다.")
    uncertain = sorted(started_slots - set(results))
    if uncertain:
        raise EvaluationError(
            "요청 시작 기록만 남은 불확실 슬롯이 있어 자동 재호출을 중단합니다: "
            + ", ".join(uncertain[:8])
        )


def _prepare_output(output: Path, manifest: dict[str, Any], resume: bool) -> None:
    if output.exists():
        if not resume:
            raise EvaluationError(
                f"출력 경로가 이미 있습니다. --resume 없이 덮어쓰지 않습니다: {output}"
            )
        manifest_path = output / "manifest.json"
        if not manifest_path.is_file():
            raise EvaluationError("재개 출력 폴더에 manifest.json이 없습니다.")
        stored = _read_json(manifest_path)
        expected = dict(manifest)
        expected["created_at"] = stored.get("created_at")
        if stored != expected:
            raise EvaluationError(
                "코드·설정·문항·루브릭·문서 manifest가 달라 재개할 수 없습니다."
            )
        return
    if resume:
        raise EvaluationError("--resume 출력 폴더가 없습니다.")
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(manifest)
    manifest["created_at"] = time.time()
    with (output / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def _initial_run_state(output: Path, resume: bool) -> dict[str, Any]:
    path = output / "run-state.json"
    if resume:
        state = _read_json(path)
        if not isinstance(state, dict) or (
            state.get("started_at_epoch") is not None
            and (
                isinstance(state.get("started_at_epoch"), bool)
                or not isinstance(state.get("started_at_epoch"), (int, float))
            )
        ):
            raise EvaluationError("실험 재개 상태가 손상되었습니다.")
        return state
    state = {
        "started_at_epoch": None,
        "started_at": None,
        "ledger_identity": None,
    }
    with path.open("x", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
    return state


def _save_run_state(output: Path, state: dict[str, Any]) -> None:
    path = output / "run-state.json"
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _run_level_lock(output: Path):
    """Hold a nonblocking lock across manifest, ledger, and result operations."""
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output.parent / f".{output.name}.routing-policy.lock"
    handle = lock_path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise EvaluationError(
            "같은 평가 출력 경로를 다른 실행이 사용 중입니다."
        ) from exc
    return handle


def _open_or_verify_ledger(
    *,
    output: Path,
    resume: bool,
    run_state: dict[str, Any],
    results: dict[str, dict[str, Any]],
    schedule: list[dict[str, Any]],
):
    from generation_evaluation.budget import BudgetLedger

    ledger_path = output / "budget.json"
    if resume and not ledger_path.is_file():
        raise EvaluationError(
            "재개 원장 budget.json이 없어 비용 상한을 검증할 수 없습니다."
        )
    ledger = BudgetLedger(
        ledger_path,
        total_dollars=MAX_DOLLARS,
        dev_dollars=None,
        total_seconds=None,
        dev_seconds=None,
        max_calls=MAX_GENERATION_ATTEMPTS,
    )
    if resume:
        identity = ledger.get_identity()
        if not identity or identity != run_state.get("ledger_identity"):
            raise EvaluationError(
                "예산 원장이 삭제되었거나 교체되어 재개를 거부했습니다."
            )
        ledger.bind_limits()
    else:
        ledger.bind_limits()
        identity = ledger.ensure_identity()
        run_state["ledger_identity"] = identity
        _save_run_state(output, run_state)

    reservations = ledger.snapshot().get("reservations", {})
    if not isinstance(reservations, dict):
        raise EvaluationError("예산 원장 reservations 형식이 올바르지 않습니다.")
    expected_slots = {item["slot_id"] for item in schedule}
    if set(reservations) - expected_slots:
        raise EvaluationError("예산 원장에 현재 계획에 없는 생성 예약이 있습니다.")
    for slot_id, reservation in reservations.items():
        record = results.get(slot_id)
        if not isinstance(reservation, dict) or not isinstance(record, dict):
            raise EvaluationError(
                f"원장 예약 {slot_id}가 완료 응답과 연결되지 않습니다."
            )
        if not record.get("generation_reserved"):
            raise EvaluationError(
                f"원장 예약 {slot_id}의 결과 기록이 일치하지 않습니다."
            )
    for slot_id, record in results.items():
        if record.get("generation_reserved") and slot_id not in reservations:
            raise EvaluationError(
                f"생성 결과 {slot_id}에 대응하는 예산 예약이 없습니다."
            )
    return ledger


def _run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    if args.dry_run:
        return _run_evaluation_locked(args)
    lock = _run_level_lock(args.output)
    try:
        return _run_evaluation_locked(args)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _run_evaluation_locked(args: argparse.Namespace) -> dict[str, Any]:
    cases_value = _read_json(args.cases)
    cases = _validate_cases(cases_value)
    rubric = _read_json(args.rubric)
    _validate_rubric(rubric, cases)
    snapshots = _validate_snapshots(_read_json(args.snapshots))
    pricing = _validate_pricing(_read_json(args.pricing))
    classifier_path = args.classifier_path.expanduser().resolve()
    manifest = build_manifest(
        cases_path=args.cases,
        rubric_path=args.rubric,
        snapshots_path=args.snapshots,
        classifier_path=classifier_path,
        pricing_path=args.pricing,
        cases=cases,
        rubric=rubric,
        snapshots=snapshots,
        pricing=pricing,
    )
    if args.dry_run:
        max_bound = 0.0
        settings = load_runtime_settings(ROOT)
        from generation.documents import render_document
        from generation.providers import to_messages

        for case in cases:
            docs = [
                render_document(
                    doc["knowledge_id"], doc["title"], doc["body"], doc["revision"]
                )
                for doc in snapshots[case["snapshot"]]
            ]
            prompt = build_profile_prompt(
                case["question"], docs, settings.prompt_profile
            )
            bound = estimate_upper_bound(to_messages(prompt), 4096, pricing)
            max_bound = max(max_bound, bound)
        return {
            "dry_run": True,
            "case_count": len(cases),
            "request_slots": len(build_schedule(cases)),
            "maximum_single_call_reservation_usd": max_bound,
            "worst_case_all_160_calls_usd": max_bound * MAX_GENERATION_ATTEMPTS,
            "budget_usd": MAX_DOLLARS,
            "classifier_path": str(classifier_path),
            "manifest_sha256": _canonical_hash(manifest),
        }

    output = args.output.expanduser().resolve()
    _prepare_output(output, manifest, args.resume)
    run_state = _initial_run_state(output, args.resume)
    results_path = output / "results.jsonl"
    events_path = output / "events.jsonl"
    schedule = build_schedule(cases)
    result_records = _read_jsonl(results_path)
    by_slot = {record.get("slot_id"): record for record in result_records}
    if None in by_slot or len(by_slot) != len(result_records):
        raise EvaluationError("results.jsonl에 slot_id가 누락되었거나 중복되었습니다.")
    events = _read_jsonl(events_path)
    started_slots = {
        event.get("slot_id") for event in events if event.get("event") == "started"
    }
    completed_slots = set(by_slot)
    _validate_resume_slots(started_slots, by_slot, schedule)

    ledger = _open_or_verify_ledger(
        output=output,
        resume=args.resume,
        run_state=run_state,
        results=by_slot,
        schedule=schedule,
    )
    missing = [slot for slot in schedule if slot["slot_id"] not in completed_slots]
    if not missing:
        return {
            "complete": True,
            "completed_slots": len(completed_slots),
            "output": str(output),
        }

    runtime = output / "runtime"
    traces = output / "traces"
    runtime.mkdir(exist_ok=True)
    for mode in MODES:
        (traces / mode).mkdir(parents=True, exist_ok=True)

    ledger_path = output / "budget.json"
    if any(record.get("budget_blocked") for record in result_records):
        return {
            "complete": False,
            "completed_slots": len(completed_slots),
            "expected_slots": len(schedule),
            "generation_attempts": len(ledger.snapshot().get("reservations", {})),
            "stop_reason": "이전 실행에서 예산 한도에 도달해 재개 호출을 중단했습니다.",
            "output": str(output),
        }

    worker_config_path = output / "worker-config.json"
    worker_config = {
        "snapshots": str(args.snapshots.resolve()),
        "pricing": str(args.pricing.resolve()),
        "ledger": str(ledger_path),
    }
    # This file contains local paths only; no API key is read or copied.
    worker_config_text = json.dumps(worker_config, ensure_ascii=False, indent=2) + "\n"
    if worker_config_path.exists():
        if (
            not args.resume
            or worker_config_path.read_text(encoding="utf-8") != worker_config_text
        ):
            raise EvaluationError(
                "기존 worker-config.json이 입력과 달라 재개할 수 없습니다."
            )
    else:
        with worker_config_path.open("x", encoding="utf-8") as handle:
            handle.write(worker_config_text)

    workers: dict[str, subprocess.Popen[str]] = {}
    worker_stderr: dict[str, Path] = {}
    worker_log_handles = {}
    try:
        for mode in MODES:
            stderr_path = runtime / f"{mode}.stderr.log"
            worker_stderr[mode] = stderr_path
            log_handle = stderr_path.open("a", encoding="utf-8")
            worker_log_handles[mode] = log_handle
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--worker-mode",
                mode,
                "--worker-config",
                str(worker_config_path),
                "--worker-runtime",
                str(runtime),
                "--worker-trace",
                str(traces / mode),
                "--worker-classifier",
                str(classifier_path),
            ]
            workers[mode] = subprocess.Popen(
                command,
                cwd=ROOT,
                env=_worker_environment(mode, runtime, classifier_path, traces / mode),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log_handle,
                text=True,
                bufsize=1,
            )
            ready = _read_worker_line(workers[mode], mode, stderr_path)
            if ready.get("worker_ready") is not True:
                raise EvaluationError(f"{mode} worker 초기화에 실패했습니다: {ready}")

        stop_reason = None
        for slot in missing:
            now = time.time()
            if run_state["started_at_epoch"] is None:
                run_state["started_at_epoch"] = now
                run_state["started_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)
                )
                _save_run_state(output, run_state)
            elapsed = now - run_state["started_at_epoch"]
            if elapsed >= TOTAL_SECONDS:
                stop_reason = "2시간 실험 시간 한도 도달"
                break
            slot = dict(slot)
            slot["deadline_epoch"] = run_state["started_at_epoch"] + TOTAL_SECONDS
            slot["experiment_started_at_epoch"] = run_state["started_at_epoch"]
            _append_jsonl(
                events_path,
                {"event": "started", "slot_id": slot["slot_id"], "at_epoch": now},
            )
            worker = workers[slot["mode"]]
            if worker.stdin is None:
                raise EvaluationError(f"{slot['mode']} worker stdin을 열 수 없습니다.")
            worker.stdin.write(json.dumps(slot, ensure_ascii=False) + "\n")
            worker.stdin.flush()
            reply = _read_worker_line(worker, slot["mode"], worker_stderr[slot["mode"]])
            if reply.get("slot_id") != slot["slot_id"]:
                raise EvaluationError("worker가 다른 평가 슬롯의 결과를 반환했습니다.")
            trace_id = reply.get("trace_id")
            trace = _load_trace(traces / slot["mode"], trace_id)
            measurement_error = None
            classification = None
            if trace is None:
                measurement_error = "trace_missing"
            else:
                try:
                    classification = _check_trace_integrity(trace, slot["mode"])
                    if trace.get("status") != reply.get("http_status"):
                        raise EvaluationError("trace와 HTTP 응답 status가 다릅니다.")
                    _check_generation_reservation_join(classification, reply)
                except EvaluationError as exc:
                    measurement_error = str(exc)
            if measurement_error:
                reply["measurement_error"] = measurement_error
            reply.update(
                {
                    "case_id": slot["case_id"],
                    "question": slot["case"]["question"],
                    "category": slot["case"]["category"],
                    "provenance": slot["case"]["provenance"],
                    "snapshot": slot["case"]["snapshot"],
                    "repeat": slot["repeat"],
                    "mode": slot["mode"],
                    "trace_id": trace_id,
                    "trace_file": _trace_file(traces / slot["mode"], trace_id),
                    "trace_summary": classification,
                    "generation_attempted": (
                        classification.get("generation_attempted")
                        if classification is not None
                        else None
                    ),
                    "experiment_elapsed_seconds": round(
                        time.time() - run_state["started_at_epoch"], 3
                    ),
                }
            )
            _append_jsonl(results_path, reply)
            _append_jsonl(
                events_path,
                {
                    "event": "completed",
                    "slot_id": slot["slot_id"],
                    "at_epoch": time.time(),
                },
            )
            by_slot[slot["slot_id"]] = reply
            if reply.get("budget_blocked"):
                stop_reason = reply.get("error_type", "예산 예약 실패")
                break
            if measurement_error:
                stop_reason = "요청 trace 연결 또는 필수 메타데이터가 누락됨"
                break
            if reply.get("http_status", 0) >= 500 and reply.get("budget_blocked"):
                stop_reason = "예산 한도 도달"
                break

        completed = len(by_slot)
        expected = len(schedule)
        return {
            "complete": completed == expected,
            "completed_slots": completed,
            "expected_slots": expected,
            "generation_attempts": len(ledger.snapshot().get("reservations", {})),
            "spent_or_reserved_usd": sum(
                float(item.get("charged_dollars", item.get("reserved_dollars", 0)))
                for item in ledger.snapshot().get("reservations", {}).values()
            ),
            "experiment_elapsed_seconds": (
                round(time.time() - run_state["started_at_epoch"], 3)
                if run_state["started_at_epoch"] is not None
                else 0
            ),
            "stop_reason": stop_reason,
            "output": str(output),
        }
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
        for handle in worker_log_handles.values():
            handle.close()


def _worker_main(args: argparse.Namespace) -> int:
    # Environment has already been isolated by the parent before this import.
    import hashlib
    from types import MappingProxyType

    from fastapi.testclient import TestClient

    from app import fastapi_main
    from app.documents.context import DocumentContext, DocumentContextSnapshot
    from generation.presets import load_runtime_settings
    from generation_evaluation.budget import BudgetLedger

    config = _read_json(Path(args.worker_config))
    snapshots = _validate_snapshots(_read_json(Path(config["snapshots"])))
    pricing = _validate_pricing(_read_json(Path(config["pricing"])))
    ledger = BudgetLedger(
        Path(config["ledger"]),
        total_dollars=MAX_DOLLARS,
        dev_dollars=None,
        total_seconds=None,
        dev_seconds=None,
        max_calls=MAX_GENERATION_ATTEMPTS,
    )
    settings = load_runtime_settings(ROOT)
    active: dict[str, Any] = {}

    class FixedSnapshotProvider:
        def snapshot(self):
            name = active.get("snapshot")
            if name not in snapshots:
                return DocumentContextSnapshot(())
            docs = []
            for doc in snapshots[name]:
                doc_id = doc["knowledge_id"]
                docs.append(
                    DocumentContext(
                        document_id=doc_id,
                        knowledge_id=doc_id,
                        revision_id=f"{doc_id}-r{doc['revision']}",
                        revision=doc["revision"],
                        title=doc["title"],
                        body=doc["body"],
                        source_reference=f"document:{doc_id}",
                        content_hash=hashlib.sha256(
                            doc["body"].encode("utf-8")
                        ).hexdigest(),
                        metadata=MappingProxyType({}),
                    )
                )
            return DocumentContextSnapshot(tuple(docs))

    with TestClient(fastapi_main.app, raise_server_exceptions=False) as client:
        if fastapi_main.app.state.routing_mode != args.worker_mode:
            raise EvaluationError(
                "앱 lifespan이 요청한 routing mode를 적용하지 않았습니다."
            )
        fastapi_main.app.state.document_provider = FixedSnapshotProvider()
        answerer = fastapi_main.app.state.answerer
        original_answer = answerer.answer

        def budgeted_answer(question, snapshot):
            return _budgeted_answer(
                question,
                snapshot,
                answer=original_answer,
                active=active,
                ledger=ledger,
                settings=settings,
                pricing=pricing,
            )

        answerer.answer = budgeted_answer
        print(json.dumps({"worker_ready": True, "mode": args.worker_mode}), flush=True)
        for line in sys.stdin:
            try:
                slot = json.loads(line)
                active.clear()
                active.update(
                    slot_id=slot["slot_id"],
                    snapshot=slot["case"]["snapshot"],
                    deadline_epoch=slot["deadline_epoch"],
                    experiment_started_at_epoch=slot["experiment_started_at_epoch"],
                    budget_blocked=False,
                )
                start = time.perf_counter()
                response = client.post(
                    "/ask", json={"question": slot["case"]["question"]}
                )
                elapsed = time.perf_counter() - start
                trace_id = response.headers.get(TRACE_HEADER)
                trace = _load_trace(Path(args.worker_trace), trace_id)
                actual_estimate = (
                    estimate_observed_cost(trace, pricing) if trace else None
                )
                if active.get("generation_attempted"):
                    # Missing usage keeps the conservative reservation charged.
                    ledger.settle(slot["slot_id"], actual_estimate)
                result = {
                    "slot_id": slot["slot_id"],
                    "trace_id": trace_id,
                    "http_status": response.status_code,
                    "response": response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else None,
                    "request_elapsed_seconds": round(elapsed, 3),
                    "generation_reserved": bool(active.get("generation_reserved")),
                    "reserved_dollars": active.get("reserved_dollars"),
                    "usage_cost_upper_estimate_dollars": actual_estimate,
                    "prompt_sha256": active.get("prompt_sha256"),
                    "budget_blocked": bool(active.get("budget_blocked")),
                    "error_type": active.get("error_type"),
                }
                if active.get("budget_blocked"):
                    result["error_type"] = active.get("error_type") or "budget_blocked"
                print(
                    json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True
                )
            except Exception as exc:  # noqa: BLE001 - protocol must fail closed, no retry
                print(
                    json.dumps(
                        {
                            "slot_id": slot.get("slot_id")
                            if isinstance(locals().get("slot"), dict)
                            else None,
                            "worker_error": type(exc).__name__,
                            "error_type": "worker_protocol_error",
                            "budget_blocked": False,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=False)
    parser.add_argument("--rubric", type=Path, required=False)
    parser.add_argument("--snapshots", type=Path, required=False)
    parser.add_argument("--classifier-path", type=Path, required=False)
    parser.add_argument(
        "--output", type=Path, default=Path("tmp/routing-policy-2026-10-15")
    )
    parser.add_argument("--pricing", type=Path, required=False)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-mode", choices=MODES, help=argparse.SUPPRESS)
    parser.add_argument("--worker-config", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-runtime", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-trace", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-classifier", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.worker:
        if not all(
            (
                args.worker_mode,
                args.worker_config,
                args.worker_runtime,
                args.worker_trace,
                args.worker_classifier,
            )
        ):
            parser.error("worker arguments are incomplete")
        return _worker_main(args)
    missing = [
        name
        for name in ("cases", "rubric", "snapshots", "classifier_path", "pricing")
        if getattr(args, name) is None
    ]
    if missing:
        parser.error(
            "필수 인자 누락: "
            + ", ".join("--" + name.replace("_", "-") for name in missing)
        )
    if args.dry_run and (args.resume or args.output.exists()):
        parser.error("--dry-run은 출력 폴더를 생성하거나 재개하지 않습니다.")
    if not args.dry_run and not os.environ.get("OPENAI_API_KEY", "").strip():
        parser.error(
            "실험 API key가 없습니다. OPENAI_API_KEY를 실행 환경에 전달하세요."
        )
    try:
        result = _run_evaluation(args)
    except (EvaluationError, OSError, ValueError) as exc:
        print(f"평가 중단: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
