"""Run the frozen v7 prompt experiment with one shared 120-attempt ledger."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generation.documents import render_document
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.providers import build_managed_model_call
from generation_evaluation.reporting import run_to_dict
from generation_evaluation.runner import run_case

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
EXPERIMENT_ID = "prompt-v7-20261015"
MAX_CALLS = 120
DEVELOPMENT_PROFILES = (
    "examples_answer_scope_v5",
    "examples_answer_scope_v7_readability",
    "examples_answer_scope_v7_completeness",
)
V7_PROFILES = (
    "examples_answer_scope_v7_readability",
    "examples_answer_scope_v7_completeness",
    "examples_answer_scope_v7_combined",
)
FINAL_REPETITIONS = 3
EXPECTED_SNAPSHOT_FINGERPRINT = (
    "9d02a7ba77a340bea017e89ab43e25db62a8cdeef83b2a40c5bbfb203a8eddf7"
)
RUBRIC_FIELDS = (
    "required",
    "critical_required",
    "optional",
    "forbidden",
    "major_forbidden",
    "readability_target",
    "common_readability_rubric",
    "structure_rubric",
    "evidence",
)
SOURCE_PATHS = (
    "generation/config.py",
    "generation/output_schema.py",
    "generation/profiles.py",
    "generation/prompts.py",
    "generation/documents.py",
    "generation/providers.py",
    "generation/presets.py",
    "generation/models.json",
    "generation/experiments.json",
    "generation/service.py",
    "generation/validation.py",
    "generation/types.py",
    "generation_evaluation/runner.py",
    "generation_evaluation/reporting.py",
    "generation_evaluation/types.py",
    "pyproject.toml",
    "uv.lock",
    "generation_evaluation/experiments/prompt-v7-20261015/policy-map.md",
    "generation_evaluation/experiments/prompt-v7-20261015/acceptance.md",
    "generation_evaluation/experiments/prompt-v7-20261015/judge-contract.md",
    "generation_evaluation/experiments/prompt-v7-20261015/summarize.py",
)


class ExperimentError(RuntimeError):
    """A frozen experiment input or restart invariant was violated."""


class CallLimitExceeded(ExperimentError):
    """The global attempt ceiling has already been reserved."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_json(value).encode("utf-8"))


def write_json_immutable(path: Path, value: dict[str, Any]) -> None:
    """Create an artifact once; allow a byte-identical preflight rerun."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ExperimentError(f"고정 manifest가 기존 파일과 다릅니다: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_snapshot(path: Path) -> tuple[dict[str, Any], list[str]]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    required = {"fingerprint", "documents", "document_count"}
    if not isinstance(snapshot, dict) or not required.issubset(snapshot):
        raise ExperimentError(
            "Snapshot에 fingerprint, document_count, documents가 필요합니다."
        )
    rows = snapshot["documents"]
    if not isinstance(rows, list) or len(rows) != snapshot["document_count"]:
        raise ExperimentError("Snapshot 문서 수가 비었거나 document_count와 다릅니다.")
    entries = []
    rendered = []
    for row in rows:
        if not isinstance(row, dict):
            raise ExperimentError("Snapshot 문서는 객체여야 합니다.")
        for field in ("id", "revision_id", "title", "body", "content_hash"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ExperimentError(f"Snapshot 문서의 {field} 값이 잘못되었습니다.")
        revision = row.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ExperimentError("Snapshot 문서 revision은 1 이상의 정수여야 합니다.")
        if digest_bytes(row["body"].encode("utf-8")) != row["content_hash"]:
            raise ExperimentError(f"Snapshot 본문 해시가 맞지 않습니다: {row['id']}")
        entries.append(
            (row["id"], row["revision_id"], row["title"], row["content_hash"])
        )
        rendered.append(render_document(row["id"], row["title"], row["body"], revision))
    expected = digest_bytes(json.dumps(entries, ensure_ascii=False).encode("utf-8"))
    if expected != snapshot["fingerprint"]:
        raise ExperimentError("Snapshot fingerprint와 문서 내용이 일치하지 않습니다.")
    if snapshot["fingerprint"] != EXPECTED_SNAPSHOT_FINGERPRINT:
        raise ExperimentError("이번 비교에 고정된 72개 문서 snapshot이 아닙니다.")
    if snapshot["document_count"] != 72:
        raise ExperimentError("고정 snapshot 문서 수는 72개여야 합니다.")
    return snapshot, rendered


def _validate_rubric(case: dict[str, Any], case_id: str) -> None:
    required_fields = {
        "id",
        "question",
        "category",
        "intent_group",
        "exposure",
        "required",
        "forbidden",
        "common_readability_rubric",
        "structure_rubric",
        "evidence",
    }
    missing = required_fields - case.keys()
    if missing:
        raise ExperimentError(f"{case_id} 문항 필수 필드 누락: {sorted(missing)}")
    for field in ("question", "category", "intent_group", "exposure"):
        if not isinstance(case[field], str) or not case[field].strip():
            raise ExperimentError(
                f"{case_id}.{field}는 비어 있지 않은 문자열이어야 합니다."
            )
    for field in ("required", "critical_required", "optional", "major_forbidden"):
        values = case.get(field, [])
        if not isinstance(values, list) or not all(
            isinstance(item, str) and item.strip() for item in values
        ):
            raise ExperimentError(f"{case_id}.{field}는 문자열 목록이어야 합니다.")
    forbidden = case["forbidden"]
    if not isinstance(forbidden, list) or not all(
        (
            isinstance(item, str)
            and item.strip()
            or isinstance(item, dict)
            and isinstance(item.get("claim"), str)
            and item["claim"].strip()
            and item.get("severity") in {"minor", "major", "critical"}
        )
        for item in forbidden
    ):
        raise ExperimentError(
            f"{case_id}.forbidden은 문자열 주장 또는 claim/severity 객체 목록이어야 합니다."
        )
    if not isinstance(case["common_readability_rubric"], dict):
        raise ExperimentError(f"{case_id}.common_readability_rubric는 객체여야 합니다.")
    readability = case["common_readability_rubric"]
    if not all(
        isinstance(readability.get(key), str) and readability[key].strip()
        for key in ("axis", "pass", "partial", "fail")
    ):
        raise ExperimentError(
            f"{case_id}.common_readability_rubric 기준이 잘못되었습니다."
        )
    structure = case["structure_rubric"]
    if not isinstance(structure, dict) or not all(
        isinstance(structure.get(key), str) and structure[key].strip()
        for key in ("target", "pass", "partial", "fail")
    ):
        raise ExperimentError(f"{case_id}.structure_rubric의 기준이 잘못되었습니다.")
    evidence = case["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ExperimentError(f"{case_id}.evidence가 비어 있습니다.")
    for item in evidence:
        if not isinstance(item, dict) or item.get("source") not in {
            "published_snapshot",
            "runtime_contract",
        }:
            raise ExperimentError(
                f"{case_id}.evidence 항목에 정확한 문서 근거가 필요합니다."
            )
        fields = (
            ("document_id", "title", "section", "quote")
            if item["source"] == "published_snapshot"
            else ("path", "quote")
        )
        if not all(
            isinstance(item.get(field), str) and item[field].strip() for field in fields
        ):
            raise ExperimentError(
                f"{case_id}.evidence에 {item['source']} 출처 정보가 필요합니다."
            )


def load_case_file(path: Path, expected_split: str) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ExperimentError(f"문항 파일은 JSON 객체여야 합니다: {path}")
    if (
        data.get("experiment_id") != EXPERIMENT_ID
        or data.get("split") != expected_split
    ):
        raise ExperimentError(
            f"{path.name}의 experiment_id/split이 실행 파일과 맞지 않습니다."
        )
    if not isinstance(data.get("scope"), str) or EXPERIMENT_ID not in data["scope"]:
        raise ExperimentError(f"{path.name} scope가 고정 실험을 가리키지 않습니다.")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != 12:
        raise ExperimentError(f"{path.name}에는 정확히 12개 문항이 필요합니다.")
    if not isinstance(data.get("shared_rubric"), dict):
        raise ExperimentError(f"{path.name}에 shared_rubric 객체가 필요합니다.")
    shared = data["shared_rubric"]
    compact_shared = ("content", "common_readability", "structure_adherence")
    detailed_shared = (
        "response_contract",
        "content_judgment",
        "evidence_rule",
        "structure_adherence",
        "tone_and_scope",
    )
    if all(key in shared for key in compact_shared):
        if not all(
            isinstance(shared.get(key), str) and shared[key].strip()
            for key in compact_shared
        ):
            raise ExperimentError(f"{path.name} shared_rubric 설명이 잘못되었습니다.")
    elif all(key in shared for key in detailed_shared):
        if not all(
            isinstance(shared.get(key), str) and shared[key].strip()
            for key in detailed_shared
        ):
            raise ExperimentError(f"{path.name} shared_rubric 설명이 잘못되었습니다.")
        shared_readability = shared.get("common_readability")
        if not isinstance(shared_readability, dict) or not all(
            isinstance(shared_readability.get(key), str)
            and shared_readability[key].strip()
            for key in ("axis", "pass", "partial", "fail")
        ):
            raise ExperimentError(f"{path.name} 공통 가독성 루브릭이 잘못되었습니다.")
        labels = shared.get("judgment_labels")
        if labels != ["pass", "partial", "fail", "uncertain"]:
            raise ExperimentError(
                f"{path.name} 판정 라벨은 사전 고정된 4종이어야 합니다."
            )
    else:
        raise ExperimentError(
            f"{path.name} shared_rubric 필드가 고정된 형식과 맞지 않습니다."
        )
    ids = []
    groups = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ExperimentError(f"{path.name} 문항 ID가 잘못되었습니다.")
        _validate_rubric(case, case["id"])
        ids.append(case["id"])
        groups.append(case["intent_group"])
    if len(set(ids)) != len(ids):
        raise ExperimentError(f"{path.name} 문항 ID가 중복되었습니다.")
    if len(set(groups)) != len(groups):
        raise ExperimentError(f"{path.name} 문항의 intent_group이 중복되었습니다.")
    if data.get("case_count") != 12:
        raise ExperimentError(f"{path.name} case_count가 12와 맞지 않습니다.")
    if data.get("snapshot_document_count") != 72:
        raise ExperimentError(f"{path.name} snapshot_document_count가 72여야 합니다.")
    if expected_split == "selection":
        expected_categories = {
            "capability_intro": 2,
            "short_single_fact": 1,
            "ordered_multi_step_procedure": 2,
            "conditional_alternatives": 2,
            "partial_answer_and_unknown": 1,
            "out_of_scope_general_knowledge": 1,
            "ambiguous_work_context": 1,
            "composite_incident_response": 2,
        }
        actual_categories = Counter(case["category"] for case in cases)
        if actual_categories != expected_categories:
            raise ExperimentError(
                f"선정셋 category 배분이 고정 기준과 다릅니다: {dict(actual_categories)}"
            )
    return data


def load_pricing(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "source_url": "https://developers.openai.com/api/docs/pricing",
        "checked_at": "2026-10-15",
        "provider": "openai",
        "model_name": "gpt-6-luna",
        "input_usd_per_million": 0.25,
        "output_usd_per_million": 0.75,
    }
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
        raise ExperimentError(
            "공식 API 가격 정보가 확인된 2026-10-15 메타데이터와 다릅니다."
        )
    if (
        not isinstance(data.get("estimation_note"), str)
        or not data["estimation_note"].strip()
    ):
        raise ExperimentError("가격 추정 한계를 밝히는 estimation_note가 필요합니다.")
    return data


def validate_settings(root: Path):
    settings = load_runtime_settings(root)
    config = settings.config
    actual = {
        "provider": config.provider.value,
        "model_name": config.model_name,
        "reasoning_effort": config.reasoning_effort,
        "max_output_tokens": config.max_output_tokens,
        "timeout_seconds": config.timeout_seconds,
        "temperature": config.temperature,
        "output_mode": config.output_mode.value,
        "prompt_profile": settings.prompt_profile,
    }
    expected = {
        "provider": "openai",
        "model_name": "gpt-6-luna",
        "reasoning_effort": "xhigh",
        "max_output_tokens": 16384,
        "timeout_seconds": 180,
        "temperature": None,
        "output_mode": "prompt_json",
        "prompt_profile": "examples_answer_scope_v5",
    }
    if actual != expected:
        raise ExperimentError(f"모델 설정이 고정 실험 설정과 다릅니다: {actual}")
    return settings


def rubric_fingerprint(dev_data: dict[str, Any], final_data: dict[str, Any]) -> str:
    def extract(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "shared_rubric": data["shared_rubric"],
            "cases": [
                {
                    "id": case["id"],
                    **{
                        field: case.get(
                            field,
                            []
                            if field
                            in {"critical_required", "optional", "major_forbidden"}
                            else None,
                        )
                        for field in RUBRIC_FIELDS
                    },
                }
                for case in data["cases"]
            ],
        }

    return digest_json(
        {"development": extract(dev_data), "selection": extract(final_data)}
    )


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def validate_evidence_sources(
    development: dict[str, Any],
    selection: dict[str, Any],
    snapshot: dict[str, Any],
) -> None:
    documents = {row["id"]: row for row in snapshot["documents"]}
    development_groups = {case["intent_group"] for case in development["cases"]}
    selection_groups = {case["intent_group"] for case in selection["cases"]}
    if development_groups & selection_groups:
        raise ExperimentError(
            "개발·선정 문항의 고정 intent_group은 서로 분리해야 합니다."
        )
    for dataset in (development, selection):
        for case in dataset["cases"]:
            for evidence in case["evidence"]:
                quote = _normalized_text(evidence["quote"])
                if evidence["source"] == "published_snapshot":
                    row = documents.get(evidence["document_id"])
                    if row is None or row["title"] != evidence["title"]:
                        raise ExperimentError(
                            f"{case['id']}의 근거 문서 ID/제목이 snapshot과 다릅니다."
                        )
                    if quote not in _normalized_text(row["body"]):
                        raise ExperimentError(
                            f"{case['id']}의 근거 인용이 snapshot 원문에 없습니다: {evidence['document_id']}"
                        )
                else:
                    source_path = Path(evidence["path"])
                    if source_path.is_absolute() or ".." in source_path.parts:
                        raise ExperimentError(
                            f"{case['id']} runtime_contract path가 안전하지 않습니다."
                        )
                    resolved = ROOT / source_path
                    if not resolved.is_file():
                        raise ExperimentError(
                            f"{case['id']} runtime_contract 파일이 없습니다."
                        )
                    if quote not in _normalized_text(
                        resolved.read_text(encoding="utf-8")
                    ):
                        raise ExperimentError(
                            f"{case['id']} runtime_contract 인용이 원문에 없습니다."
                        )


def build_global_manifest(
    snapshot_path: Path,
    snapshot: dict[str, Any],
    development_path: Path,
    development_data: dict[str, Any],
    selection_path: Path,
    selection_data: dict[str, Any],
    pricing_path: Path,
    pricing: dict[str, Any],
    settings,
) -> dict[str, Any]:
    if development_data.get("snapshot_fingerprint") != snapshot["fingerprint"]:
        raise ExperimentError(
            "개발 문항이 고정 snapshot fingerprint와 일치하지 않습니다."
        )
    if selection_data.get("snapshot_fingerprint") != snapshot["fingerprint"]:
        raise ExperimentError(
            "선정 문항이 고정 snapshot fingerprint와 일치하지 않습니다."
        )
    source_hashes = {path: digest_file(ROOT / path) for path in SOURCE_PATHS}
    source_hashes[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest_file(
        Path(__file__)
    )
    profile_hashes = {
        profile: digest_bytes(
            build_profile_prompt("해시 확인", [], profile).system.encode("utf-8")
        )
        for profile in ("examples_answer_scope_v5", *V7_PROFILES)
    }
    config = settings.config
    config_data = {
        "provider": config.provider.value,
        "model_name": config.model_name,
        "reasoning_effort": config.reasoning_effort,
        "max_output_tokens": config.max_output_tokens,
        "timeout_seconds": config.timeout_seconds,
        "temperature": config.temperature,
        "output_mode": config.output_mode.value,
    }
    return {
        "experiment_id": EXPERIMENT_ID,
        "maximum_generation_attempts": MAX_CALLS,
        "snapshot_path": str(snapshot_path.resolve()),
        "development_cases_declared_snapshot_path": development_data.get(
            "snapshot_path"
        ),
        "selection_cases_declared_snapshot_path": selection_data.get("snapshot_path"),
        "snapshot_sha256": digest_file(snapshot_path),
        "snapshot_fingerprint": snapshot["fingerprint"],
        "snapshot_document_count": snapshot["document_count"],
        "development_cases_sha256": digest_file(development_path),
        "selection_cases_sha256": digest_file(selection_path),
        "rubric_sha256": rubric_fingerprint(development_data, selection_data),
        "model_configuration": config_data,
        "pricing_sha256": digest_file(pricing_path),
        "pricing_metadata": pricing,
        "profile_system_sha256": profile_hashes,
        "source_sha256": source_hashes,
    }


def cost_reservation(
    prompt_json: bytes, max_output_tokens: int, pricing: dict[str, Any]
) -> tuple[int, float]:
    # UTF-8 bytes are a conservative planning proxy from prior experiments, not a tokenizer proof.
    input_token_estimate = len(prompt_json) + 512
    dollars = (
        input_token_estimate * pricing["input_usd_per_million"]
        + max_output_tokens * pricing["output_usd_per_million"]
    ) / 1_000_000
    return input_token_estimate, dollars


def cost_for_result(
    input_tokens: int | None,
    output_tokens: int | None,
    reserved_usd: float,
    pricing: dict[str, Any],
) -> tuple[bool, float]:
    """Use measured usage only when both token counts exist; otherwise keep reserve."""
    valid_usage = all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in (input_tokens, output_tokens)
    )
    if not valid_usage:
        return False, reserved_usd
    cost = (
        input_tokens * pricing["input_usd_per_million"]
        + output_tokens * pricing["output_usd_per_million"]
    ) / 1_000_000
    return True, cost


@dataclass(frozen=True)
class RequestSlot:
    key: str
    ordinal: int
    case: dict[str, Any]
    profile: str
    repetition: int
    prompt_sha256: str
    reserved_usd: float
    prompt_bytes: bytes


def _slot(
    case: dict[str, Any],
    profile: str,
    repetition: int,
    ordinal: int,
    documents: list[str],
    settings,
    pricing: dict[str, Any],
    stage: str,
) -> RequestSlot:
    prompt = build_profile_prompt(case["question"], documents, profile)
    encoded = json.dumps(
        {"system": prompt.system, "user": prompt.user},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    _input_estimate, reserve = cost_reservation(
        encoded, settings.config.max_output_tokens, pricing
    )
    case_key = case["id"]
    key = f"{stage}:{repetition}:{case_key}:{profile}"
    return RequestSlot(
        key=key,
        ordinal=ordinal,
        case=case,
        profile=profile,
        repetition=repetition,
        prompt_sha256=digest_bytes(encoded),
        reserved_usd=reserve,
        prompt_bytes=encoded,
    )


def build_slots(
    stage: str,
    development_data: dict[str, Any],
    selection_data: dict[str, Any],
    documents: list[str],
    settings,
    pricing: dict[str, Any],
    selected_profile: str | None,
) -> list[RequestSlot]:
    slots: list[RequestSlot] = []
    if stage == "development":
        cases = development_data["cases"]
        for index, case in enumerate(cases):
            ordered = (
                DEVELOPMENT_PROFILES[index % len(DEVELOPMENT_PROFILES) :]
                + DEVELOPMENT_PROFILES[: index % len(DEVELOPMENT_PROFILES)]
            )
            for profile in ordered:
                slots.append(
                    _slot(
                        case,
                        profile,
                        1,
                        len(slots),
                        documents,
                        settings,
                        pricing,
                        stage,
                    )
                )
        expected = 36
    elif stage == "combination":
        cases = development_data["cases"]
        for case in cases:
            slots.append(
                _slot(
                    case,
                    "examples_answer_scope_v7_combined",
                    1,
                    len(slots),
                    documents,
                    settings,
                    pricing,
                    stage,
                )
            )
        expected = 12
    elif stage == "final":
        if selected_profile not in V7_PROFILES:
            raise ExperimentError(
                "최종 단계 selected_profile은 v7 후보 중 하나여야 합니다."
            )
        for repetition in range(1, FINAL_REPETITIONS + 1):
            for index, case in enumerate(selection_data["cases"]):
                profiles = ("examples_answer_scope_v5", selected_profile)
                if (index + repetition) % 2:
                    profiles = profiles[::-1]
                for profile in profiles:
                    slots.append(
                        _slot(
                            case,
                            profile,
                            repetition,
                            len(slots),
                            documents,
                            settings,
                            pricing,
                            stage,
                        )
                    )
        expected = 72
    else:
        raise ExperimentError(f"알 수 없는 실험 단계입니다: {stage}")
    if len(slots) != expected:
        raise ExperimentError(
            f"{stage} 요청 슬롯 수가 {expected}가 아닙니다: {len(slots)}"
        )
    if len({slot.key for slot in slots}) != len(slots):
        raise ExperimentError(f"{stage} 요청 슬롯 키가 중복되었습니다.")
    return slots


def _development_manifest_sha(output_root: Path) -> str:
    path = output_root / "stages" / "development" / "stage-manifest.json"
    if not path.is_file():
        raise ExperimentError("개발 단계 stage-manifest.json을 먼저 실행해야 합니다.")
    return digest_file(path)


def _require_stage_complete(output_root: Path, stage: str, expected: int) -> None:
    database = output_root / "ledger.sqlite3"
    if not database.is_file():
        raise ExperimentError(f"{stage} 단계 공유 ledger가 없습니다.")
    uri = f"file:{database.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            finished = conn.execute(
                "SELECT COUNT(*) FROM slots WHERE stage = ? AND status = 'finished'",
                (stage,),
            ).fetchone()[0]
            started = conn.execute(
                "SELECT COUNT(*) FROM slots WHERE stage = ? AND status = 'started'",
                (stage,),
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise ExperimentError(f"{stage} 단계 ledger를 읽을 수 없습니다.") from exc
    if finished != expected or started:
        raise ExperimentError(
            f"{stage} 단계는 {expected}개 슬롯이 모두 완료되어야 합니다 (완료={finished}, 불확실={started})."
        )


def _load_decision(
    path: Path, stage: str, output_root: Path
) -> tuple[dict[str, Any], str | None]:
    decision = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decision, dict):
        raise ExperimentError("검토 결정 파일은 JSON 객체여야 합니다.")
    for field in ("decision_id", "development_manifest_sha256", "rationale"):
        if not isinstance(decision.get(field), str) or not decision[field].strip():
            raise ExperimentError(f"검토 결정에 {field}가 필요합니다.")
    if decision["development_manifest_sha256"] != _development_manifest_sha(
        output_root
    ):
        raise ExperimentError(
            "검토 결정이 현재 고정 개발 manifest에 연결되지 않았습니다."
        )
    _require_stage_complete(output_root, "development", 36)
    if stage == "combination":
        flags = (
            "readability_approved",
            "completeness_approved",
            "combination_approved",
        )
        if not all(decision.get(flag) is True for flag in flags):
            raise ExperimentError(
                "결합 단계는 두 독립 후보가 모두 검토 통과하고 결합 승인되어야 합니다."
            )
        selected = None
    else:
        if decision.get("final_approved") is not True:
            raise ExperimentError(
                "최종 단계는 명시적인 final_approved 검토가 필요합니다."
            )
        selected = decision.get("selected_profile")
        if selected not in V7_PROFILES:
            raise ExperimentError("선정 프로필은 등록된 v7 후보여야 합니다.")
        required_approval = {
            "examples_answer_scope_v7_readability": "readability_approved",
            "examples_answer_scope_v7_completeness": "completeness_approved",
            "examples_answer_scope_v7_combined": "combination_approved",
        }[selected]
        if decision.get(required_approval) is not True:
            raise ExperimentError(
                f"최종 후보의 검토 승인 필드가 필요합니다: {required_approval}"
            )
        if selected == "examples_answer_scope_v7_combined":
            if decision.get("combination_approved") is not True:
                raise ExperimentError("combined 후보는 조합 승인 결정이 필요합니다.")
            stage_dir = output_root / "stages" / "combination"
            if not (stage_dir / "stage-manifest.json").is_file():
                raise ExperimentError(
                    "combined 최종 평가는 결합 단계를 먼저 완료해야 합니다."
                )
            _require_stage_complete(output_root, "combination", 12)
    return decision, selected


def build_stage_manifest(
    stage: str,
    slots: list[RequestSlot],
    global_manifest: dict[str, Any],
    decision: dict[str, Any] | None,
    decision_path: Path | None,
    settings,
) -> dict[str, Any]:
    profiles = list(dict.fromkeys(slot.profile for slot in slots))
    return {
        "experiment_id": EXPERIMENT_ID,
        "stage": stage,
        "planned_generation_attempts": len(slots),
        "maximum_generation_attempts_global": MAX_CALLS,
        "profiles": profiles,
        "repetitions": sorted({slot.repetition for slot in slots}),
        "ordered_slots": [
            {
                "slot": slot.key,
                "ordinal": slot.ordinal,
                "prompt_sha256": slot.prompt_sha256,
                "reserved_usd": round(slot.reserved_usd, 10),
            }
            for slot in slots
        ],
        "estimated_stage_reserved_usd": round(
            sum(slot.reserved_usd for slot in slots), 10
        ),
        "global_manifest_sha256": digest_json(global_manifest),
        "global_fingerprints": {
            "snapshot_sha256": global_manifest["snapshot_sha256"],
            "snapshot_fingerprint": global_manifest["snapshot_fingerprint"],
            "development_cases_sha256": global_manifest["development_cases_sha256"],
            "selection_cases_sha256": global_manifest["selection_cases_sha256"],
            "rubric_sha256": global_manifest["rubric_sha256"],
            "model_configuration": global_manifest["model_configuration"],
            "source_sha256": global_manifest["source_sha256"],
            "profile_system_sha256": global_manifest["profile_system_sha256"],
            "pricing_sha256": global_manifest["pricing_sha256"],
        },
        "decision_sha256": digest_file(decision_path) if decision_path else None,
        "decision": decision,
        "call_policy": "one reservation before each single attempt; no retries; started slots are never called again",
        "output_schema": "existing JSON object with exactly one string answer key",
        "rubric_sent_to_model": False,
        "model_configuration": global_manifest["model_configuration"],
        "provider_timeout_seconds": settings.config.timeout_seconds,
    }


class AttemptLedger:
    """SQLite-backed atomic reservation ledger shared by every experiment stage."""

    def __init__(self, path: Path, max_calls: int = MAX_CALLS) -> None:
        if (
            isinstance(max_calls, bool)
            or not isinstance(max_calls, int)
            or max_calls <= 0
        ):
            raise ValueError("max_calls는 양의 정수여야 합니다.")
        self.path = Path(path)
        self.max_calls = max_calls
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stages (
                    stage TEXT PRIMARY KEY,
                    manifest_sha256 TEXT NOT NULL,
                    manifest_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS slots (
                    slot_key TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('started', 'finished')),
                    reserved_usd REAL NOT NULL CHECK(reserved_usd >= 0),
                    started_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT,
                    record_json TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_key TEXT,
                    stage TEXT NOT NULL,
                    event TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def initialize(self, global_fingerprint: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value FROM metadata WHERE key = 'global_fingerprint'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO metadata(key, value) VALUES ('global_fingerprint', ?)",
                    (global_fingerprint,),
                )
            elif row[0] != global_fingerprint:
                conn.rollback()
                raise ExperimentError(
                    "기존 공유 ledger의 snapshot·문항·루브릭·설정·코드 fingerprint가 달라 재개를 거부합니다."
                )
            conn.commit()

    def register_stage(self, stage: str, manifest: dict[str, Any]) -> None:
        manifest_json = canonical_json(manifest)
        manifest_sha = digest_bytes(manifest_json.encode("utf-8"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT manifest_sha256, manifest_json FROM stages WHERE stage = ?",
                (stage,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO stages(stage, manifest_sha256, manifest_json) VALUES (?, ?, ?)",
                    (stage, manifest_sha, manifest_json),
                )
            elif existing != (manifest_sha, manifest_json):
                conn.rollback()
                raise ExperimentError(
                    f"{stage} 단계 manifest가 이미 고정되어 다릅니다."
                )
            conn.commit()

    @contextmanager
    def run_lock(self) -> Iterator[None]:
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+b") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ExperimentError("다른 v7 실행기가 요청을 처리 중입니다.") from exc
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def status(self, slot_key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM slots WHERE slot_key = ?", (slot_key,)
            ).fetchone()
        return None if row is None else row[0]

    def claim(
        self, stage: str, slot_key: str, ordinal: int, reserved_usd: float
    ) -> str:
        if reserved_usd < 0:
            raise ValueError("예약 비용은 0 이상이어야 합니다.")
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT stage, ordinal, status, reserved_usd FROM slots WHERE slot_key = ?",
                (slot_key,),
            ).fetchone()
            if existing is not None:
                if (
                    existing[0] != stage
                    or existing[1] != ordinal
                    or abs(existing[3] - reserved_usd) > 1e-12
                ):
                    conn.rollback()
                    raise ExperimentError(f"기존 슬롯 정의가 다릅니다: {slot_key}")
                conn.commit()
                return "finished" if existing[2] == "finished" else "uncertain"
            count = conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
            if count >= self.max_calls:
                conn.rollback()
                raise CallLimitExceeded(
                    f"전체 생성 시도 상한 {self.max_calls}회 예약을 마쳤습니다."
                )
            conn.execute(
                """INSERT INTO slots(
                    slot_key, stage, ordinal, status, reserved_usd, started_at_utc
                ) VALUES (?, ?, ?, 'started', ?, ?)""",
                (slot_key, stage, ordinal, reserved_usd, now),
            )
            conn.execute(
                "INSERT INTO events(slot_key, stage, event, created_at_utc, details_json) VALUES (?, ?, 'started', ?, ?)",
                (
                    slot_key,
                    stage,
                    now,
                    canonical_json({"reserved_usd": reserved_usd, "ordinal": ordinal}),
                ),
            )
            conn.commit()
        return "claimed"

    def finish(self, slot_key: str, record: dict[str, Any]) -> None:
        encoded = canonical_json(record)
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT stage, status FROM slots WHERE slot_key = ?", (slot_key,)
            ).fetchone()
            if row is None or row[1] != "started":
                conn.rollback()
                raise ExperimentError(
                    f"완료 상태로 바꿀 수 없는 슬롯입니다: {slot_key}"
                )
            conn.execute(
                "UPDATE slots SET status = 'finished', finished_at_utc = ?, record_json = ? WHERE slot_key = ?",
                (now, encoded, slot_key),
            )
            conn.execute(
                "INSERT INTO events(slot_key, stage, event, created_at_utc, details_json) VALUES (?, ?, 'finished', ?, ?)",
                (
                    slot_key,
                    row[0],
                    now,
                    canonical_json(
                        {
                            "status": record.get("result", {}).get("status")
                            if isinstance(record.get("result"), dict)
                            else record.get("error_type"),
                            "usage_known": record.get("usage_known"),
                            "cost_estimate_usd": record.get("cost_estimate_usd"),
                        }
                    ),
                ),
            )
            conn.commit()

    def stage_rows(
        self, stage: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT slot_key, ordinal, status, reserved_usd, started_at_utc, finished_at_utc, record_json FROM slots WHERE stage = ? ORDER BY ordinal",
                (stage,),
            ).fetchall()
            events = conn.execute(
                "SELECT slot_key, event, created_at_utc, details_json FROM events WHERE stage = ? ORDER BY event_id",
                (stage,),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
        records = []
        for row in rows:
            if row[2] == "finished":
                records.append(json.loads(row[6]))
            else:
                records.append(
                    {
                        "slot": row[0],
                        "ordinal": row[1],
                        "status": "uncertain_started_no_automatic_retry",
                        "reserved_usd": row[3],
                        "started_at_utc": row[4],
                    }
                )
        event_records = [
            {
                "slot": row[0],
                "event": row[1],
                "created_at_utc": row[2],
                **json.loads(row[3]),
            }
            for row in events
        ]
        return records, event_records, total

    def invalid_prompt_slots(self, stage: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT slot_key, record_json FROM slots WHERE stage = ? AND status = 'finished'",
                (stage,),
            ).fetchall()
        return [
            slot_key
            for slot_key, record_json in rows
            if not json.loads(record_json).get("prompt_hash_matches_manifest", False)
        ]


def export_stage(
    ledger: AttemptLedger, stage: str, stage_dir: Path, expected: int
) -> dict[str, Any]:
    rows, events, total = ledger.stage_rows(stage)
    finished = sum(
        1 for row in rows if row.get("status") != "uncertain_started_no_automatic_retry"
    )
    uncertain = len(rows) - finished
    summary = {
        "stage": stage,
        "planned_slots": expected,
        "finished_slots": finished,
        "uncertain_started_slots": uncertain,
        "not_started_slots": expected - len(rows),
        "total_reserved_attempts_all_stages": total,
        "global_maximum_attempts": MAX_CALLS,
        "finished_cost_estimate_usd": round(
            sum(
                float(row.get("cost_estimate_usd", 0))
                for row in rows
                if row.get("status") != "uncertain_started_no_automatic_retry"
            ),
            10,
        ),
        "claimed_reservation_total_usd": round(
            sum(float(row.get("reserved_usd", 0)) for row in rows), 10
        ),
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    write_jsonl_atomic(stage_dir / "responses.jsonl", rows)
    write_jsonl_atomic(stage_dir / "events.jsonl", events)
    write_json_atomic(stage_dir / "summary.json", summary)
    return summary


def prepare(
    snapshot_path: Path,
    development_path: Path,
    selection_path: Path,
    pricing_path: Path,
    settings,
    stage: str,
    output_root: Path,
    decision_path: Path | None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[RequestSlot],
    dict[str, Any] | None,
    str | None,
    list[str],
    dict[str, Any],
]:
    snapshot_path = snapshot_path.resolve()
    development_path = development_path.resolve()
    selection_path = selection_path.resolve()
    pricing_path = pricing_path.resolve()
    snapshot, documents = load_snapshot(snapshot_path)
    development = load_case_file(development_path, "development")
    selection = load_case_file(selection_path, "selection")
    validate_evidence_sources(development, selection, snapshot)
    pricing = load_pricing(pricing_path)
    global_manifest = build_global_manifest(
        snapshot_path,
        snapshot,
        development_path,
        development,
        selection_path,
        selection,
        pricing_path,
        pricing,
        settings,
    )
    decision = None
    selected_profile = None
    if stage in {"combination", "final"}:
        if decision_path is None:
            raise ExperimentError(
                f"{stage} 단계에는 독립 검토 결정 파일 --decision이 필요합니다."
            )
        decision_path = decision_path.resolve()
        decision, selected_profile = _load_decision(decision_path, stage, output_root)
    slots = build_slots(
        stage,
        development,
        selection,
        documents,
        settings,
        pricing,
        selected_profile,
    )
    manifest = build_stage_manifest(
        stage,
        slots,
        global_manifest,
        decision,
        decision_path,
        settings,
    )
    return (
        global_manifest,
        manifest,
        slots,
        decision,
        selected_profile,
        documents,
        pricing,
    )


async def run_stage(
    slots: list[RequestSlot],
    stage: str,
    stage_dir: Path,
    ledger: AttemptLedger,
    settings,
    documents: list[str],
    pricing: dict[str, Any],
) -> dict[str, Any]:
    client = None
    try:
        with ledger.run_lock():
            pending = [slot for slot in slots if ledger.status(slot.key) is None]
            invalid_slots = ledger.invalid_prompt_slots(stage)
            if invalid_slots:
                raise ExperimentError(
                    f"프롬프트 해시 불일치 슬롯이 있어 추가 호출을 중단합니다: {invalid_slots}"
                )
            if pending:
                if not os.environ.get("OPENAI_API_KEY", "").strip():
                    raise ExperimentError("실행 전에 OPENAI_API_KEY를 설정해야 합니다.")
                client = build_managed_model_call(settings.config)
            for slot in slots:
                state = ledger.claim(stage, slot.key, slot.ordinal, slot.reserved_usd)
                if state != "claimed":
                    print(f"{slot.key} {state}", flush=True)
                    continue
                run = run_case(
                    slot.case["id"],
                    settings.config,
                    slot.case["question"],
                    # The same frozen documents are already fingerprinted into prompt bytes.
                    documents,
                    client,
                    prompt_profile=slot.profile,
                )
                prompt_hash_matches = run.prompt_sha256 == slot.prompt_sha256
                result = run.result
                usage_known, cost = cost_for_result(
                    result.input_tokens if result is not None else None,
                    result.output_tokens if result is not None else None,
                    slot.reserved_usd,
                    pricing,
                )
                record = run_to_dict(run)
                record.update(
                    {
                        "experiment_id": EXPERIMENT_ID,
                        "stage": stage,
                        "question": slot.case["question"],
                        "category": slot.case["category"],
                        "intent_group": slot.case["intent_group"],
                        "exposure": slot.case["exposure"],
                        "slot": slot.key,
                        "ordinal": slot.ordinal,
                        "repetition": slot.repetition,
                        "expected_prompt_sha256": slot.prompt_sha256,
                        "prompt_hash_matches_manifest": prompt_hash_matches,
                        "usage_known": usage_known,
                        "reserved_usd": slot.reserved_usd,
                        "cost_estimate_usd": cost,
                    }
                )
                ledger.finish(slot.key, record)
                export_stage(ledger, stage, stage_dir, len(slots))
                if not prompt_hash_matches:
                    raise ExperimentError(
                        f"실행 프롬프트 해시가 사전 고정과 달라 중단합니다: {slot.key}"
                    )
                print(
                    slot.key,
                    result.status.value if result else run.error_type,
                    flush=True,
                )
    except Exception:
        export_stage(ledger, stage, stage_dir, len(slots))
        raise
    finally:
        if client is not None:
            await client.aclose()
    return export_stage(ledger, stage, stage_dir, len(slots))


def _write_global_manifest(output_root: Path, manifest: dict[str, Any]) -> None:
    write_json_immutable(output_root / "global-manifest.json", manifest)


async def async_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument(
        "--development-cases", type=Path, default=HERE / "development.json"
    )
    parser.add_argument("--selection-cases", type=Path, default=HERE / "selection.json")
    parser.add_argument("--pricing", type=Path, default=HERE / "pricing.json")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="All stages share this run root and ledger.sqlite3.",
    )
    parser.add_argument(
        "--stage", choices=("development", "combination", "final"), required=True
    )
    parser.add_argument(
        "--decision",
        type=Path,
        help="Required for combination/final; binds reviewed choice to development manifest SHA-256.",
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)

    settings = validate_settings(ROOT)
    (
        global_manifest,
        stage_manifest,
        slots,
        _decision,
        _selected,
        documents,
        pricing,
    ) = prepare(
        args.snapshot,
        args.development_cases,
        args.selection_cases,
        args.pricing,
        settings,
        args.stage,
        args.output.resolve(),
        args.decision,
    )
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    stage_dir = output_root / "stages" / args.stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_sha = digest_json(stage_manifest)
    write_json_immutable(
        stage_dir / "preflight-manifest.json",
        {
            "global_fingerprint": digest_json(global_manifest),
            "stage_fingerprint": stage_sha,
            "stage_manifest": stage_manifest,
            "preflight_only": True,
        },
    )
    _write_global_manifest(output_root, global_manifest)
    if args.preflight_only:
        print(json.dumps(stage_manifest, ensure_ascii=False, indent=2))
        return

    ledger = AttemptLedger(output_root / "ledger.sqlite3")
    ledger.initialize(digest_json(global_manifest))
    ledger.register_stage(args.stage, stage_manifest)
    write_json_immutable(stage_dir / "stage-manifest.json", stage_manifest)

    summary = await run_stage(
        slots,
        args.stage,
        stage_dir,
        ledger,
        settings,
        documents,
        pricing,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    try:
        asyncio.run(async_main())
    except (ExperimentError, CallLimitExceeded, OSError, ValueError, TypeError) as exc:
        print(f"실험 중단: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
