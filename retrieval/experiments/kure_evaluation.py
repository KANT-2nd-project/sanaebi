"""Offline, provenance-checked KURE/Tiny retrieval evaluation.

The runner never downloads a model, calls a generation API, or reuses query
embeddings. KURE document vectors are reused only from the recorded pilot;
Tiny vectors are read from an isolated copy of the prepared index.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import resource
import shutil
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.documents.context import DocumentContextProvider
from app.retrieval.config import (
    DEFAULT_SPEC,
    QUERY_PREFIX,
    retrieval_spec_id,
)
from app.retrieval.config import (
    MODEL_ID as TINY_MODEL_ID,
)
from app.retrieval.config import (
    MODEL_REVISION as TINY_REVISION,
)
from app.retrieval.config import (
    VECTOR_DIMENSION as TINY_DIMENSION,
)
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from retrieval.experiments.calibration_metrics import claim_metrics
from retrieval.experiments.calibration_search import evidence_items, select_evidence
from retrieval.experiments.kure_gate import gate_hits
from retrieval.experiments.optimization import (
    _verify_qrel_spans,
    validate_frozen_qrels,
)

ROOT = Path(__file__).resolve().parents[2]
QREL_V3_PATH = ROOT / "retrieval/reports/2026-10-15-retrieval-v3/qrels-v3.json"
KURE_MODEL_ID = "nlpai-lab/KURE-v1"
KURE_REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"
KURE_DIMENSION = 1024
QUERY_LIMIT = 512
TOP_K = 20
TINY_C_THRESHOLD = 0.35
EXPECTED_CHUNK_COUNT = 298
DEVELOPMENT_CASE_COUNT = 68
CONFIRMATION_CASE_COUNT = 40
CONFIRMATION_RELATED_COUNT = 30
CONFIRMATION_GATE_NEGATIVE_COUNT = 10
CONFIRMATION_ANSWERABILITY_COUNTS = {
    "answerable": 20,
    "partial": 5,
    "unanswerable": 15,
}


@dataclass(frozen=True)
class QueryEncoder:
    model_id: str
    revision: str
    dimension: int
    tokenizer: Any
    count_query_tokens: Callable[[str], int]
    encode_queries: Callable[[list[str]], np.ndarray]


def digest_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_file(path: str | Path) -> tuple[dict[str, Any], bytes]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value, raw


def _reject_duplicate_case_ids(payload: dict[str, Any]) -> None:
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise TypeError("frozen cases must be a list")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = case.get("case_id")
        if isinstance(case_id, str) and case_id in seen:
            raise ValueError(f"duplicate case ID: {case_id}")
        if isinstance(case_id, str):
            seen.add(case_id)


def _validate_case_set(payload: dict[str, Any], *, phase: str) -> list[dict[str, Any]]:
    _reject_duplicate_case_ids(payload)
    validate_frozen_qrels(payload)
    cases = payload["cases"]
    seen: set[str] = set()
    for case in cases:
        case_id = case["case_id"]
        if case_id in seen:
            raise ValueError(f"duplicate case ID: {case_id}")
        seen.add(case_id)
        if type(case.get("related")) is not bool:
            raise ValueError(f"{case_id}: related must be a Boolean")
        if type(case.get("gate_negative")) is not bool:
            raise ValueError(f"{case_id}: gate_negative must be a Boolean")
        if case["related"] and case["gate_negative"]:
            raise ValueError(f"{case_id}: related cases cannot be gate negatives")

    if phase == "development":
        if len(cases) != DEVELOPMENT_CASE_COUNT:
            raise ValueError(
                f"development requires exactly {DEVELOPMENT_CASE_COUNT} frozen cases"
            )
        canonical, _ = _json_file(QREL_V3_PATH)
        canonical_ids = [case["case_id"] for case in canonical["cases"]]
        if [case["case_id"] for case in cases[: len(canonical_ids)]] != canonical_ids:
            raise ValueError("development must start with the canonical qrel-v3 cases")
        canonical_cases = cases[: len(canonical_ids)]
        if any(case["gate_negative"] for case in canonical_cases):
            raise ValueError("canonical qrel-v3 cases cannot be gate negatives")
        additions = cases[len(canonical_ids) :]
        if (
            sum(case["related"] for case in additions) != 10
            or sum(case["gate_negative"] for case in additions) != 10
        ):
            raise ValueError(
                "the 20 additional development cases must contain 10 related and 10 gate negatives"
            )
    elif phase == "confirmation":
        if len(cases) != CONFIRMATION_CASE_COUNT:
            raise ValueError(
                f"confirmation requires exactly {CONFIRMATION_CASE_COUNT} frozen cases"
            )
        if sum(case["related"] for case in cases) != CONFIRMATION_RELATED_COUNT:
            raise ValueError("confirmation related-case count is not 30")
        if sum(case["gate_negative"] for case in cases) != (
            CONFIRMATION_GATE_NEGATIVE_COUNT
        ):
            raise ValueError("confirmation gate-negative count is not 10")
        counts = {
            answerability: sum(case["answerability"] == answerability for case in cases)
            for answerability in CONFIRMATION_ANSWERABILITY_COUNTS
        }
        if counts != CONFIRMATION_ANSWERABILITY_COUNTS:
            raise ValueError("confirmation answerability counts do not match 20/5/15")
    else:
        raise ValueError(f"unsupported evaluation phase: {phase}")
    return cases


def _validate_benchmark_cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the frozen development file used by the optional benchmark."""
    return _validate_case_set(payload, phase="development")


def _validate_original_qrel_cases(cases, canonical_cases):
    canonical_by_id = {case["case_id"]: case for case in canonical_cases}
    for case in cases:
        original = canonical_by_id.get(case["case_id"])
        if original is None:
            continue
        candidate = {
            key: value
            for key, value in case.items()
            if key not in {"related", "gate_negative"}
        }
        if candidate != original:
            raise ValueError(f"{case['case_id']}: canonical qrel-v3 content changed")


def _validate_candidate_freeze(
    path: str | Path,
    *,
    expected_case_sha: str,
    case_sha_field: str,
) -> dict[str, Any]:
    freeze, raw = _json_file(path)
    if freeze.get("status") != "frozen_candidate":
        raise ValueError("candidate freeze must have status frozen_candidate")
    if freeze.get("candidate") not in (None, "kure_top20_question_gate"):
        raise ValueError("candidate freeze names a different candidate")
    if freeze.get("model_id") != KURE_MODEL_ID:
        raise ValueError("candidate freeze model_id mismatch")
    if freeze.get("model_revision") != KURE_REVISION:
        raise ValueError("candidate freeze model revision mismatch")
    if type(freeze.get("top_k")) is not int or freeze["top_k"] != TOP_K:
        raise ValueError("candidate freeze top_k must be 20")
    threshold = freeze.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise TypeError("candidate freeze threshold must be numeric")
    if not math.isfinite(threshold):
        raise ValueError("candidate freeze threshold must be finite")
    if freeze.get(case_sha_field) != expected_case_sha:
        raise ValueError(f"candidate freeze {case_sha_field} mismatch")

    development_cases_sha = freeze.get("development_cases_sha256")
    development_results_sha = freeze.get("development_results_sha256")
    development_results_path = freeze.get("development_results_path")
    if not all(
        isinstance(value, str) and len(value) == 64
        for value in (development_cases_sha, development_results_sha)
    ):
        raise ValueError("candidate freeze is missing development SHA-256 values")
    if not isinstance(development_results_path, str) or not development_results_path:
        raise ValueError("candidate freeze is missing development_results_path")
    development_path = Path(development_results_path)
    if not development_path.is_file():
        raise ValueError("frozen development results file is unavailable")
    actual_development_sha = digest_file(development_path)
    if actual_development_sha != development_results_sha:
        raise ValueError("frozen development results SHA-256 mismatch")
    development, _ = _json_file(development_path)
    if (
        development.get("phase") != "development"
        or development.get("model_id") != KURE_MODEL_ID
        or development.get("model_revision") != KURE_REVISION
        or development.get("cases_sha256") != development_cases_sha
    ):
        raise ValueError("frozen development result provenance mismatch")
    return {
        "path": str(Path(path).resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "threshold": float(threshold),
        "development_cases_sha256": development_cases_sha,
        "development_results_sha256": actual_development_sha,
        "development_results_path": str(development_path.resolve()),
    }


def _validate_spec_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise TypeError("prepared artifact manifest has no source section")
    if source.get("retrieval_spec") != DEFAULT_SPEC.to_dict():
        raise ValueError("prepared artifact does not use the pinned Tiny source spec")
    spec_id = retrieval_spec_id(DEFAULT_SPEC)
    if source.get("retrieval_spec_id") != spec_id:
        raise ValueError("prepared artifact retrieval spec ID mismatch")
    return source


def _copy_isolated_inputs(artifact_root: Path, staging: Path, source: dict[str, Any]):
    published_database = source.get("published_database")
    retrieval_root = source.get("isolated_retrieval_root")
    spec_id = source.get("retrieval_spec_id")
    if not all(
        isinstance(value, str) and value
        for value in (published_database, retrieval_root, spec_id)
    ):
        raise ValueError("prepared artifact source paths are malformed")
    original_source = artifact_root / published_database
    original_index = (
        artifact_root / retrieval_root / "schema-v1" / spec_id / "index.sqlite3"
    )
    for original in (original_source, original_index):
        if not original.is_file():
            raise ValueError(f"prepared artifact input is missing: {original}")
        wal = Path(str(original) + "-wal")
        if wal.exists() and wal.stat().st_size:
            raise ValueError(f"prepared artifact has a nonempty SQLite WAL: {wal}")
    before = {
        "source": digest_file(original_source),
        "index": digest_file(original_index),
    }
    copied_source = staging / "isolated-input/source/documents.sqlite3"
    copied_index = (
        staging / "isolated-input/retrieval/schema-v1" / spec_id / "index.sqlite3"
    )
    copied_source.parent.mkdir(parents=True, exist_ok=True)
    copied_index.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original_source, copied_source)
    shutil.copyfile(original_index, copied_index)
    copied = {
        "source": digest_file(copied_source),
        "index": digest_file(copied_index),
    }
    after = {
        "source": digest_file(original_source),
        "index": digest_file(original_index),
    }
    if before != copied or before != after:
        raise ValueError("prepared artifact changed during isolated copy")
    return {
        "original_source": original_source,
        "original_index": original_index,
        "copied_source": copied_source,
        "copied_index": copied_index,
        "source_sha256": before["source"],
        "index_sha256": before["index"],
    }


def _validate_normalized_matrix(matrix, *, expected_rows: int, dimension: int):
    array = np.asarray(matrix)
    if (
        array.dtype != np.float32
        or array.shape != (expected_rows, dimension)
        or not np.isfinite(array).all()
    ):
        raise ValueError("document vector matrix has an invalid dtype, shape, or value")
    norms = np.linalg.norm(array, axis=1)
    if array.shape[0] and not np.allclose(norms, 1.0, rtol=1e-4, atol=1e-4):
        raise ValueError("document vectors are not L2 normalized")


def _validate_tiny_matrix(current):
    matrix = np.asarray([vector for _, vector in current], dtype=np.float32)
    if matrix.shape != (len(current), TINY_DIMENSION):
        raise ValueError(
            "Tiny source vectors do not match the 384-dimensional contract"
        )
    _validate_normalized_matrix(
        matrix, expected_rows=len(current), dimension=TINY_DIMENSION
    )
    return matrix


def _validate_kure_pilot(
    pilot_root: Path,
    *,
    snapshot_fingerprint: str,
    chunk_ids: list[str],
    source_sha256: str,
    index_sha256: str,
    canonical_qrels_sha256: str,
):
    results_path = pilot_root / "kure/results.json"
    vectors_path = pilot_root / "kure/vectors.npy"
    result, _ = _json_file(results_path)
    if result.get("model") != "kure" or result.get("revision") != KURE_REVISION:
        raise ValueError("KURE pilot model revision mismatch")
    if result.get("qrels_sha") != canonical_qrels_sha256:
        raise ValueError("KURE pilot qrel-v3 SHA-256 mismatch")
    if result.get("snapshot") != snapshot_fingerprint:
        raise ValueError("KURE pilot snapshot mismatch")
    if result.get("chunks") != len(chunk_ids) or len(chunk_ids) != EXPECTED_CHUNK_COUNT:
        raise ValueError("KURE pilot chunk count mismatch")
    maximum_document_tokens = result.get("max_document_tokens")
    if (
        type(maximum_document_tokens) is not int
        or maximum_document_tokens < 1
        or maximum_document_tokens > 8192
    ):
        raise ValueError("KURE pilot document input exceeds its 8192-token contract")
    source_hashes = result.get("source_hashes")
    if not isinstance(source_hashes, dict) or not {
        source_sha256,
        index_sha256,
    }.issubset(set(source_hashes.values())):
        raise ValueError("KURE pilot source database/index SHA mismatch")
    rankings = result.get("rankings")
    if not isinstance(rankings, list) or not rankings:
        raise ValueError("KURE pilot has no recorded ranking provenance")
    expected_ids = set(chunk_ids)
    for row in rankings:
        ranking = row.get("ranking") if isinstance(row, dict) else None
        ids = [item.get("chunk_id") for item in ranking or []]
        if len(ids) != len(expected_ids) or set(ids) != expected_ids:
            raise ValueError("KURE pilot ranking chunk order/source set mismatch")
    matrix = np.load(vectors_path, allow_pickle=False)
    _validate_normalized_matrix(
        matrix, expected_rows=len(chunk_ids), dimension=KURE_DIMENSION
    )
    queries_path = pilot_root / "kure/queries.npy"
    queries = np.load(queries_path, allow_pickle=False)
    _validate_normalized_matrix(
        queries, expected_rows=len(rankings), dimension=KURE_DIMENSION
    )
    canonical_qrels, _ = _json_file(QREL_V3_PATH)
    expected_case_ids = [case["case_id"] for case in canonical_qrels["cases"]]
    if [row.get("case_id") for row in rankings] != expected_case_ids:
        raise ValueError("KURE pilot query/ranking rows do not match canonical qrel-v3")

    for query, row in zip(queries, rankings, strict=True):
        ranked = row["ranking"]
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("chunk_id"), str)
            or type(item.get("score")) not in (int, float)
            or not math.isfinite(item["score"])
            for item in ranked
        ):
            raise ValueError(f"{row['case_id']}: malformed KURE pilot ranking")
        scores = matrix @ query
        order = sorted(
            range(len(chunk_ids)),
            key=lambda index: (-float(scores[index]), chunk_ids[index]),
        )
        expected_ids = [chunk_ids[index] for index in order]
        expected_scores = [float(scores[index]) for index in order]
        actual_ids = [item["chunk_id"] for item in ranked]
        actual_scores = [item["score"] for item in ranked]
        if actual_ids != expected_ids or not np.allclose(
            actual_scores, expected_scores, rtol=1e-6, atol=1e-7
        ):
            raise ValueError(
                f"{row['case_id']}: KURE pilot ranking differs from source-ordered vectors"
            )
    return matrix, {
        "model_id": KURE_MODEL_ID,
        "model_revision": KURE_REVISION,
        "vector_path": str(vectors_path.resolve()),
        "vector_sha256": digest_file(vectors_path),
        "pilot_results_path": str(results_path.resolve()),
        "pilot_results_sha256": digest_file(results_path),
        "pilot_queries_path": str(queries_path.resolve()),
        "pilot_queries_sha256": digest_file(queries_path),
        "pilot_query_vectors_used_for_evaluation": False,
        "pilot_qrels_sha256": result["qrels_sha"],
        "source_hashes": source_hashes,
        "snapshot_fingerprint": snapshot_fingerprint,
        "chunk_count": len(chunk_ids),
        "max_document_tokens": maximum_document_tokens,
        "dimension": KURE_DIMENSION,
        "dtype": str(matrix.dtype),
        "normalization": "l2",
    }


def _load_query_encoder(model: str, model_path: Path) -> QueryEncoder:
    if not model_path.is_dir():
        raise ValueError("an explicit local model directory is required")
    if model == "tiny":
        embedder = TinyEmbedder(model_path)
        embedder.warmup()
        tokenizer = embedder.tokenizer

        def count_query_tokens(question: str) -> int:
            return len(
                tokenizer(
                    QUERY_PREFIX + question,
                    add_special_tokens=True,
                    truncation=False,
                )["input_ids"]
            )

        return QueryEncoder(
            model_id=TINY_MODEL_ID,
            revision=TINY_REVISION,
            dimension=TINY_DIMENSION,
            tokenizer=tokenizer,
            count_query_tokens=count_query_tokens,
            encode_queries=embedder.encode_queries,
        )
    if model != "kure":
        raise ValueError(f"unsupported model: {model}")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import torch
    from transformers import AutoModel, AutoTokenizer

    model_path = model_path.resolve()
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path), local_files_only=True, trust_remote_code=False
    )
    model_config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    configured_revision = model_config.get("_commit_hash")
    if configured_revision is not None and configured_revision != KURE_REVISION:
        raise ValueError("local KURE model config revision mismatch")
    if model_path.name != KURE_REVISION and configured_revision != KURE_REVISION:
        raise ValueError("KURE model path must identify the pinned local revision")
    pooling_path = model_path / "1_Pooling/config.json"
    pooling = json.loads(pooling_path.read_text(encoding="utf-8"))
    if not pooling.get("pooling_mode_cls_token") or pooling.get(
        "pooling_mode_mean_tokens"
    ):
        raise ValueError("KURE pooling configuration must use CLS pooling")
    model_obj = (
        AutoModel.from_pretrained(
            str(model_path), local_files_only=True, trust_remote_code=False
        )
        .float()
        .to("cpu")
        .eval()
    )
    if getattr(model_obj.config, "hidden_size", None) != KURE_DIMENSION:
        raise ValueError(
            "KURE hidden size does not match the 1024-dimensional contract"
        )
    torch.set_num_threads(2)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        if torch.get_num_interop_threads() != 1:
            raise

    def count_query_tokens(question: str) -> int:
        return len(
            tokenizer(
                question,
                add_special_tokens=True,
                truncation=False,
            )["input_ids"]
        )

    def encode_queries(questions: list[str]) -> np.ndarray:
        batch = tokenizer(
            questions,
            padding=True,
            truncation=False,
            return_tensors="pt",
        )
        if batch["input_ids"].shape[1] > QUERY_LIMIT:
            raise ValueError("query exceeds the 512-token input limit")
        with torch.inference_mode():
            hidden = model_obj(**batch).last_hidden_state[:, 0]
            vectors = torch.nn.functional.normalize(hidden.float(), p=2, dim=1)
        return vectors.detach().cpu().numpy().astype(np.float32, copy=False)

    return QueryEncoder(
        model_id=KURE_MODEL_ID,
        revision=KURE_REVISION,
        dimension=KURE_DIMENSION,
        tokenizer=tokenizer,
        count_query_tokens=count_query_tokens,
        encode_queries=encode_queries,
    )


def _set_cpu_affinity_two():
    if not (hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity")):
        return None
    original = set(os.sched_getaffinity(0))
    if original:
        os.sched_setaffinity(0, sorted(original)[:2])
    return original


def _restore_cpu_affinity(original):
    if original is not None and hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, original)


def _peak_rss_mib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return float(peak / (1024 * 1024 if sys.platform == "darwin" else 1024))


def _rank_case(
    case: dict[str, Any],
    snapshot,
    current,
    matrix: np.ndarray,
    encoder: QueryEncoder,
    *,
    model: str,
    phase: str,
    threshold: float | None,
):
    total_started = time.perf_counter()
    question = case["question"]
    query_tokens = encoder.count_query_tokens(question)
    if query_tokens > QUERY_LIMIT:
        raise ValueError(f"{case['case_id']}: query exceeds the 512-token limit")
    started = time.perf_counter()
    vector = np.asarray(encoder.encode_queries([question]), dtype=np.float32)
    encode_ms = (time.perf_counter() - started) * 1000
    if vector.shape != (1, encoder.dimension) or not np.isfinite(vector).all():
        raise ValueError("query encoder returned an invalid vector")
    if not math.isclose(
        float(np.linalg.norm(vector[0])), 1.0, rel_tol=1e-4, abs_tol=1e-4
    ):
        raise ValueError("query vector is not L2 normalized")

    started = time.perf_counter()
    scores = matrix @ vector[0]
    order = sorted(
        range(len(current)),
        key=lambda index: (-float(scores[index]), current[index][0].chunk_id),
    )
    ranked = [(current[index][0], float(scores[index])) for index in order]
    rank_ms = (time.perf_counter() - started) * 1000
    maximum = ranked[0][1] if ranked else float("-inf")

    gate_rejected = False
    if model == "tiny":
        gate_rejected = not ranked or maximum < TINY_C_THRESHOLD
        hits = [(chunk, score) for chunk, score in ranked if score >= TINY_C_THRESHOLD]
        policy = "tiny_c_threshold_035_all"
        applied_threshold = TINY_C_THRESHOLD
    elif phase == "development":
        hits = ranked[:TOP_K]
        policy = "kure_raw_top20_no_gate"
        applied_threshold = None
    else:
        if threshold is None:
            raise ValueError("confirmation KURE run requires a frozen threshold")
        selected_ids = {
            chunk_id
            for chunk_id, _ in gate_hits(
                [(chunk.chunk_id, score) for chunk, score in ranked],
                threshold,
                maximum=TOP_K,
            )
        }
        gate_rejected = not selected_ids
        hits = [
            (chunk, score) for chunk, score in ranked if chunk.chunk_id in selected_ids
        ]
        policy = "kure_question_gate_top20"
        applied_threshold = threshold

    started = time.perf_counter()
    evidence = select_evidence(
        hits,
        snapshot,
        float("inf"),
        encoder.tokenizer,
        None,
        total_chars=None,
        per_evidence_chars=None,
    )
    evidence_ms = (time.perf_counter() - started) * 1000
    metrics = claim_metrics(evidence_items(evidence), case)
    return {
        "case_id": case["case_id"],
        "question": question,
        "related": case["related"],
        "gate_negative": case["gate_negative"],
        "answerability": case["answerability"],
        "maximum": maximum,
        "threshold": applied_threshold,
        "gate_rejected": gate_rejected,
        "complete": metrics["complete"],
        "included": metrics["included"],
        "required": metrics["required"],
        "recall": metrics["recall"],
        "missing_claims": metrics["missing_claims"],
        "policy": policy,
        "selected_chunk_count": len(hits),
        "selected_chunk_ids": [chunk.chunk_id for chunk, _ in hits],
        "chars": sum(len(item.text) for item in evidence),
        "evidence": [asdict(item) for item in evidence],
        "ranking": [
            {"chunk_id": chunk.chunk_id, "score": score} for chunk, score in ranked
        ],
        "query_tokens": query_tokens,
        "encode_ms": encode_ms,
        "rank_ms": rank_ms,
        "evidence_ms": evidence_ms,
        "total_ms": (time.perf_counter() - total_started) * 1000,
    }


def _validate_output_rows(cases, rows):
    expected_ids = [case["case_id"] for case in cases]
    actual_ids = [row.get("case_id") for row in rows]
    if len(actual_ids) != len(set(actual_ids)) or actual_ids != expected_ids:
        raise ValueError("evaluation output case IDs differ from the frozen input")
    required = {
        "case_id",
        "related",
        "gate_negative",
        "answerability",
        "maximum",
        "gate_rejected",
        "complete",
        "included",
        "required",
        "evidence",
        "ranking",
    }
    if any(not required.issubset(row) for row in rows):
        raise ValueError("evaluation output row is incomplete")


def _run_benchmark(cases, *, snapshot, current, matrix, encoder, threshold):
    if len(cases) < 48:
        raise ValueError("KURE benchmark requires at least 48 development cases")
    benchmark_cases = cases[:48]
    lock = threading.Lock()
    reports = []
    for concurrency in (1, 2):
        jobs = [
            (round_number, case)
            for round_number in range(3)
            for case in benchmark_cases
        ]
        timings: list[float] = []
        iterator = iter(jobs)
        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            pending = set()
            while pending or completed < len(jobs):
                while len(pending) < concurrency:
                    try:
                        _, case = next(iterator)
                    except StopIteration:
                        break

                    submitted = time.perf_counter()

                    def run_one(case=case, submitted=submitted):
                        with lock:
                            _rank_case(
                                case,
                                snapshot,
                                current,
                                matrix,
                                encoder,
                                model="kure",
                                phase="confirmation",
                                threshold=threshold,
                            )
                        return (time.perf_counter() - submitted) * 1000

                    pending.add(executor.submit(run_one))
                done, pending = concurrent.futures.wait(
                    pending,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    timings.append(future.result())
                    completed += 1
        reports.append(
            {
                "concurrency": concurrency,
                "requested": 48 * 3,
                "completed": completed,
                "p95_ms": float(np.percentile(timings, 95)),
                "max_rss_mib": _peak_rss_mib(),
                "rss_scope": "process high-water mark through this concurrency batch",
            }
        )
    return {
        "case_ids": [case["case_id"] for case in benchmark_cases],
        "rounds": 3,
        "serialization": "encode_rank_and_evidence_merge_under_one_lock",
        "runs": reports,
    }


def evaluate(args, *, encoder_factory=None):
    """Run one frozen evaluation into a new, atomically published output folder."""
    output = Path(args.output)
    if output.exists():
        raise ValueError("preserve existing output; use a new explicit output path")
    if args.model not in {"tiny", "kure"}:
        raise ValueError("model must be tiny or kure")
    if args.phase not in {"development", "confirmation"}:
        raise ValueError("phase must be development or confirmation")
    if args.benchmark and (args.phase != "development" or args.model != "kure"):
        raise ValueError("--benchmark requires development phase and KURE model")

    cases_payload, cases_raw = _json_file(args.cases)
    cases_sha = hashlib.sha256(cases_raw).hexdigest()
    cases = (
        _validate_benchmark_cases(cases_payload)
        if args.benchmark
        else _validate_case_set(cases_payload, phase=args.phase)
    )
    canonical_qrels, canonical_raw = _json_file(QREL_V3_PATH)
    validate_frozen_qrels(canonical_qrels)
    canonical_qrels_sha = hashlib.sha256(canonical_raw).hexdigest()
    _validate_original_qrel_cases(cases, canonical_qrels["cases"])

    freeze = None
    threshold = None
    if args.phase == "confirmation" or args.benchmark:
        if args.candidate_freeze is None:
            raise ValueError(
                "confirmation and benchmark runs require --candidate-freeze"
            )
        case_sha_field = (
            "development_cases_sha256"
            if args.benchmark
            else "confirmation_cases_sha256"
        )
        freeze = _validate_candidate_freeze(
            args.candidate_freeze,
            expected_case_sha=cases_sha,
            case_sha_field=case_sha_field,
        )
        threshold = freeze["threshold"]

    manifest, _ = _json_file(Path(args.artifact_root) / "manifest.json")
    source_manifest = _validate_spec_manifest(manifest)
    if not Path(args.model_path).is_dir():
        raise ValueError("an explicit local model directory is required")
    if args.model == "kure" and not Path(args.pilot_root).is_dir():
        raise ValueError("the original KURE pilot directory is required")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("preserve existing output; use a new explicit output path")

    original_affinity = _set_cpu_affinity_two()
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}.staging-", dir=output.parent
        ) as temporary:
            staging = Path(temporary)
            index_started = time.perf_counter()
            copied = _copy_isolated_inputs(
                Path(args.artifact_root), staging, source_manifest
            )
            snapshot = DocumentContextProvider(
                database_path=copied["copied_source"]
            ).snapshot()
            if snapshot.fingerprint != source_manifest.get("snapshot_fingerprint"):
                raise ValueError("copied document snapshot fingerprint mismatch")
            repository = IndexRepository(staging / "isolated-input/retrieval")
            current = repository.current_chunks(snapshot)
            if len(current) != EXPECTED_CHUNK_COUNT:
                raise ValueError("the frozen source must contain exactly 298 chunks")
            _verify_qrel_spans(cases, snapshot)
            chunk_ids = [chunk.chunk_id for chunk, _ in current]

            if args.model == "tiny":
                matrix = _validate_tiny_matrix(current)
                vector_provenance = {
                    "model_id": TINY_MODEL_ID,
                    "model_revision": TINY_REVISION,
                    "vector_sha256": hashlib.sha256(
                        np.ascontiguousarray(matrix).tobytes()
                    ).hexdigest(),
                    "vector_source": "isolated copied Tiny index",
                    "dimension": TINY_DIMENSION,
                    "dtype": str(matrix.dtype),
                    "normalization": "l2",
                    "chunk_count": len(chunk_ids),
                }
            else:
                matrix, vector_provenance = _validate_kure_pilot(
                    Path(args.pilot_root),
                    snapshot_fingerprint=snapshot.fingerprint,
                    chunk_ids=chunk_ids,
                    source_sha256=copied["source_sha256"],
                    index_sha256=copied["index_sha256"],
                    canonical_qrels_sha256=canonical_qrels_sha,
                )
            index_seconds = time.perf_counter() - index_started

            load_started = time.perf_counter()
            encoder = (
                encoder_factory(args.model, Path(args.model_path))
                if encoder_factory
                else _load_query_encoder(args.model, Path(args.model_path))
            )
            expected_model_id = KURE_MODEL_ID if args.model == "kure" else TINY_MODEL_ID
            expected_revision = KURE_REVISION if args.model == "kure" else TINY_REVISION
            expected_dimension = (
                KURE_DIMENSION if args.model == "kure" else TINY_DIMENSION
            )
            if (
                encoder.model_id != expected_model_id
                or encoder.revision != expected_revision
                or encoder.dimension != expected_dimension
            ):
                raise ValueError(
                    "query encoder does not match the pinned model contract"
                )

            warmup_started = time.perf_counter()
            warmup_tokens = encoder.count_query_tokens("워밍업 질문입니다.")
            if warmup_tokens > QUERY_LIMIT:
                raise ValueError("warmup query exceeds the query token limit")
            warmup_vector = np.asarray(
                encoder.encode_queries(["워밍업 질문입니다."]), dtype=np.float32
            )
            if (
                warmup_vector.shape != (1, encoder.dimension)
                or not np.isfinite(warmup_vector).all()
            ):
                raise ValueError("query encoder warmup returned an invalid vector")
            if not math.isclose(
                float(np.linalg.norm(warmup_vector[0])),
                1.0,
                rel_tol=1e-4,
                abs_tol=1e-4,
            ):
                raise ValueError("query encoder warmup vector is not normalized")
            warmup_seconds = time.perf_counter() - warmup_started
            load_seconds = time.perf_counter() - load_started

            benchmark = None
            rows = []
            if args.benchmark:
                benchmark = _run_benchmark(
                    cases,
                    snapshot=snapshot,
                    current=current,
                    matrix=matrix,
                    encoder=encoder,
                    threshold=threshold,
                )
            else:
                rows = [
                    _rank_case(
                        case,
                        snapshot,
                        current,
                        matrix,
                        encoder,
                        model=args.model,
                        phase=args.phase,
                        threshold=threshold,
                    )
                    for case in cases
                ]
                _validate_output_rows(cases, rows)

            source_after = {
                "source": digest_file(copied["original_source"]),
                "index": digest_file(copied["original_index"]),
            }
            if source_after != {
                "source": copied["source_sha256"],
                "index": copied["index_sha256"],
            }:
                raise ValueError("prepared source changed while evaluating its copy")

            results = {
                "schema_version": 1,
                "phase": args.phase,
                "run_type": "benchmark" if args.benchmark else "evaluation",
                "model": args.model,
                "model_id": encoder.model_id,
                "model_revision": encoder.revision,
                "cases_path": str(Path(args.cases).resolve()),
                "cases_sha256": cases_sha,
                "case_count": len(cases),
                "qrel_v3_sha256": canonical_qrels_sha,
                "snapshot_fingerprint": snapshot.fingerprint,
                "source": {
                    "artifact_root": str(Path(args.artifact_root).resolve()),
                    "original_source_path": str(copied["original_source"].resolve()),
                    "original_index_path": str(copied["original_index"].resolve()),
                    "copied_source_sha256": copied["source_sha256"],
                    "copied_index_sha256": copied["index_sha256"],
                    "source_sha_before_after_match": True,
                    "chunk_count": len(current),
                    "chunk_ids_sha256": hashlib.sha256(
                        "\n".join(chunk_ids).encode("utf-8")
                    ).hexdigest(),
                },
                "vector_provenance": vector_provenance,
                "query_cache_used": False,
                "query_prefix": QUERY_PREFIX if args.model == "tiny" else "",
                "selection": {
                    "policy": (
                        "frozen_kure_top20_question_gate"
                        if args.model == "kure" and args.phase == "confirmation"
                        else "kure_raw_top20_no_gate"
                        if args.model == "kure"
                        else "tiny_c_cosine_035_unlimited"
                    ),
                    "maximum": TOP_K if args.model == "kure" else None,
                    "threshold": threshold
                    if args.model == "kure"
                    else TINY_C_THRESHOLD,
                    "threshold_applied_in_development": False,
                },
                "candidate_freeze": freeze,
                "timing": {
                    "snapshot_copy_and_vector_load_seconds": index_seconds,
                    "model_load_and_warmup_seconds": load_seconds,
                    "warmup_seconds": warmup_seconds,
                    "peak_rss_mib": _peak_rss_mib(),
                    "cpu_limit": 2,
                },
                "rows": rows,
                "benchmark": benchmark,
            }
            (staging / "results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(staging, output)
    finally:
        _restore_cpu_affinity(original_affinity)
    return output / "results.json"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run offline KURE/Tiny retrieval evaluation on frozen cases."
    )
    parser.add_argument(
        "--phase", choices=("development", "confirmation"), required=True
    )
    parser.add_argument("--model", choices=("tiny", "kure"), required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--candidate-freeze", type=Path)
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="benchmark KURE on the first 48 development cases using a frozen candidate threshold",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        path = evaluate(args)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"KURE evaluation failed: {exc}") from exc
    print(path)


if __name__ == "__main__":
    main()
