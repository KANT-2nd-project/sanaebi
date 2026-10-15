"""Queued, cache-free local retrieval benchmark for a frozen candidate."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from app.documents.context import DocumentContextProvider
from app.retrieval.config import DEFAULT_SPEC, MODEL_REVISION, retrieval_spec_id
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from retrieval.experiments.optimization import (
    BGE_MODEL_ID,
    BGE_REVISION,
    RERANK_CANDIDATE_COUNT,
    LocalBgeReranker,
    _verify_qrel_spans,
    digest_file,
    parse_variant_ids,
    select_variant_evidence,
    validate_frozen_qrels,
    variants_require_reranker,
)

ROOT = Path(__file__).resolve().parents[2]
REQUESTS_PER_ROUND = 48
MINIMUM_ROUNDS = 1
RESPONSE_TARGET_MS = 3000.0
_SELECTION_LOCK = threading.Lock()


def validate_benchmark_request(args, *, case_count):
    if not getattr(args, "execute_frozen_benchmark", False):
        raise ValueError(
            "explicit --execute-frozen-benchmark authorization is required"
        )
    rounds = getattr(args, "rounds", None)
    if not isinstance(rounds, int) or rounds < MINIMUM_ROUNDS:
        raise ValueError("benchmark requires at least one complete qrel round")
    if case_count != REQUESTS_PER_ROUND:
        raise ValueError("benchmark requires exactly 48 frozen development questions")
    concurrency = tuple(getattr(args, "concurrency", ()))
    if concurrency != (1, 2):
        raise ValueError("benchmark concurrency must be exactly 1 and 2")
    variants = parse_variant_ids([getattr(args, "variant", None)])
    return variants[0]


def make_timing_row(*, submitted_at, started_at, finished_at, stages_ms):
    if not submitted_at <= started_at <= finished_at:
        raise ValueError("benchmark timestamps must be monotonic")
    return {
        "queue_wait_ms": (started_at - submitted_at) * 1000.0,
        "service_ms": (finished_at - started_at) * 1000.0,
        "response_ms": (finished_at - submitted_at) * 1000.0,
        **{key: float(value) for key, value in stages_ms.items()},
    }


def _distribution(values):
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or not np.isfinite(array).all():
        raise ValueError("benchmark timing distribution must be finite and nonempty")
    return {
        "p50": float(np.percentile(array, 50, method="linear")),
        "p95": float(np.percentile(array, 95, method="linear")),
        "max": float(np.max(array)),
    }


def summarize_timing_rows(rows):
    if not rows:
        raise ValueError("benchmark requires at least one timing row")
    stage_names = sorted(
        {name for row in rows for name in row if name.endswith("_ms")}
        - {"queue_wait_ms", "service_ms", "response_ms"}
    )
    return {
        "request_count": len(rows),
        "queue_wait_ms": _distribution([row["queue_wait_ms"] for row in rows]),
        "service_ms": _distribution([row["service_ms"] for row in rows]),
        "response_ms": _distribution([row["response_ms"] for row in rows]),
        "stages_ms": {
            name: _distribution([row[name] for row in rows if name in row])
            for name in stage_names
        },
    }


def bounded_request_batches(items, concurrency):
    if concurrency < 1:
        raise ValueError("benchmark concurrency must be positive")
    for start in range(0, len(items), concurrency):
        yield items[start : start + concurrency]


def select_variant_evidence_serialized(*args, **kwargs):
    """Protect the shared legacy budget constants patched by selection."""
    with _SELECTION_LOCK:
        return select_variant_evidence(*args, **kwargs)


def _max_rss_mib():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes.
    return float(value / (1024 * 1024 if sys.platform == "darwin" else 1024))


def _pin_two_cpus():
    if not hasattr(os, "sched_getaffinity") or not hasattr(os, "sched_setaffinity"):
        raise RuntimeError("benchmark requires CPU affinity support")
    available = sorted(os.sched_getaffinity(0))
    if len(available) < 2:
        raise RuntimeError("benchmark requires two available CPUs for affinity pinning")
    selected = available[:2]
    os.sched_setaffinity(0, selected)
    return selected


def _request(*, case, variant, submitted_at, tiny, reranker, repository, snapshot):
    started_at = time.perf_counter()
    stages = {}

    stage_start = time.perf_counter()
    query = tiny.encode_queries([case["question"]])[0]
    stages["query_embedding_ms"] = (time.perf_counter() - stage_start) * 1000.0

    stage_start = time.perf_counter()
    current = repository.current_chunks(snapshot)
    if not current:
        raise ValueError("isolated vector index contains no current chunks")
    matrix = np.stack([vector for _chunk, vector in current]).astype(
        np.float32, copy=False
    )
    scores = matrix @ query
    order = sorted(
        range(len(current)),
        key=lambda index: (-float(scores[index]), current[index][0].chunk_id),
    )
    ranked = [(current[index][0], float(scores[index])) for index in order]
    stages["index_and_cosine_ms"] = (time.perf_counter() - stage_start) * 1000.0

    reranked = None
    pair_count = 0
    stage_start = time.perf_counter()
    if reranker is not None:
        documents = {doc.document_id: doc for doc in snapshot.documents}
        pairs = []
        for chunk, _score in ranked[:RERANK_CANDIDATE_COUNT]:
            document = documents[chunk.document_id]
            passage = "\n".join(
                part for part in (document.title, chunk.heading, chunk.text) if part
            )
            pairs.append((case["question"], passage))
        outputs = reranker.score_pairs(pairs)
        pair_count = len(outputs)
        reranked = sorted(
            [
                (ranked[index][0], output["score"])
                for index, output in enumerate(outputs)
            ],
            key=lambda item: (-item[1], item[0].chunk_id),
        )
    stages["rerank_ms"] = (time.perf_counter() - stage_start) * 1000.0

    stage_start = time.perf_counter()
    selected = select_variant_evidence_serialized(
        variant,
        ranked,
        snapshot,
        tiny.tokenizer,
        current_chunks=[chunk for chunk, _vector in current],
        reranked=reranked,
    )
    stages["selection_ms"] = (time.perf_counter() - stage_start) * 1000.0

    finished_at = time.perf_counter()
    timing = make_timing_row(
        submitted_at=submitted_at,
        started_at=started_at,
        finished_at=finished_at,
        stages_ms=stages,
    )
    timing["candidate_count"] = len(ranked)
    timing["selected_count"] = len(selected)
    timing["rerank_pair_count"] = pair_count
    return timing


def p95_lower_bound(observed_ms, planned_count):
    """Unmeasured durations set to zero give a conservative fixed-pool bound."""
    values = np.asarray(observed_ms, dtype=float)
    if (
        planned_count < 1
        or len(values) > planned_count
        or not np.isfinite(values).all()
        or (values < 0).any()
    ):
        raise ValueError("invalid nonnegative timing samples")
    completed = np.concatenate((values, np.zeros(planned_count - len(values))))
    return float(np.percentile(completed, 95, method="linear"))


def _run_worker(config):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    affinity = _pin_two_cpus()

    qrels_raw = Path(config["qrels"]).read_bytes()
    qrels = json.loads(qrels_raw)
    validate_frozen_qrels(qrels)
    cases = qrels["cases"]
    if len(cases) != REQUESTS_PER_ROUND:
        raise ValueError("benchmark requires exactly 48 frozen development questions")

    artifact_root = Path(config["artifact_root"])
    artifact_manifest = json.loads(
        (artifact_root / "manifest.json").read_text(encoding="utf-8")
    )
    source = artifact_manifest["source"]
    spec_id = source["retrieval_spec_id"]
    if spec_id != retrieval_spec_id(DEFAULT_SPEC):
        raise ValueError("prepared vectors do not use the frozen Tiny retrieval spec")
    source_db = artifact_root / "source/documents.sqlite3"
    database_sha = digest_file(source_db)
    snapshot = DocumentContextProvider(database_path=source_db).snapshot()
    if snapshot.fingerprint != source["snapshot_fingerprint"]:
        raise ValueError("local published snapshot differs from prepared artifacts")
    _verify_qrel_spans(cases, snapshot)

    original_index = artifact_root / "retrieval/schema-v1" / spec_id / "index.sqlite3"
    wal = Path(str(original_index) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("original vector index has an uncheckpointed WAL")
    original_index_sha = digest_file(original_index)
    variant = config["variant"]
    reranker_needed = variants_require_reranker((variant,))
    started_load = time.perf_counter()
    tiny = TinyEmbedder(Path(config["model"]))
    tiny.warmup()
    tiny_load_ms = (time.perf_counter() - started_load) * 1000.0
    reranker = None
    reranker_load_ms = 0.0
    if reranker_needed:
        reranker = LocalBgeReranker(
            Path(config["reranker_model"]),
            Path(config["reranker_manifest"]),
            batch_size=int(config["reranker_batch_size"]),
        )
        started_load = time.perf_counter()
        reranker.warmup()
        reranker_load_ms = (time.perf_counter() - started_load) * 1000.0

    with tempfile.TemporaryDirectory(prefix="sanaebi-retrieval-benchmark-") as temp:
        isolated_root = Path(temp) / "retrieval"
        target = isolated_root / "schema-v1" / spec_id / "index.sqlite3"
        target.parent.mkdir(parents=True)
        shutil.copyfile(original_index, target)
        repository = IndexRepository(isolated_root)
        warmup_case = cases[0]
        _request(
            case=warmup_case,
            variant=variant,
            submitted_at=time.perf_counter(),
            tiny=tiny,
            reranker=reranker,
            repository=repository,
            snapshot=snapshot,
        )
        rss_after_load_mib = _max_rss_mib()
        measurements = []
        planned_count = len(cases) * int(config["rounds"])
        early_rejected = False
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=int(config["concurrency"])
        ) as executor:
            for round_index in range(int(config["rounds"])):
                for batch in bounded_request_batches(cases, int(config["concurrency"])):
                    request_tasks = []
                    for case in batch:
                        submitted_at = time.perf_counter()
                        future = executor.submit(
                            _request,
                            case=case,
                            variant=variant,
                            submitted_at=submitted_at,
                            tiny=tiny,
                            reranker=reranker,
                            repository=repository,
                            snapshot=snapshot,
                        )
                        request_tasks.append((case, future))
                    for case, future in request_tasks:
                        row = future.result()
                        measurements.append(
                            {
                                "round": round_index + 1,
                                "case_id": case["case_id"],
                                **row,
                            }
                        )
                    if (
                        config.get("early_reject", False)
                        and p95_lower_bound(
                            [r["response_ms"] for r in measurements], planned_count
                        )
                        > RESPONSE_TARGET_MS
                    ):
                        early_rejected = True
                        break
                if early_rejected:
                    break

        if digest_file(original_index) != original_index_sha:
            raise ValueError("original vector index changed during benchmark")
        if digest_file(source_db) != database_sha:
            raise ValueError("published source database changed during benchmark")

    return {
        "concurrency": int(config["concurrency"]),
        "variant": variant,
        "rounds": int(config["rounds"]),
        "request_count": len(measurements),
        "planned_request_count": planned_count,
        "completed_full_measurement": len(measurements) == planned_count,
        "early_rejected": early_rejected,
        "fixed_pool_p95_lower_bound_ms": p95_lower_bound(
            [r["response_ms"] for r in measurements], planned_count
        ),
        "cache_policy": {"query_cache": False, "rerank_cache": False},
        "executor_inflight_limit": int(config["concurrency"]),
        "reranker_batch_size": (
            int(config["reranker_batch_size"]) if reranker is not None else None
        ),
        "cold_model_load_ms": {
            "tiny": tiny_load_ms,
            "bge_reranker": reranker_load_ms if reranker is not None else None,
            "total": tiny_load_ms + reranker_load_ms,
        },
        "rss_after_model_load_mib": rss_after_load_mib,
        "max_rss_mib": _max_rss_mib(),
        "cpu_affinity": affinity,
        "latency": summarize_timing_rows(measurements),
        "latency_target_ms": RESPONSE_TARGET_MS,
        "latency_target_met": (
            not early_rejected
            and len(measurements) == planned_count
            and summarize_timing_rows(measurements)["response_ms"]["p95"]
            <= RESPONSE_TARGET_MS
        ),
        "measurements": measurements,
    }


def _invoke_worker(config):
    with tempfile.TemporaryDirectory(prefix="sanaebi-benchmark-worker-") as temp:
        config_path = Path(temp) / "config.json"
        result_path = Path(temp) / "result.json"
        config["result"] = str(result_path)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "retrieval.experiments.optimization_benchmark",
                "--worker-config",
                str(config_path),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError("benchmark worker failed: " + completed.stderr[-4000:])
        return json.loads(result_path.read_text(encoding="utf-8"))


def run_benchmark(args):
    if args.output.exists():
        raise ValueError("preserve existing benchmark output; choose a new path")
    qrels_raw = args.qrels.read_bytes()
    qrels = json.loads(qrels_raw)
    validate_frozen_qrels(qrels)
    variant = validate_benchmark_request(args, case_count=len(qrels["cases"]))
    if variants_require_reranker((variant,)) and (
        args.reranker_model is None or args.reranker_manifest is None
    ):
        raise ValueError(
            "BGE benchmark candidate requires local model and manifest paths"
        )

    artifact_root = args.artifact_root.resolve()
    artifact_manifest = json.loads(
        (artifact_root / "manifest.json").read_text(encoding="utf-8")
    )
    source_index = (
        artifact_root
        / "retrieval/schema-v1"
        / artifact_manifest["source"]["retrieval_spec_id"]
        / "index.sqlite3"
    )
    source_index_sha = digest_file(source_index)
    results = []
    for concurrency in (1, 2):
        worker_config = {
            "qrels": str(args.qrels.resolve()),
            "artifact_root": str(artifact_root),
            "model": str(args.model.resolve()),
            "variant": variant,
            "rounds": args.rounds,
            "early_reject": getattr(args, "early_reject", False),
            "concurrency": concurrency,
            "reranker_batch_size": args.reranker_batch_size,
            "reranker_model": (
                str(args.reranker_model.resolve()) if args.reranker_model else None
            ),
            "reranker_manifest": (
                str(args.reranker_manifest.resolve())
                if args.reranker_manifest
                else None
            ),
        }
        results.append(_invoke_worker(worker_config))
    if digest_file(source_index) != source_index_sha:
        raise ValueError("original vector index changed across benchmark workers")

    output_record = {
        "schema_version": 1,
        "qrels_sha256": hashlib.sha256(qrels_raw).hexdigest(),
        "snapshot_fingerprint": artifact_manifest["source"]["snapshot_fingerprint"],
        "source_index_sha256": source_index_sha,
        "retrieval_spec_id": artifact_manifest["source"]["retrieval_spec_id"],
        "tiny_model_revision": MODEL_REVISION,
        "reranker_model_id": BGE_MODEL_ID
        if variants_require_reranker((variant,))
        else None,
        "reranker_revision": BGE_REVISION
        if variants_require_reranker((variant,))
        else None,
        "variant": variant,
        "rounds": args.rounds,
        "questions_per_round": REQUESTS_PER_ROUND,
        "reranker_batch_size": (
            args.reranker_batch_size if variants_require_reranker((variant,)) else None
        ),
        "query_cache_used": False,
        "rerank_cache_used": False,
        "concurrency_results": results,
    }
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.stage-", dir=output.parent
    ) as stage_dir:
        staged = Path(stage_dir) / "benchmark.json"
        staged.write_text(
            json.dumps(output_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if output.exists():
            raise ValueError(
                "benchmark output appeared during execution; preserving it"
            )
        os.replace(staged, output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--reranker-model", type=Path)
    parser.add_argument("--reranker-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--variant")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--early-reject",
        action="store_true",
        help="stop only when the fixed-pool p95 lower bound already fails",
    )
    parser.add_argument("--concurrency", type=int, nargs=2, default=(1, 2))
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--execute-frozen-benchmark", action="store_true")
    parser.add_argument("--worker-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker_config:
        config = json.loads(args.worker_config.read_text(encoding="utf-8"))
        result = _run_worker(config)
        Path(config["result"]).write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
        return
    required = (
        "qrels",
        "artifact_root",
        "model",
        "output",
        "variant",
    )
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        parser.error(
            "required options missing: "
            + ", ".join("--" + name.replace("_", "-") for name in missing)
        )
    try:
        run_benchmark(args)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
