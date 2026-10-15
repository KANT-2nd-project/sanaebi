"""Prepare and execute one bounded, blinded full/RAG answer comparison.

Prepare is local-only. Execute is explicit, records a permanent start marker,
and never resumes or retries a started run. The script itself does not make
provider calls unless ``--execute`` is supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import subprocess
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from dotenv import dotenv_values, load_dotenv

from app.answering.adapter import GenerationAnswerer
from app.documents.context import (
    DocumentContext,
    DocumentContextProvider,
    DocumentContextSnapshot,
)
from app.documents.transfer import import_knowledge, read_source
from app.retrieval.config import DEFAULT_SPEC, MODEL_ID, MODEL_REVISION
from app.retrieval.embedding import MODEL_MANIFEST, TinyEmbedder
from app.retrieval.repository import IndexRepository
from app.retrieval.service import RetrievalService
from app.retrieval.types import Evidence, RetrievedContext, SourceSpan
from generation.documents import render_document
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.providers import (
    GenerationProviderResponseError,
    build_managed_model_call,
    to_messages,
)
from generation.types import GenerationPrompt, ModelResponse
from generation_evaluation.budget import (
    BudgetExceeded,
    BudgetLedger,
    actual_cost,
    reserve_cost,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "data/company-knowledge/documents.jsonl"
DEFAULT_CASES = ROOT / "retrieval/reports/2026-10-15-rag-answer-comparison/cases.json"
ARTIFACT_SCHEMA_VERSION = 1
MAX_CASES = 20
MAX_CALLS = 40
MAX_DOLLARS = 5.0
PROMPT_PROFILE = "examples_answer_scope_v5"
MODEL_NAME = "gpt-6-luna"
EXECUTION_STARTED = "execution.started.json"
_CASE_ID = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FORBIDDEN_PROVIDER_OVERRIDES = (
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_API_TYPE",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "OPENAI_SERVICE_TIER",
)

# Hash the small set of source files that determine the saved input prompts and
# execute-time answer path. The frozen corpus and cases have independent hashes.
_CODE_INPUTS = (
    "retrieval/experiments/answers.py",
    "app/answering/adapter.py",
    "app/documents/context.py",
    "app/documents/metadata.py",
    "app/documents/repository.py",
    "app/documents/schemas.py",
    "app/documents/transfer.py",
    "app/retrieval/baseline.py",
    "app/retrieval/chunking.py",
    "app/retrieval/config.py",
    "app/retrieval/embedding.py",
    "app/retrieval/repository.py",
    "app/retrieval/search.py",
    "app/retrieval/service.py",
    "app/retrieval/types.py",
    "generation/config.py",
    "generation/documents.py",
    "generation/experiments.json",
    "generation/models.json",
    "generation/presets.py",
    "generation/profiles.py",
    "generation/prompts.py",
    "generation/providers.py",
    "generation/service.py",
    "generation/types.py",
    "generation/validation.py",
    "generation_evaluation/budget.py",
    "uv.lock",
)


class AnswerEvaluationError(RuntimeError):
    """Safe, user-facing reason the prepared evaluation cannot proceed."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes())


def code_manifest(root: Path = ROOT) -> dict[str, str]:
    """Return source hashes used to reject execution after code drift."""
    result = {}
    for name in _CODE_INPUTS:
        path = root / name
        if not path.is_file():
            raise AnswerEvaluationError(f"평가 기준 파일이 없습니다: {name}")
        result[name] = sha256_file(path)
    return result


def ledger_at(output: Path) -> BudgetLedger:
    ledger = BudgetLedger(
        output / "ledger.json",
        total_dollars=MAX_DOLLARS,
        dev_dollars=MAX_DOLLARS,
        total_seconds=None,
        dev_seconds=None,
        max_calls=MAX_CALLS,
    )
    ledger.bind_limits()
    return ledger


def _runtime_settings(root: Path):
    settings = load_runtime_settings(root)
    config = settings.config
    if (
        config.provider.value != "openai"
        or config.model_name != MODEL_NAME
        or config.reasoning_effort != "xhigh"
        or config.max_output_tokens != 16_384
        or config.output_mode.value != "prompt_json"
        or settings.prompt_profile != PROMPT_PROFILE
    ):
        raise AnswerEvaluationError(
            "고정 평가 설정(Luna, v5, xhigh, 16,384)이 현재 runtime 기본값과 다릅니다."
        )
    return settings


def _check_model_manifest(model_path: Path) -> None:
    manifest_path = model_path / "retrieval-model.json"
    if not model_path.is_dir() or not manifest_path.is_file():
        raise AnswerEvaluationError("고정 로컬 Tiny 모델 또는 manifest가 없습니다.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnswerEvaluationError("Tiny 모델 manifest를 읽을 수 없습니다.") from exc
    if manifest != MODEL_MANIFEST:
        raise AnswerEvaluationError(
            "Tiny 모델 manifest가 고정 retrieval 계약과 다릅니다."
        )


def _validate_provider_environment(env_file: Path) -> None:
    if not env_file.is_file():
        raise AnswerEvaluationError("실행에 필요한 env 파일을 읽을 수 없습니다.")
    file_values = dotenv_values(env_file)
    configured = {
        key
        for key in _FORBIDDEN_PROVIDER_OVERRIDES
        if (file_values.get(key) or os.environ.get(key) or "").strip()
    }
    if configured:
        names = ", ".join(sorted(configured))
        raise AnswerEvaluationError(
            f"가격·endpoint를 바꾸는 provider 환경변수는 사용할 수 없습니다: {names}"
        )


def _validate_cases(data: Any, source_sha: str, source_rows) -> list[dict[str, Any]]:
    if (
        not isinstance(data, dict)
        or data.get("status") != "frozen_independent_ai_reviewed"
    ):
        raise AnswerEvaluationError("문항은 독립 AI 검토 후 고정된 상태여야 합니다.")
    source = data.get("source")
    if (
        not isinstance(source, dict)
        or source.get("sha256") != source_sha
        or source.get("path") != "data/company-knowledge/documents.jsonl"
    ):
        raise AnswerEvaluationError("고정 문항의 corpus 식별값이 일치하지 않습니다.")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != MAX_CASES:
        raise AnswerEvaluationError("평가 문항은 정확히 20개여야 합니다.")
    by_document_id = {row[3]["document_id"]: row[3] for row in source_rows}
    ids: set[str] = set()
    answerable_count = 0
    copied_cases = []
    for case in cases:
        if not isinstance(case, dict):
            raise AnswerEvaluationError("평가 문항 형식이 올바르지 않습니다.")
        case_id = case.get("case_id")
        question = case.get("question")
        answerable = case.get("answerable")
        if (
            not isinstance(case_id, str)
            or not _CASE_ID.fullmatch(case_id)
            or case_id in ids
        ):
            raise AnswerEvaluationError(
                "문항 ID가 비어 있거나 중복 또는 안전하지 않습니다."
            )
        if not isinstance(question, str) or not question.strip():
            raise AnswerEvaluationError(f"{case_id}: 질문이 비어 있습니다.")
        if not isinstance(answerable, bool):
            raise AnswerEvaluationError(
                f"{case_id}: answerable은 boolean이어야 합니다."
            )
        ids.add(case_id)
        answerable_count += int(answerable)
        if case.get("split") not in {"regression", "development", "unanswerable"}:
            raise AnswerEvaluationError(f"{case_id}: split 값이 올바르지 않습니다.")
        required_spans = case.get("required_spans", [])
        if not isinstance(required_spans, list):
            raise AnswerEvaluationError(
                f"{case_id}: required_spans 형식이 올바르지 않습니다."
            )
        if answerable:
            document_id = case.get("document_id")
            document = by_document_id.get(document_id)
            if document is None or case.get("title") != document["title"]:
                raise AnswerEvaluationError(
                    f"{case_id}: 정답 문서가 frozen corpus와 다릅니다."
                )
            if not required_spans:
                raise AnswerEvaluationError(f"{case_id}: 필수 근거 구간이 없습니다.")
            for required in required_spans:
                if not isinstance(required, dict):
                    raise AnswerEvaluationError(
                        f"{case_id}: 근거 구간이 객체가 아닙니다."
                    )
                start, end, text = (
                    required.get("start"),
                    required.get("end"),
                    required.get("text"),
                )
                if (
                    isinstance(start, bool)
                    or not isinstance(start, int)
                    or isinstance(end, bool)
                    or not isinstance(end, int)
                    or start < 0
                    or end <= start
                    or end > len(document["document"])
                    or not isinstance(text, str)
                    or document["document"][start:end] != text
                ):
                    raise AnswerEvaluationError(
                        f"{case_id}: 정답 구간이 원문과 다릅니다."
                    )
        elif case.get("split") != "unanswerable":
            raise AnswerEvaluationError(
                f"{case_id}: 답변 불가 문항 split은 unanswerable이어야 합니다."
            )
        answerability_reason = case.get("answerability_reason")
        if not answerable and (
            not isinstance(answerability_reason, str)
            or not answerability_reason.strip()
        ):
            raise AnswerEvaluationError(f"{case_id}: 답변 불가 근거가 비어 있습니다.")
        tags = case.get("challenge_tags")
        reason = case.get("selection_reason")
        criteria = case.get("expected_answer_criteria")
        if (
            not isinstance(tags, list)
            or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
            or not isinstance(reason, str)
            or not reason.strip()
            or not isinstance(criteria, list)
            or any(not isinstance(item, str) or not item.strip() for item in criteria)
        ):
            raise AnswerEvaluationError(
                f"{case_id}: 검토 근거/기준 형식이 올바르지 않습니다."
            )
        copied_cases.append(
            {
                "case_id": case_id,
                "split": case["split"],
                "answerable": answerable,
                "question": question,
                "document_id": case.get("document_id"),
                "title": case.get("title"),
                "required_spans": required_spans,
                "challenge_tags": tags,
                "selection_reason": reason,
                "expected_answer_criteria": criteria,
                **(
                    {"answerability_reason": answerability_reason}
                    if answerability_reason is not None
                    else {}
                ),
                **(
                    {"optional_correctness_checks": case["optional_correctness_checks"]}
                    if "optional_correctness_checks" in case
                    else {}
                ),
            }
        )
    if answerable_count != 16:
        raise AnswerEvaluationError(
            "평가 문항은 답변 가능 16개와 답변 불가 4개여야 합니다."
        )
    return copied_cases


def _frozen_source_hashes(cases_path: Path) -> dict[str, str]:
    """Verify and hash the reviewed case, rubric, freeze, and price evidence."""
    cases_path = cases_path.resolve()
    paths = {
        "cases.json": cases_path,
        "rubric.md": cases_path.with_name("rubric.md"),
        "freeze.json": cases_path.with_name("freeze.json"),
        "pricing.json": cases_path.with_name("pricing.json"),
    }
    if any(not path.is_file() for path in paths.values()):
        raise AnswerEvaluationError(
            "고정 문항, rubric, freeze, pricing 근거가 모두 필요합니다."
        )
    try:
        cases_data = json.loads(paths["cases.json"].read_text(encoding="utf-8"))
        freeze_data = json.loads(paths["freeze.json"].read_text(encoding="utf-8"))
        pricing_data = json.loads(paths["pricing.json"].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnswerEvaluationError("고정 평가 근거 파일을 읽을 수 없습니다.") from exc
    cases_sha = sha256_file(paths["cases.json"])
    rubric_sha = sha256_file(paths["rubric.md"])
    if (
        not isinstance(freeze_data, dict)
        or freeze_data.get("status") != "approved_before_calls"
        or freeze_data.get("human_review") is not False
        or freeze_data.get("cases_sha256") != cases_sha
        or freeze_data.get("rubric_sha256") != rubric_sha
        or not isinstance(cases_data, dict)
        or cases_data.get("status") != "frozen_independent_ai_reviewed"
    ):
        raise AnswerEvaluationError("case/rubric이 승인 후 고정본과 일치하지 않습니다.")
    expected_pricing = {
        "source_url": "https://developers.openai.com/api/docs/pricing",
        "model": MODEL_NAME,
        "tier": "Standard long context conservative",
        "input_usd_per_million": 0.2,
        "cached_input_usd_per_million": 0.02,
        "cache_write_usd_per_million": 0.25,
        "output_usd_per_million": 0.75,
        "max_calls": MAX_CALLS,
        "max_total_usd": MAX_DOLLARS,
    }
    if (
        not isinstance(pricing_data, dict)
        or any(
            pricing_data.get(key) != value for key, value in expected_pricing.items()
        )
        or not isinstance(pricing_data.get("preflight"), str)
        or "max output16384" not in pricing_data["preflight"]
    ):
        raise AnswerEvaluationError("pricing evidence가 고정 평가 예산과 다릅니다.")
    # Paths are represented by stable logical names, never host-specific paths.
    return {name: sha256_file(path) for name, path in paths.items()}


def _snapshot_to_dict(snapshot: DocumentContextSnapshot) -> dict[str, Any]:
    return {
        "snapshot_fingerprint": snapshot.fingerprint,
        "documents": [
            {
                "document_id": doc.document_id,
                "knowledge_id": doc.knowledge_id,
                "revision_id": doc.revision_id,
                "revision": doc.revision,
                "title": doc.title,
                "body": doc.body,
                "source_reference": doc.source_reference,
                "content_hash": doc.content_hash,
                "metadata": dict(doc.metadata),
            }
            for doc in snapshot.documents
        ],
    }


def _snapshot_from_dict(data: dict[str, Any]) -> DocumentContextSnapshot:
    documents = tuple(
        DocumentContext(
            document_id=doc["document_id"],
            knowledge_id=doc["knowledge_id"],
            revision_id=doc["revision_id"],
            revision=doc["revision"],
            title=doc["title"],
            body=doc["body"],
            source_reference=doc["source_reference"],
            content_hash=doc["content_hash"],
            metadata=MappingProxyType(doc.get("metadata", {})),
        )
        for doc in data["documents"]
    )
    snapshot = DocumentContextSnapshot(documents)
    if snapshot.fingerprint != data.get("snapshot_fingerprint"):
        raise AnswerEvaluationError("저장된 snapshot fingerprint가 손상되었습니다.")
    return snapshot


def _retrieval_to_dict(context: RetrievedContext) -> dict[str, Any]:
    value = asdict(context)
    value["observed_at"] = context.observed_at.isoformat()
    return value


def _retrieval_from_dict(data: dict[str, Any]) -> RetrievedContext:
    from datetime import datetime

    return RetrievedContext(
        snapshot_fingerprint=data["snapshot_fingerprint"],
        spec_id=data["spec_id"],
        evidence=tuple(
            Evidence(
                knowledge_id=evidence["knowledge_id"],
                document_id=evidence["document_id"],
                revision_id=evidence["revision_id"],
                revision=evidence["revision"],
                title=evidence["title"],
                text=evidence["text"],
                source_reference=evidence["source_reference"],
                spans=tuple(SourceSpan(**span) for span in evidence["spans"]),
                chunk_ids=tuple(evidence["chunk_ids"]),
                score=evidence["score"],
                rank=evidence["rank"],
                expanded_chunk_ids=tuple(evidence.get("expanded_chunk_ids", ())),
            )
            for evidence in data["evidence"]
        ),
        candidate_count=data["candidate_count"],
        selected_count=data["selected_count"],
        observed_at=datetime.fromisoformat(data["observed_at"]),
        candidate_chunk_ids=tuple(data.get("candidate_chunk_ids", ())),
        search_config_id=data.get("search_config_id", ""),
    )


def _prompt_dict(prompt: GenerationPrompt) -> dict[str, str]:
    return {"system": prompt.system, "user": prompt.user}


def _prompt_sha(prompt: GenerationPrompt) -> str:
    payload = json.dumps(
        {"system": prompt.system, "user": prompt.user},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload)


def _render_full(snapshot: DocumentContextSnapshot) -> list[str]:
    return [
        render_document(doc.knowledge_id, doc.title, doc.body, doc.revision)
        for doc in snapshot.documents
    ]


def _render_retrieved(context: RetrievedContext) -> list[str]:
    documents = [
        render_document(
            evidence.knowledge_id, evidence.title, evidence.text, evidence.revision
        )
        for evidence in context.evidence
    ]
    if not documents:
        raise AnswerEvaluationError("RAG가 전달할 근거를 찾지 못했습니다.")
    return ["[현재 게시 문서의 발췌 근거]\n" + document for document in documents]


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
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def prepare_evaluation(
    cases_path: Path,
    model_path: Path,
    artifact_root: Path,
    *,
    root: Path = ROOT,
    source_path: Path = DEFAULT_SOURCE,
    embedder_factory=TinyEmbedder,
) -> dict[str, Any]:
    """Build an isolated published DB, default-spec index, prompts and blind map."""
    target = artifact_root.resolve()
    if target.exists():
        raise AnswerEvaluationError(
            "artifact-root가 이미 있습니다. 새 경로를 지정하세요."
        )
    if not cases_path.is_file() or not source_path.is_file():
        raise AnswerEvaluationError("고정 문항 또는 corpus 파일을 찾을 수 없습니다.")
    frozen_source_hashes = _frozen_source_hashes(cases_path)
    settings = _runtime_settings(root)
    _check_model_manifest(model_path.resolve())
    raw, source_rows = read_source(source_path)
    source_sha = sha256(raw)
    case_data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = _validate_cases(case_data, source_sha, source_rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.prepare-", dir=target.parent))
    try:
        source_dir = stage / "source"
        source_dir.mkdir()
        isolated_db = source_dir / "documents.sqlite3"
        import_report = import_knowledge(
            source_path, isolated_db, apply=True, publish=True
        )
        if import_report.get("published_count") != len(source_rows):
            raise AnswerEvaluationError(
                "격리 문서 저장소의 게시 문서 수가 맞지 않습니다."
            )
        snapshot = DocumentContextProvider(database_path=isolated_db).snapshot()
        expected = {
            row[3]["document_id"]: (row[3]["title"], row[3]["document"])
            for row in source_rows
        }
        actual = {
            document.knowledge_id: (document.title, document.body)
            for document in snapshot.documents
        }
        if actual != expected or len(actual) != len(expected):
            raise AnswerEvaluationError(
                "격리된 게시 snapshot이 frozen corpus와 다릅니다."
            )

        embedder = embedder_factory(model_path.resolve())
        repository = IndexRepository(stage / "retrieval", spec=DEFAULT_SPEC)
        retrieval = RetrievalService(repository, embedder, spec=DEFAULT_SPEC)
        status = retrieval.reconcile(snapshot)
        if not status["ready"]:
            raise AnswerEvaluationError("격리 retrieval index가 준비되지 않았습니다.")

        full_documents = _render_full(snapshot)
        blind_map: dict[str, dict[str, str]] = {}
        prepared_cases = []
        rng = secrets.SystemRandom()
        for case in cases:
            rag_context = retrieval.retrieve(case["question"], snapshot)
            rag_documents = _render_retrieved(rag_context)
            variants_by_mode = {}
            for mode, documents in (
                ("full", full_documents),
                ("rag", rag_documents),
            ):
                prompt = build_profile_prompt(
                    case["question"], documents, settings.prompt_profile
                )
                variants_by_mode[mode] = {
                    "prompt": _prompt_dict(prompt),
                    "prompt_sha256": _prompt_sha(prompt),
                    "rendered_documents": documents,
                    "retrieved_context": (
                        _retrieval_to_dict(rag_context) if mode == "rag" else None
                    ),
                }
            modes = ["full", "rag"]
            rng.shuffle(modes)
            mapping = {"A": modes[0], "B": modes[1]}
            blind_map[case["case_id"]] = mapping
            prepared_cases.append(
                {
                    **case,
                    "variants": {
                        alias: variants_by_mode[mode] for alias, mode in mapping.items()
                    },
                }
            )

        snapshot_data = _snapshot_to_dict(snapshot)
        _write_json(stage / "snapshot.json", snapshot_data, exclusive=True)
        _write_json(
            stage / "inputs.json",
            {"schema_version": ARTIFACT_SCHEMA_VERSION, "cases": prepared_cases},
            exclusive=True,
        )
        private_dir = stage / "private"
        private_dir.mkdir(mode=0o700)
        _write_json(private_dir / "blind-map.json", blind_map, exclusive=True)
        source_manifest = {
            "source_sha256": source_sha,
            "source_document_count": len(source_rows),
            "snapshot_fingerprint": snapshot.fingerprint,
            "snapshot_sha256": sha256_file(stage / "snapshot.json"),
            "published_database": "source/documents.sqlite3",
            "isolated_retrieval_root": "retrieval",
            "retrieval_spec": DEFAULT_SPEC.to_dict(),
            "retrieval_spec_id": retrieval.spec_id,
        }
        manifest = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "status": "prepared",
            "created_at": datetime.now(UTC).isoformat(),
            "code_commit": _git_commit(root),
            "code_files": code_manifest(root),
            "cases_sha256": sha256_file(cases_path),
            "frozen_source_files_sha256": frozen_source_hashes,
            "case_count": len(cases),
            "answerable_count": sum(case["answerable"] for case in cases),
            "unanswerable_count": sum(not case["answerable"] for case in cases),
            "source": source_manifest,
            "embedding_model": {
                "model_id": MODEL_ID,
                "revision": MODEL_REVISION,
                "local_only": True,
            },
            "runtime": {
                "provider": settings.config.provider.value,
                "model_name": settings.config.model_name,
                "prompt_profile": settings.prompt_profile,
                "reasoning_effort": settings.config.reasoning_effort,
                "max_output_tokens": settings.config.max_output_tokens,
                "output_mode": settings.config.output_mode.value,
                "api_calls_planned": len(cases) * 2,
                "max_api_calls": MAX_CALLS,
                "max_cost_usd": MAX_DOLLARS,
                "api_calls_made": 0,
            },
            "python": platform.python_version(),
        }
        manifest["prepared_files_sha256"] = {
            relative: sha256_file(stage / relative)
            for relative in (
                "inputs.json",
                "snapshot.json",
                "private/blind-map.json",
            )
        }
        _write_json(stage / "manifest.json", manifest, exclusive=True)
        os.replace(stage, target)
        return manifest
    except BaseException:
        # The target is not published until the complete local-only prepare is ready.
        import shutil

        shutil.rmtree(stage, ignore_errors=True)
        raise


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnswerEvaluationError(
            f"평가 자료를 읽을 수 없습니다: {path.name}"
        ) from exc


def _validate_prepared(
    artifact_root: Path,
    cases_path: Path,
    model_path: Path,
    root: Path,
    source_path: Path,
):
    manifest = _read_json(artifact_root / "manifest.json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != ARTIFACT_SCHEMA_VERSION
        or manifest.get("status") != "prepared"
    ):
        raise AnswerEvaluationError("실행 가능한 prepare artifact가 아닙니다.")
    if manifest.get("code_files") != code_manifest(root):
        raise AnswerEvaluationError(
            "prepare 이후 answer·retrieval 코드가 바뀌었습니다."
        )
    frozen_source_hashes = _frozen_source_hashes(cases_path)
    if manifest.get(
        "frozen_source_files_sha256"
    ) != frozen_source_hashes or manifest.get(
        "cases_sha256"
    ) != frozen_source_hashes.get("cases.json"):
        raise AnswerEvaluationError(
            "prepare 이후 고정 cases/rubric/freeze/pricing이 바뀌었습니다."
        )
    expected_prepared_hashes = {
        "inputs.json",
        "snapshot.json",
        "private/blind-map.json",
    }
    prepared_hashes = manifest.get("prepared_files_sha256")
    if (
        not isinstance(prepared_hashes, dict)
        or set(prepared_hashes) != expected_prepared_hashes
    ):
        raise AnswerEvaluationError("저장된 입력 무결성 manifest가 올바르지 않습니다.")
    if any(
        not (artifact_root / relative).is_file()
        or sha256_file(artifact_root / relative) != prepared_hashes[relative]
        for relative in expected_prepared_hashes
    ):
        raise AnswerEvaluationError(
            "prepare 입력·snapshot·blind map이 생성 이후 바뀌었습니다."
        )
    runtime = manifest.get("runtime", {})
    if (
        runtime
        != {
            "provider": "openai",
            "model_name": MODEL_NAME,
            "prompt_profile": PROMPT_PROFILE,
            "reasoning_effort": "xhigh",
            "max_output_tokens": 16_384,
            "output_mode": "prompt_json",
            "api_calls_planned": runtime.get("api_calls_planned"),
            "max_api_calls": MAX_CALLS,
            "max_cost_usd": MAX_DOLLARS,
            "api_calls_made": 0,
        }
        or runtime.get("api_calls_planned") != MAX_CASES * 2
    ):
        raise AnswerEvaluationError(
            "저장된 generation 설정이 고정 평가 계약과 다릅니다."
        )
    _check_model_manifest(model_path.resolve())
    source_raw, source_rows = read_source(source_path)
    source_sha = sha256(source_raw)
    if (
        not isinstance(manifest.get("source"), dict)
        or manifest["source"].get("source_sha256") != source_sha
    ):
        raise AnswerEvaluationError(
            "현재 corpus가 prepare에서 고정한 corpus와 다릅니다."
        )
    frozen_data = _read_json(cases_path)
    frozen_cases = _validate_cases(frozen_data, source_sha, source_rows)
    inputs = _read_json(artifact_root / "inputs.json")
    snapshot_data = _read_json(artifact_root / "snapshot.json")
    snapshot = _snapshot_from_dict(snapshot_data)
    source_manifest = manifest["source"]
    snapshot_sha = sha256_file(artifact_root / "snapshot.json")
    if snapshot.fingerprint != source_manifest.get(
        "snapshot_fingerprint"
    ) or snapshot_sha != source_manifest.get("snapshot_sha256"):
        raise AnswerEvaluationError("prepared snapshot 식별값이 manifest와 다릅니다.")
    blind_map = _read_json(artifact_root / "private" / "blind-map.json")
    cases = inputs.get("cases") if isinstance(inputs, dict) else None
    if not isinstance(cases, list) or len(cases) != MAX_CASES:
        raise AnswerEvaluationError("저장된 평가 문항 수가 20개가 아닙니다.")
    for prepared_case, frozen_case in zip(cases, frozen_cases, strict=True):
        if not isinstance(prepared_case, dict):
            raise AnswerEvaluationError("저장된 평가 문항 형식이 올바르지 않습니다.")
        prepared_base = {
            key: value for key, value in prepared_case.items() if key != "variants"
        }
        if prepared_base != frozen_case:
            raise AnswerEvaluationError(
                "저장된 문항·정답 기준이 현재 frozen cases와 다릅니다."
            )
    if not isinstance(blind_map, dict) or set(blind_map) != {
        case.get("case_id") for case in cases if isinstance(case, dict)
    }:
        raise AnswerEvaluationError("A/B mapping이 평가 문항과 일치하지 않습니다.")
    for case in cases:
        if not isinstance(case, dict) or set(case.get("variants", {})) != {"A", "B"}:
            raise AnswerEvaluationError(
                "저장된 A/B 입력 자료 형식이 올바르지 않습니다."
            )
        mapping = blind_map[case["case_id"]]
        if mapping not in ({"A": "full", "B": "rag"}, {"A": "rag", "B": "full"}):
            raise AnswerEvaluationError("고정 A/B mapping 값이 잘못되었습니다.")
        if set(mapping.values()) != {"full", "rag"}:
            raise AnswerEvaluationError("각 문항은 full과 RAG를 한 번씩 가져야 합니다.")
        for alias in ("A", "B"):
            variant = case["variants"][alias]
            mode = mapping[alias]
            prompt = variant.get("prompt")
            if (
                not isinstance(prompt, dict)
                or not isinstance(prompt.get("system"), str)
                or not isinstance(prompt.get("user"), str)
            ):
                raise AnswerEvaluationError("저장된 prompt 형식이 올바르지 않습니다.")
            prompt_obj = GenerationPrompt(prompt["system"], prompt["user"])
            if _prompt_sha(prompt_obj) != variant.get("prompt_sha256"):
                raise AnswerEvaluationError("저장된 prompt hash가 일치하지 않습니다.")
            retrieved_context = variant.get("retrieved_context")
            if mode == "rag":
                if not isinstance(retrieved_context, dict):
                    raise AnswerEvaluationError(
                        "RAG 입력에 prepared retrieval context가 없습니다."
                    )
                context = _retrieval_from_dict(retrieved_context)
                if (
                    context.snapshot_fingerprint != snapshot.fingerprint
                    or not context.evidence
                ):
                    raise AnswerEvaluationError(
                        "RAG 근거가 prepared snapshot과 맞지 않습니다."
                    )
            elif retrieved_context is not None:
                raise AnswerEvaluationError(
                    "full 입력에 불필요한 RAG context가 있습니다."
                )
    return manifest, cases, snapshot, blind_map


def _serialize_response(response: ModelResponse) -> dict[str, Any]:
    # Only fields defined by the app's model-response contract are retained.
    return {
        "raw_text": response.raw_text,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "finish_reason": response.finish_reason,
        "refusal": response.refusal,
    }


class _BudgetedCall:
    def __init__(self, delegate, ledger: BudgetLedger):
        self.delegate = delegate
        self.ledger = ledger
        self.request_id = None
        self.record = None
        self.record_path = None
        self.expected_prompt = None
        self.cost_known = False
        self.provider_error = False

    def bind(
        self,
        request_id: str,
        record: dict[str, Any],
        path: Path,
        prompt: GenerationPrompt,
    ):
        self.request_id = request_id
        self.record = record
        self.record_path = path
        self.expected_prompt = prompt
        self.cost_known = False
        self.provider_error = False

    def __call__(self, prompt: GenerationPrompt) -> ModelResponse:
        if prompt != self.expected_prompt:
            self.record.update(status="prompt_mismatch", provider_attempted=False)
            self.ledger.settle(self.request_id, 0)
            _write_json(self.record_path, self.record)
            raise AnswerEvaluationError(
                "생성 입력이 고정 prompt와 달라 provider 호출을 중단했습니다."
            )
        self.record.update(status="in_flight", provider_attempted=True)
        _write_json(self.record_path, self.record)
        started = time.perf_counter()
        try:
            response = self.delegate(prompt)
        except (
            Exception
        ) as exc:  # provider may have accepted the request before failing
            self.provider_error = True
            self.record.update(
                status="provider_error",
                error_type=type(exc).__name__,
                elapsed_seconds=time.perf_counter() - started,
                actual_cost_usd=None,
            )
            self.ledger.settle(self.request_id, None)
            _write_json(self.record_path, self.record)
            raise
        if not isinstance(response, ModelResponse):
            self.provider_error = True
            self.record.update(
                status="provider_contract_error",
                error_type=GenerationProviderResponseError.__name__,
                elapsed_seconds=time.perf_counter() - started,
                actual_cost_usd=None,
            )
            self.ledger.settle(self.request_id, None)
            _write_json(self.record_path, self.record)
            raise GenerationProviderResponseError(
                "managed provider returned an invalid response"
            )

        provider_response = _serialize_response(response)
        self.record.update(
            status="response_received",
            provider_response=provider_response,
            usage={
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
            finish_reason=response.finish_reason,
            refusal=response.refusal,
            elapsed_seconds=time.perf_counter() - started,
        )
        # Persist the raw response before settlement so an accounting failure does
        # not erase a provider response or accidentally enable a retry.
        _write_json(self.record_path, self.record)
        cost = actual_cost(
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
            {},
        )
        self.ledger.settle(self.request_id, cost)
        self.cost_known = cost is not None
        self.record.update(
            actual_cost_usd=cost,
            cost_status="estimated_from_usage" if cost is not None else "unknown",
            status="cost_known" if self.cost_known else "unknown_cost",
        )
        _write_json(self.record_path, self.record)
        return response


def _safe_status_error(exc: BaseException) -> str:
    return type(exc).__name__


def execute_prepared(
    artifact_root: Path,
    cases_path: Path,
    model_path: Path,
    env_file: Path | None,
    *,
    root: Path = ROOT,
    source_path: Path = DEFAULT_SOURCE,
    provider_factory=build_managed_model_call,
) -> dict[str, Any]:
    """Execute each A/B pair once; persist unknown/error responses and stop."""
    output = artifact_root.resolve()
    if not output.is_dir():
        raise AnswerEvaluationError("artifact-root가 준비되지 않았습니다.")
    if (output / EXECUTION_STARTED).exists():
        raise AnswerEvaluationError(
            "이 artifact-root는 이미 실행을 시작했습니다. 재실행하지 마세요."
        )
    if env_file is None:
        raise AnswerEvaluationError("--execute에는 명시적인 --env-file이 필요합니다.")
    _manifest, cases, snapshot, blind_map = _validate_prepared(
        output, cases_path, model_path, root, source_path
    )
    _validate_provider_environment(env_file)
    load_dotenv(env_file, override=False)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise AnswerEvaluationError("OpenAI API key가 실행 환경에 없습니다.")
    settings = _runtime_settings(root)
    marker = output / EXECUTION_STARTED
    _write_json(
        marker,
        {
            "started_at": datetime.now(UTC).isoformat(),
            "manifest_sha256": sha256_file(output / "manifest.json"),
            "status": "running",
        },
        exclusive=True,
    )
    ledger = ledger_at(output)
    response_dir = output / "responses"
    response_dir.mkdir(exist_ok=True)
    pair_dir = output / "pairs"
    pair_dir.mkdir(exist_ok=True)
    answerer = GenerationAnswerer(settings)
    budgeted_call = None
    results = []
    stop_status = None
    provider_close_error_type = None
    try:
        # The normal generation adapter (including parser and managed provider)
        # runs on both branches. TRACE_DIR is disabled because prompts and raw
        # outputs are stored in the explicit protected evaluation artifacts.
        from unittest.mock import patch

        with patch.dict(os.environ, {"TRACE_DIR": "", "TRACE_FULL_PROMPT": "0"}):
            for case in cases:
                case_id = case["case_id"]
                variants = case["variants"]
                pair_path = pair_dir / f"{case_id}.json"
                if pair_path.exists():
                    raise AnswerEvaluationError(
                        "pair artifact가 이미 있습니다. 재실행하지 마세요."
                    )
                pair = {
                    "case_id": case_id,
                    "status": "reserving",
                    "variants": {
                        alias: {"status": "not_called"} for alias in ("A", "B")
                    },
                }
                request_ids = {
                    alias: f"answer-{case_id}-{alias}" for alias in ("A", "B")
                }
                costs = {}
                try:
                    for alias in ("A", "B"):
                        prompt_data = variants[alias]["prompt"]
                        prompt = GenerationPrompt(
                            prompt_data["system"], prompt_data["user"]
                        )
                        costs[alias] = reserve_cost(
                            to_messages(prompt), settings.config.max_output_tokens
                        )
                        ledger.reserve(request_ids[alias], "final", costs[alias])
                        pair["variants"][alias] = {
                            "status": "reserved_not_called",
                            "request_id": request_ids[alias],
                            "reserved_cost_usd": costs[alias],
                        }
                except BudgetExceeded as exc:
                    pair["status"] = "budget_blocked_before_calls"
                    pair["budget_error_type"] = _safe_status_error(exc)
                    blocked_alias = alias
                    pair["variants"][blocked_alias] = {
                        "status": "budget_blocked",
                        "request_id": request_ids[blocked_alias],
                        "reserved_cost_usd": costs.get(blocked_alias),
                    }
                    # If the first side was reserved but the pair could not be
                    # fully reserved, it was certainly never sent to the provider.
                    for prior_alias in ("A", "B"):
                        state = pair["variants"][prior_alias]
                        if state["status"] == "reserved_not_called":
                            ledger.settle(state["request_id"], 0)
                            state["status"] = "not_called"
                    _write_json(pair_path, pair, exclusive=True)
                    results.append(pair)
                    stop_status = "stopped_budget"
                    break

                _write_json(pair_path, pair, exclusive=True)
                for alias in ("A", "B"):
                    request_id = request_ids[alias]
                    variant = variants[alias]
                    response_path = response_dir / f"{case_id}-{alias}.json"
                    prompt_data = variant["prompt"]
                    prompt = GenerationPrompt(
                        prompt_data["system"], prompt_data["user"]
                    )
                    record = {
                        "case_id": case_id,
                        "blind_variant": alias,
                        "status": "reserved",
                        "request_id": request_id,
                        "prompt_sha256": variant["prompt_sha256"],
                        "reserved_cost_usd": costs[alias],
                        "actual_cost_usd": None,
                        "provider_attempted": False,
                    }
                    _write_json(response_path, record, exclusive=True)
                    if budgeted_call is None:
                        try:
                            delegate = provider_factory(settings.config)
                        except Exception as exc:  # noqa: BLE001 - keep provider details out of artifacts
                            record.update(
                                status="provider_initialization_error",
                                error_type=_safe_status_error(exc),
                            )
                            _write_json(response_path, record)
                            ledger.settle(request_id, 0)
                            pair["variants"][alias] = {
                                "status": "provider_initialization_error"
                            }
                            peer = "B" if alias == "A" else "A"
                            peer_state = pair["variants"][peer]
                            if peer_state.get("status") == "reserved_not_called":
                                ledger.settle(peer_state["request_id"], 0)
                                peer_state["status"] = (
                                    "not_called_provider_initialization_error"
                                )
                                peer_record_path = (
                                    response_dir / f"{case_id}-{peer}.json"
                                )
                                _write_json(
                                    peer_record_path,
                                    {
                                        "case_id": case_id,
                                        "blind_variant": peer,
                                        "status": "not_called_provider_initialization_error",
                                        "request_id": peer_state["request_id"],
                                        "reserved_cost_usd": peer_state[
                                            "reserved_cost_usd"
                                        ],
                                        "actual_cost_usd": 0,
                                        "provider_attempted": False,
                                    },
                                    exclusive=True,
                                )
                            pair["status"] = "provider_initialization_error"
                            _write_json(pair_path, pair)
                            results.append(pair)
                            stop_status = "stopped_provider_error"
                            break
                        budgeted_call = _BudgetedCall(delegate, ledger)
                        answerer._client = budgeted_call
                    budgeted_call.bind(request_id, record, response_path, prompt)
                    mode = blind_map[case_id][alias]
                    started = time.perf_counter()
                    try:
                        if mode == "full":
                            answer = answerer.answer(case["question"], snapshot)
                        else:
                            context_data = variant.get("retrieved_context")
                            if not isinstance(context_data, dict):
                                raise AnswerEvaluationError(
                                    "RAG 입력에 retrieval context가 없습니다."
                                )
                            context = _retrieval_from_dict(context_data)
                            answer = answerer.answer_retrieved(
                                case["question"], context
                            )
                    except Exception as exc:  # noqa: BLE001 - record safe type after adapter failure
                        if record.get("status") in {"cost_known", "unknown_cost"}:
                            record.update(
                                status="generation_error",
                                generation_error_type=_safe_status_error(exc),
                                generation_status="failed_after_response",
                                elapsed_seconds=time.perf_counter() - started,
                            )
                            _write_json(response_path, record)
                        elif record.get("status") not in {
                            "provider_error",
                            "provider_contract_error",
                            "prompt_mismatch",
                        }:
                            record.update(
                                status="generation_error",
                                generation_error_type=_safe_status_error(exc),
                                elapsed_seconds=time.perf_counter() - started,
                            )
                            _write_json(response_path, record)
                        pair["variants"][alias] = {
                            "status": record["status"],
                            "request_id": request_id,
                        }
                        peer = "B" if alias == "A" else "A"
                        peer_state = pair["variants"][peer]
                        if peer_state.get("status") == "reserved_not_called":
                            ledger.settle(peer_state["request_id"], 0)
                            peer_state["status"] = "not_called_peer_error"
                            _write_json(
                                response_dir / f"{case_id}-{peer}.json",
                                {
                                    "case_id": case_id,
                                    "blind_variant": peer,
                                    "status": "not_called_peer_error",
                                    "request_id": peer_state["request_id"],
                                    "reserved_cost_usd": peer_state[
                                        "reserved_cost_usd"
                                    ],
                                    "actual_cost_usd": 0,
                                    "provider_attempted": False,
                                },
                                exclusive=True,
                            )
                        pair["status"] = "stopped_after_variant_error"
                        pair["variants"][alias] = {
                            "status": record["status"],
                            "request_id": request_id,
                        }
                        _write_json(pair_path, pair)
                        results.append(pair)
                        if budgeted_call.provider_error:
                            stop_status = "stopped_provider_error"
                        elif not budgeted_call.cost_known:
                            stop_status = "stopped_unknown_cost"
                        else:
                            stop_status = "stopped_generation_error"
                        break
                    record.update(
                        status=(
                            "unknown_cost"
                            if not budgeted_call.cost_known
                            else "completed"
                        ),
                        answer=answer,
                        elapsed_seconds=time.perf_counter() - started,
                    )
                    _write_json(response_path, record)
                    pair["variants"][alias] = {
                        "status": record["status"],
                        "request_id": request_id,
                        "actual_cost_usd": record.get("actual_cost_usd"),
                    }
                    _write_json(pair_path, pair)
                    if not budgeted_call.cost_known:
                        peer = "B" if alias == "A" else "A"
                        peer_state = pair["variants"][peer]
                        if peer_state.get("status") == "reserved_not_called":
                            ledger.settle(peer_state["request_id"], 0)
                            peer_state["status"] = "not_called_unknown_cost"
                            _write_json(
                                response_dir / f"{case_id}-{peer}.json",
                                {
                                    "case_id": case_id,
                                    "blind_variant": peer,
                                    "status": "not_called_unknown_cost",
                                    "request_id": peer_state["request_id"],
                                    "reserved_cost_usd": peer_state[
                                        "reserved_cost_usd"
                                    ],
                                    "actual_cost_usd": 0,
                                    "provider_attempted": False,
                                },
                                exclusive=True,
                            )
                        pair["status"] = "stopped_unknown_cost"
                        _write_json(pair_path, pair)
                        results.append(pair)
                        stop_status = "stopped_unknown_cost"
                        break
                if stop_status:
                    break
                pair["status"] = "completed"
                _write_json(pair_path, pair)
                results.append(pair)
    except BaseException as exc:
        summary = {
            "status": "runner_error",
            "error_type": _safe_status_error(exc),
            "completed_pairs": sum(
                item.get("status") == "completed" for item in results
            ),
            "recorded_pairs": len(results),
        }
        _write_json(output / "execution.json", summary)
        raise
    finally:
        if budgeted_call is not None:
            try:
                asyncio.run(budgeted_call.delegate.aclose())
            except Exception as exc:  # noqa: BLE001 - report safe close failure in summary
                provider_close_error_type = _safe_status_error(exc)
    summary = {
        "status": stop_status or "completed",
        "started_at": _read_json(marker).get("started_at"),
        "finished_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "completed_pairs": sum(item.get("status") == "completed" for item in results),
        "recorded_pairs": len(results),
        "api_calls_started": sum(
            1
            for path in response_dir.glob("*.json")
            if _read_json(path).get("provider_attempted")
        ),
        "budget_limits": {
            "total_dollars": MAX_DOLLARS,
            "dev_dollars": MAX_DOLLARS,
            "max_calls": MAX_CALLS,
        },
        "ledger_path": "ledger.json",
        "blinding": "A/B labels only; mode mapping is in private/blind-map.json",
    }
    if provider_close_error_type is not None:
        summary["provider_close_error_type"] = provider_close_error_type
    _write_json(output / "execution.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--prepare",
        action="store_true",
        help="Build local artifacts; never calls the LLM",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Run explicitly budgeted provider calls once",
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument(
        "--model", type=Path, required=True, help="Local pinned KoEn-E5-Tiny directory"
    )
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Required only for --execute; values are never printed or saved",
    )
    args = parser.parse_args(argv)
    if args.prepare:
        result = prepare_evaluation(
            args.cases, args.model, args.artifact_root, root=ROOT
        )
    else:
        if args.env_file is None:
            parser.error("--execute에는 --env-file을 지정해야 합니다.")
        result = execute_prepared(
            args.artifact_root,
            args.cases,
            args.model,
            args.env_file,
            root=ROOT,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.execute and result.get("status") != "completed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
