"""Run the frozen RAG v5/v6/v7 readability comparison without retries.

The input directory is also the durable run directory. It must contain
inputs.json, rubric.json, and a verified pricing.json before the first model
call. Responses and exact prompts are stored one file per slot.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

from langchain_core.messages import BaseMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import RunnableLambda

from app.answering import adapter as answerer_adapter
from app.answering.input import AnswerInput
from generation.advisory import ClassificationContext
from generation.presets import RuntimeSettings, load_runtime_settings
from generation.providers import model_response_from_ai_message
from generation.service import _build_prompt_values
from generation.types import GenerationResult, GenerationStatus, ModelResponse
from generation_evaluation.budget import BudgetExceeded, BudgetLedger

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "rag-readability-20261016"
MAX_GENERATION_CALLS = 24

CODE_PATHS = (
    "generation_evaluation/rag_readability.py",
    "generation_evaluation/budget.py",
    "app/answering/adapter.py",
    "app/answering/input.py",
    "app/diagnostics/trace.py",
    "contracts/classification.py",
    "generation/advisory.py",
    "generation/config.py",
    "generation/documents.py",
    "generation/evidence.py",
    "generation/output_schema.py",
    "generation/presets.py",
    "generation/profile_registry.py",
    "generation/profile_texts.py",
    "generation/profiles.py",
    "generation/prompts.py",
    "generation/providers.py",
    "generation/service.py",
    "generation/types.py",
    "generation/validation.py",
    "app/classification/predictor.py",
    "app/documents/context.py",
    "app/questions/service.py",
    "app/settings.py",
)


class ReadabilityExperimentError(RuntimeError):
    """The frozen experiment cannot safely proceed or resume."""


@dataclass(frozen=True)
class Candidate:
    key: str
    profile: str


@dataclass
class _Capture:
    slot: dict[str, Any] | None = None
    messages: dict[str, str] | None = None
    model_response: ModelResponse | None = None
    generation_result: GenerationResult | None = None
    prompt_mismatch: bool = False
    provider_response_raw: dict[str, Any] | None = None


def _candidates() -> tuple[Candidate, Candidate, Candidate]:
    """Resolve profile identifiers from the runtime registry at execution time."""
    try:
        from generation.profiles import (
            RAG_PROMPT_PROFILE,
            RAG_READABILITY_V6_PROFILE,
            RAG_READABILITY_V7_PROFILE,
        )
    except ImportError as exc:
        raise ReadabilityExperimentError(
            "RAG 기준·v6·v7 프로필 상수가 generation.profiles에 등록되어야 합니다."
        ) from exc

    return (
        Candidate("reference", RAG_PROMPT_PROFILE),
        Candidate("v6_readability", RAG_READABILITY_V6_PROFILE),
        Candidate("v7_readability", RAG_READABILITY_V7_PROFILE),
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ReadabilityExperimentError(
            f"필수 파일을 읽을 수 없습니다: {path}"
        ) from exc


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
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


@contextmanager
def _run_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".run.lock"
    with path.open("a+b") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReadabilityExperimentError(
                "이 실험 디렉터리에서 다른 실행이 진행 중입니다."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_json(path: Path) -> tuple[Any, bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadabilityExperimentError(
            f"JSON 입력이 없거나 잘못되었습니다: {path}"
        ) from exc
    return value, raw


def _load_pricing(path: Path) -> dict[str, Any]:
    value, _ = _load_json(path)
    required = {
        "currency",
        "input_usd_per_million_tokens",
        "output_usd_per_million_tokens",
        "source",
        "verified_at",
    }
    if not isinstance(value, dict) or not required.issubset(value):
        raise ReadabilityExperimentError(
            "pricing.json은 통화·입출력 단가·출처·확인 시각 필드를 정확히 포함해야 합니다."
        )
    if value["currency"] != "USD":
        raise ReadabilityExperimentError("pricing.json의 통화는 USD여야 합니다.")
    for field in ("input_usd_per_million_tokens", "output_usd_per_million_tokens"):
        rate = value[field]
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate < 0
        ):
            raise ReadabilityExperimentError(
                f"{field}는 유한한 0 이상 값이어야 합니다."
            )
    if not any(
        value[field] > 0
        for field in (
            "input_usd_per_million_tokens",
            "output_usd_per_million_tokens",
        )
    ):
        raise ReadabilityExperimentError("가격이 모두 0이면 실험을 시작할 수 없습니다.")
    if not isinstance(value["source"], str) or not value["source"].strip():
        raise ReadabilityExperimentError("가격 출처를 확인할 수 없습니다.")
    if not isinstance(value["verified_at"], str):
        raise ReadabilityExperimentError(
            "verified_at은 시간대가 포함된 ISO-8601이어야 합니다."
        )
    try:
        verified_at = datetime.fromisoformat(value["verified_at"])
    except ValueError as exc:
        raise ReadabilityExperimentError(
            "verified_at은 시간대가 포함된 ISO-8601이어야 합니다."
        ) from exc
    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise ReadabilityExperimentError("verified_at에는 시간대가 필요합니다.")
    return value


def _answer_input(value: Any) -> AnswerInput:
    if not isinstance(value, dict):
        raise ReadabilityExperimentError("answer_input은 객체여야 합니다.")
    allowed = {
        "question",
        "documents",
        "snapshot_fingerprint",
        "classification_context",
        "evidence_state",
    }
    required = {"question", "documents", "snapshot_fingerprint"}
    if set(value) - allowed or not required.issubset(value):
        raise ReadabilityExperimentError("answer_input 필드가 계약과 다릅니다.")
    question = value["question"]
    documents = value["documents"]
    fingerprint = value["snapshot_fingerprint"]
    if not isinstance(question, str) or not question.strip():
        raise ReadabilityExperimentError("answer_input.question이 비어 있습니다.")
    if not isinstance(documents, list) or any(
        not isinstance(item, str) for item in documents
    ):
        raise ReadabilityExperimentError(
            "answer_input.documents는 문자열 목록이어야 합니다."
        )
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ReadabilityExperimentError("snapshot_fingerprint가 비어 있습니다.")

    context_data = value.get("classification_context")
    context = None
    if context_data is not None:
        if not isinstance(context_data, dict):
            raise ReadabilityExperimentError(
                "classification_context는 객체여야 합니다."
            )
        try:
            context = ClassificationContext(**context_data)
        except (TypeError, ValueError) as exc:
            raise ReadabilityExperimentError(
                "classification_context가 올바르지 않습니다."
            ) from exc

    evidence_state = value.get("evidence_state")
    if evidence_state is not None and not isinstance(evidence_state, str):
        raise ReadabilityExperimentError(
            "evidence_state는 문자열 또는 null이어야 합니다."
        )
    return AnswerInput(
        question=question,
        documents=tuple(documents),
        snapshot_fingerprint=fingerprint,
        classification_context=context,
        evidence_state=evidence_state,
    )


def _answer_input_manifest(value: AnswerInput) -> dict[str, Any]:
    return {
        "question": value.question,
        "documents": list(value.documents),
        "snapshot_fingerprint": value.snapshot_fingerprint,
        "classification_context": (
            asdict(value.classification_context)
            if value.classification_context is not None
            else None
        ),
        "evidence_state": value.evidence_state,
    }


def _prompt_values(answer_input: AnswerInput, profile: str) -> dict[str, str]:
    return _build_prompt_values(
        {
            "question": answer_input.question,
            "documents": answer_input.documents,
            "prompt_profile": profile,
            "classification_context": answer_input.classification_context,
            "evidence_state": answer_input.evidence_state,
        }
    )


def _prompt_hash(messages: dict[str, str]) -> str:
    return _sha256_bytes(_canonical_bytes(messages))


def _source_hashes(root: Path) -> dict[str, str]:
    paths = [
        *CODE_PATHS,
        "generation/rag_readability.py",
        "generation/archive/prompt_profiles.json",
        "generation/models.json",
        "generation/experiments.json",
        "pyproject.toml",
        "uv.lock",
    ]
    paths.extend(
        str(path.relative_to(root))
        for package in (
            "app/answering",
            "app/documents",
            "app/questions",
            "app/retrieval",
        )
        for path in sorted((root / package).rglob("*.py"))
    )
    return {path: _sha256_file(root / path) for path in paths}


def _validate_settings(settings: RuntimeSettings) -> None:
    config = settings.config
    expected = {
        "provider": "openai",
        "model_name": "gpt-6-luna",
        "reasoning_effort": "xhigh",
        "max_output_tokens": 16384,
        "context_window": None,
        "timeout_seconds": 180,
        "temperature": None,
        "output_mode": "prompt_json",
    }
    actual = {
        "provider": config.provider.value,
        "model_name": config.model_name,
        "reasoning_effort": config.reasoning_effort,
        "max_output_tokens": config.max_output_tokens,
        "context_window": config.context_window,
        "timeout_seconds": config.timeout_seconds,
        "temperature": config.temperature,
        "output_mode": config.output_mode.value,
    }
    if actual != expected:
        raise ReadabilityExperimentError(f"고정된 실험 생성 설정과 다릅니다: {actual}")


def _schedule(
    cases: list[dict[str, Any]], candidates: tuple[Candidate, ...]
) -> list[dict[str, Any]]:
    scheduled: list[dict[str, Any]] = []
    index = 0
    for case_index, case in enumerate(cases):
        rotation = case_index % len(candidates)
        rotated = candidates[rotation:] + candidates[:rotation]
        for candidate_index, candidate in enumerate(rotated, start=1):
            index += 1
            scheduled.append(
                {
                    "slot_id": f"slot-{index:02d}",
                    "case_id": case["id"],
                    "candidate": candidate.key,
                    "profile": candidate.profile,
                    "candidate_order": candidate_index,
                }
            )
    return scheduled


def _prepare_manifest(
    directory: Path, project_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    input_value, input_bytes = _load_json(directory / "inputs.json")
    rubric, rubric_bytes = _load_json(directory / "rubric.json")
    _, pricing_bytes = _load_json(directory / "pricing.json")
    pricing = _load_pricing(directory / "pricing.json")
    if not isinstance(input_value, list) or len(input_value) != 8:
        raise ReadabilityExperimentError(
            "inputs.json에는 고정된 8개 문항이 필요합니다."
        )
    if not isinstance(rubric, (dict, list)):
        raise ReadabilityExperimentError("rubric.json은 객체 또는 목록이어야 합니다.")

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(input_value, start=1):
        if (
            not isinstance(raw_case, dict)
            or not isinstance(raw_case.get("id"), str)
            or not raw_case["id"].strip()
        ):
            raise ReadabilityExperimentError(f"문항 {index}의 id가 비어 있습니다.")
        case_id = raw_case["id"]
        if case_id in seen:
            raise ReadabilityExperimentError(f"중복 문항 id: {case_id}")
        seen.add(case_id)
        answer = _answer_input(raw_case.get("answer_input"))
        cases.append(
            {
                "id": case_id,
                "answer_input": answer,
                "metadata": {
                    key: value
                    for key, value in raw_case.items()
                    if key not in {"id", "answer_input"}
                },
            }
        )

    base_settings = load_runtime_settings(project_root)
    _validate_settings(base_settings)
    candidates = _candidates()
    schedule = _schedule(cases, candidates)
    profile_hashes: dict[str, dict[str, str]] = {}
    for case in cases:
        profile_hashes[case["id"]] = {
            candidate.key: _prompt_hash(
                _prompt_values(case["answer_input"], candidate.profile)
            )
            for candidate in candidates
        }
    for item in schedule:
        item["prompt_sha256"] = profile_hashes[item["case_id"]][item["candidate"]]

    settings = {
        "provider": base_settings.config.provider.value,
        "model_name": base_settings.config.model_name,
        "timeout_seconds": base_settings.config.timeout_seconds,
        "max_output_tokens": base_settings.config.max_output_tokens,
        "context_window": base_settings.config.context_window,
        "reasoning_effort": base_settings.config.reasoning_effort,
        "temperature": base_settings.config.temperature,
        "output_mode": base_settings.config.output_mode.value,
    }
    manifest_body = {
        "format_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "model_settings": settings,
        "candidate_profiles": [asdict(candidate) for candidate in candidates],
        "input_sha256": _sha256_bytes(input_bytes),
        "input_artifact_sha256": {
            name: _sha256_file(directory / name)
            for name in ("prepare.py", "snapshot.json", "freeze.json")
            if (directory / name).is_file()
        },
        "rubric_sha256": _sha256_bytes(rubric_bytes),
        "pricing_sha256": _sha256_bytes(pricing_bytes),
        "pricing": pricing,
        "code_sha256": _source_hashes(project_root),
        "answer_input_sha256": {
            case["id"]: _sha256_bytes(
                _canonical_bytes(_answer_input_manifest(case["answer_input"]))
            )
            for case in cases
        },
        "prompt_sha256": profile_hashes,
        "schedule": schedule,
        "max_generation_calls": MAX_GENERATION_CALLS,
        "reservation_method": (
            "UTF-8 byte count plus 256 input-token overhead per message; "
            "configured maximum output tokens"
        ),
    }
    envelope = {
        "manifest": manifest_body,
        "manifest_sha256": _sha256_bytes(_canonical_bytes(manifest_body)),
    }
    return envelope, cases, schedule


def _bind_manifest(directory: Path, expected: dict[str, Any]) -> str:
    path = directory / "manifest.json"
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReadabilityExperimentError(
                "manifest.json을 읽을 수 없습니다."
            ) from exc
        body = stored.get("manifest") if isinstance(stored, dict) else None
        checksum = stored.get("manifest_sha256") if isinstance(stored, dict) else None
        if not isinstance(body, dict) or checksum != _sha256_bytes(
            _canonical_bytes(body)
        ):
            raise ReadabilityExperimentError("manifest.json이 손상되었습니다.")
        if stored != expected:
            raise ReadabilityExperimentError(
                "입력·루브릭·가격·설정·프롬프트·코드가 바뀌어 같은 실험을 재개할 수 없습니다."
            )
    else:
        _atomic_json(path, expected)
    return expected["manifest_sha256"]


def _reservation_cost(
    messages: dict[str, str], settings: RuntimeSettings, pricing: dict[str, Any]
) -> float:
    input_upper_tokens = sum(
        len(value.encode("utf-8")) + 256 for value in messages.values()
    )
    output_upper_tokens = settings.config.max_output_tokens
    if output_upper_tokens is None:
        raise ReadabilityExperimentError(
            "출력 토큰 상한이 없어 비용을 예약할 수 없습니다."
        )
    return (
        input_upper_tokens * pricing["input_usd_per_million_tokens"]
        + output_upper_tokens * pricing["output_usd_per_million_tokens"]
    ) / 1_000_000


def _actual_cost(
    result: GenerationResult | None, pricing: dict[str, Any]
) -> float | None:
    if result is None or result.input_tokens is None or result.output_tokens is None:
        return None
    return (
        result.input_tokens * pricing["input_usd_per_million_tokens"]
        + result.output_tokens * pricing["output_usd_per_million_tokens"]
    ) / 1_000_000


def _messages(value: object) -> dict[str, str]:
    if isinstance(value, PromptValue):
        message_list = value.to_messages()
    elif isinstance(value, list) and all(
        isinstance(item, BaseMessage) for item in value
    ):
        message_list = value
    else:
        raise TypeError("모델 입력이 메시지 목록이 아닙니다.")
    if len(message_list) != 2:
        raise TypeError("최종 프롬프트에는 system/user 두 메시지가 필요합니다.")
    roles: dict[str, str] = {}
    for message in message_list:
        role = (
            "system"
            if message.type == "system"
            else "user"
            if message.type == "human"
            else None
        )
        if role is None or not isinstance(message.content, str):
            raise TypeError("최종 프롬프트는 system/user 문자열 메시지여야 합니다.")
        roles[role] = message.content
    if set(roles) != {"system", "user"}:
        raise TypeError("system/user 메시지 역할이 중복되었거나 빠졌습니다.")
    return roles


class _RecordingClient:
    def __init__(self, client: Any, capture: _Capture):
        self._client = client
        self._capture = capture
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, value: object, config: Any = None) -> Any:
        messages = _messages(value)
        self._capture.messages = messages
        slot = self._capture.slot
        if slot is None or messages != slot["precomputed_prompt"]:
            self._capture.prompt_mismatch = True
            raise ReadabilityExperimentError(
                "최종 조립 프롬프트가 사전 고정값과 달라 모델 호출을 차단했습니다."
            )
        result = self._client.runnable.invoke(value, config=config)
        if hasattr(result, "content"):
            self._capture.provider_response_raw = {
                "content": result.content,
                "additional_kwargs": getattr(result, "additional_kwargs", None),
                "response_metadata": getattr(result, "response_metadata", None),
                "usage_metadata": getattr(result, "usage_metadata", None),
            }
            started_record = slot.get("started_record")
            if started_record is not None:
                started_record["provider_response_raw"] = (
                    self._capture.provider_response_raw
                )
                _atomic_json(slot["path"], started_record)
        self._capture.model_response = model_response_from_ai_message(result)
        return result

    async def aclose(self) -> None:
        await self._client.aclose()


class _Experiment:
    def __init__(
        self,
        directory: Path,
        ledger: BudgetLedger,
        pricing: dict[str, Any],
        capture: _Capture,
    ):
        self.directory = directory
        self.ledger = ledger
        self.pricing = pricing
        self.capture = capture
        self.settings_by_profile: dict[str, RuntimeSettings] = {}

    def reserve(self) -> None:
        slot = self.capture.slot
        if slot is None:
            raise ReadabilityExperimentError("호출 슬롯 없이 생성 예약을 요청했습니다.")
        messages = slot["precomputed_prompt"]
        if _prompt_hash(messages) != slot["expected_prompt_sha256"]:
            raise ReadabilityExperimentError(
                "실제 프롬프트가 고정 manifest와 다릅니다."
            )
        bound = _reservation_cost(
            messages, self.settings_by_profile[slot["profile"]], self.pricing
        )
        self.ledger.reserve(slot["slot_id"], "final", bound)
        slot_record = dict(slot["record"])
        slot_record.update(
            status="started",
            started_at=datetime.now().astimezone().isoformat(),
            reserved_cost_usd=bound,
            precomputed_prompt=messages,
            expected_prompt_sha256=slot["expected_prompt_sha256"],
            manifest_sha256=slot["manifest_sha256"],
        )
        _atomic_json(slot["path"], slot_record)
        slot["started_record"] = slot_record


def _capture_result_patch(capture: _Capture):
    original = answerer_adapter.run_generation_pipeline

    def recording_run(**kwargs: Any) -> GenerationResult:
        result = original(**kwargs)
        capture.generation_result = result
        return result

    return recording_run


def _slot_path(directory: Path, slot_id: str) -> Path:
    return directory / "slots" / f"{slot_id}.json"


def _existing_state(
    path: Path,
    ledger_snapshot: dict[str, Any],
    expected_slot: dict[str, Any],
    manifest_hash: str,
    expected_prompt: dict[str, str],
) -> str | None:
    slot_id = expected_slot["slot_id"]
    reservation = ledger_snapshot.get("reservations", {}).get(slot_id)
    if path.exists():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReadabilityExperimentError(
                f"저장된 슬롯이 손상되었습니다: {path}"
            ) from exc
        status = record.get("status") if isinstance(record, dict) else None
        expected_fields = {
            key: expected_slot[key]
            for key in ("slot_id", "case_id", "candidate", "profile", "prompt_sha256")
        }
        if any(record.get(key) != value for key, value in expected_fields.items()):
            raise ReadabilityExperimentError(
                f"저장된 슬롯 식별이 일정과 다릅니다: {path}"
            )
        if record.get("manifest_sha256") != manifest_hash:
            raise ReadabilityExperimentError(
                f"저장된 슬롯의 manifest가 다릅니다: {path}"
            )
        if status in {"started", "completed"} and (
            record.get("precomputed_prompt") != expected_prompt
            or record.get(
                "precomputed_prompt_sha256", record.get("expected_prompt_sha256")
            )
            != expected_slot["prompt_sha256"]
        ):
            raise ReadabilityExperimentError(
                f"저장된 슬롯의 사전 프롬프트가 다릅니다: {path}"
            )
        if status == "completed" and (
            record.get("final_prompt") != expected_prompt
            or record.get("final_prompt_sha256") != expected_slot["prompt_sha256"]
            or record.get("prompt_matches_manifest") is not True
        ):
            raise ReadabilityExperimentError(
                f"완료 슬롯의 실제 프롬프트가 다릅니다: {path}"
            )
        if status in {"completed", "failed", "started", "uncertain"}:
            if reservation is not None and (
                reservation.get("phase") != "final"
                or reservation.get("status") not in {"reserved", "settled"}
            ):
                raise ReadabilityExperimentError(
                    f"저장된 슬롯의 예산 예약이 올바르지 않습니다: {path}"
                )
            if status in {"completed", "started", "uncertain"} and reservation is None:
                raise ReadabilityExperimentError(
                    f"저장된 슬롯에 대응하는 예산 예약이 없습니다: {path}"
                )
            if status == "completed" and reservation.get("status") != "settled":
                raise ReadabilityExperimentError(
                    f"완료 슬롯의 예산 예약이 정산되지 않았습니다: {path}"
                )
            if (
                reservation is not None
                and record.get("reserved_cost_usd") is not None
                and not math.isclose(
                    reservation.get("reserved_dollars", -1),
                    record["reserved_cost_usd"],
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
            ):
                raise ReadabilityExperimentError(
                    f"저장된 슬롯과 ledger의 예약 금액이 다릅니다: {path}"
                )
        if status in {"completed", "failed", "uncertain"}:
            return status
        if status == "started":
            return "uncertain"
        raise ReadabilityExperimentError(f"슬롯 상태가 올바르지 않습니다: {path}")
    if reservation is not None:
        return "uncertain"
    return None


def _safe_serialized_result(
    result: GenerationResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "raw_text": result.raw_text,
        "answer": result.answer,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "finish_reason": result.finish_reason,
        "refusal": result.refusal,
    }


def _profile_response(
    case: dict[str, Any],
    scheduled: dict[str, Any],
    *,
    capture: _Capture,
    answerer: Any,
    experiment: _Experiment,
    expected_prompt: dict[str, str],
    manifest_hash: str,
    path: Path,
) -> dict[str, Any]:
    record = {
        **scheduled,
        "question": case["answer_input"].question,
        "answer_input": _answer_input_manifest(case["answer_input"]),
        "case_metadata": case["metadata"],
    }
    capture.slot = {
        "slot_id": scheduled["slot_id"],
        "profile": scheduled["profile"],
        "record": record,
        "path": path,
        "precomputed_prompt": expected_prompt,
        "expected_prompt_sha256": _prompt_hash(expected_prompt),
        "manifest_sha256": manifest_hash,
    }
    capture.messages = None
    capture.model_response = None
    capture.generation_result = None
    capture.prompt_mismatch = False
    capture.provider_response_raw = None
    started = perf_counter()
    error_type = None
    answer = None
    try:
        answer = answerer.answer_input(case["answer_input"])
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        # Store only the exception type, without provider details or credentials.
        error_type = type(exc).__name__
    elapsed = perf_counter() - started

    result = capture.generation_result
    estimated_cost = _actual_cost(result, experiment.pricing)
    reservation = (
        experiment.ledger.snapshot().get("reservations", {}).get(scheduled["slot_id"])
    )
    if reservation is None:
        result_state = "failed"
        cost = None
    else:
        experiment.ledger.settle(scheduled["slot_id"], estimated_cost)
        result_state = (
            "completed"
            if error_type is None
            and result is not None
            and result.status is GenerationStatus.COMPLETED
            else "failed"
        )
        cost = estimated_cost

    actual_messages = capture.messages
    prompt_matches = actual_messages == expected_prompt
    slot_result = {
        **record,
        "status": result_state,
        "manifest_sha256": manifest_hash,
        "generation_status": result.status.value if result is not None else None,
        "error_type": error_type,
        "answer": answer,
        "final_prompt": actual_messages,
        "final_prompt_sha256": (
            _prompt_hash(actual_messages) if actual_messages is not None else None
        ),
        "precomputed_prompt_sha256": _prompt_hash(expected_prompt),
        "precomputed_prompt": expected_prompt,
        "prompt_matches_manifest": prompt_matches,
        "started_at": (
            capture.slot["started_record"].get("started_at")
            if capture.slot and capture.slot.get("started_record")
            else None
        ),
        "model_response": (
            {
                "raw_text": capture.model_response.raw_text,
                "input_tokens": capture.model_response.input_tokens,
                "output_tokens": capture.model_response.output_tokens,
                "finish_reason": capture.model_response.finish_reason,
                "refusal": capture.model_response.refusal,
            }
            if capture.model_response is not None
            else None
        ),
        "provider_response_raw": capture.provider_response_raw,
        "generation_result": _safe_serialized_result(result),
        "elapsed_seconds": elapsed,
        "input_tokens": result.input_tokens if result is not None else None,
        "output_tokens": result.output_tokens if result is not None else None,
        "reserved_cost_usd": (
            reservation.get("reserved_dollars") if reservation else None
        ),
        "estimated_cost_usd": estimated_cost,
        "cost_estimate_method": (
            "estimated from observed token usage and frozen USD-per-million rates; not provider billing"
            if estimated_cost is not None
            else None
        ),
        "actual_billing_amount_usd": None,
        "charged_cost_usd": (
            reservation.get("reserved_dollars")
            if reservation and estimated_cost is None
            else cost
        ),
        "cost_status": (
            "token_usage_estimate"
            if estimated_cost is not None
            else "reservation_retained_unknown_usage"
        ),
        "completed_at": datetime.now().astimezone().isoformat(),
    }
    _atomic_json(path, slot_result)
    if not prompt_matches and result is not None:
        raise ReadabilityExperimentError(
            f"실제 조립 프롬프트가 manifest와 다릅니다: {scheduled['slot_id']}"
        )
    if capture.prompt_mismatch:
        raise ReadabilityExperimentError(
            f"실제 조립 프롬프트가 manifest와 달라 중단했습니다: {scheduled['slot_id']}"
        )
    return slot_result


def run_experiment(
    directory: Path,
    *,
    project_root: Path = ROOT,
    prepare_only: bool = False,
) -> dict[str, Any]:
    directory = Path(directory).resolve()
    project_root = Path(project_root).resolve()
    with _run_lock(directory):
        manifest, cases, schedule = _prepare_manifest(directory, project_root)
        manifest_hash = _bind_manifest(directory, manifest)
        if prepare_only:
            return {
                "directory": str(directory),
                "manifest_sha256": manifest_hash,
                "planned_slots": len(schedule),
                "generated": 0,
                "prepare_only": True,
            }

        pricing = manifest["manifest"]["pricing"]
        ledger = BudgetLedger(
            directory / "budget.json",
            total_dollars=None,
            dev_dollars=None,
            total_seconds=None,
            dev_seconds=None,
            max_calls=MAX_GENERATION_CALLS,
        )
        ledger.bind_limits()
        ledger_snapshot = ledger.snapshot()
        allowed_slots = {item["slot_id"] for item in schedule}
        unknown_reservations = (
            set(ledger_snapshot.get("reservations", {})) - allowed_slots
        )
        if unknown_reservations:
            raise ReadabilityExperimentError(
                "예산 ledger에 현재 일정과 무관한 호출이 있습니다."
            )

        candidate_specs = {candidate.profile: candidate for candidate in _candidates()}
        capture = _Capture()
        experiment = _Experiment(directory, ledger, pricing, capture)
        base_settings = load_runtime_settings(project_root)
        answerers: dict[str, Any] = {}
        for profile in candidate_specs:
            settings = replace(base_settings, prompt_profile=profile)
            experiment.settings_by_profile[profile] = settings
            answerers[profile] = answerer_adapter.GenerationAnswerer(
                settings, reserve_generation=experiment.reserve
            )

        original_factory = answerer_adapter.build_managed_model_call

        def build_recording_client(config: Any) -> _RecordingClient:
            return _RecordingClient(original_factory(config), capture)

        completed = failed = skipped = uncertain = generated = 0
        try:
            with (
                patch.object(
                    answerer_adapter,
                    "build_managed_model_call",
                    side_effect=build_recording_client,
                ),
                patch.object(
                    answerer_adapter,
                    "run_generation_pipeline",
                    side_effect=_capture_result_patch(capture),
                ),
            ):
                by_id = {case["id"]: case for case in cases}
                for item in schedule:
                    path = _slot_path(directory, item["slot_id"])
                    case = by_id[item["case_id"]]
                    candidate = candidate_specs[item["profile"]]
                    expected_prompt = _prompt_values(
                        case["answer_input"], candidate.profile
                    )
                    state = _existing_state(
                        path,
                        ledger.snapshot(),
                        item,
                        manifest_hash,
                        expected_prompt,
                    )
                    if state == "completed":
                        completed += 1
                        skipped += 1
                        continue
                    if state == "failed":
                        failed += 1
                        skipped += 1
                        continue
                    if state == "uncertain":
                        if not path.exists():
                            _atomic_json(
                                path,
                                {
                                    **item,
                                    "status": "uncertain",
                                    "manifest_sha256": manifest_hash,
                                    "prompt_sha256": item["prompt_sha256"],
                                    "precomputed_prompt_sha256": item["prompt_sha256"],
                                    "precomputed_prompt": expected_prompt,
                                    "note": (
                                        "이전 실행의 호출 여부 또는 응답 저장 여부를 "
                                        "확정할 수 없어 재호출하지 않음"
                                    ),
                                },
                            )
                        uncertain += 1
                        skipped += 1
                        continue
                    try:
                        slot_result = _profile_response(
                            case,
                            item,
                            capture=capture,
                            answerer=answerers[candidate.profile],
                            experiment=experiment,
                            expected_prompt=expected_prompt,
                            manifest_hash=manifest_hash,
                            path=path,
                        )
                    except BudgetExceeded as exc:
                        raise ReadabilityExperimentError(
                            "24회 생성 호출 한도에 도달했습니다."
                        ) from exc
                    generated += 1
                    if slot_result["status"] == "completed":
                        completed += 1
                    else:
                        failed += 1
        finally:
            for answerer in answerers.values():
                asyncio.run(answerer.aclose())

        return {
            "directory": str(directory),
            "manifest_sha256": manifest_hash,
            "planned_slots": len(schedule),
            "generated": generated,
            "newly_generated": generated,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "uncertain": uncertain,
            "budget": ledger.snapshot(),
            "prepare_only": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RAG v5/v6/v7 prompt readability comparison"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_experiment(args.directory, prepare_only=args.prepare_only)
    except (ReadabilityExperimentError, BudgetExceeded) as exc:
        parser.exit(2, f"오류: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    if result.get("failed") or result.get("uncertain"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
