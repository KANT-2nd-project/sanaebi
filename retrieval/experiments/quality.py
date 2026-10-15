"""Frozen sequential retrieval comparison using local Tiny and isolated SQLite."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from app.documents.context import DocumentContextProvider
from app.documents.repository import DocumentRepository
from app.documents.transfer import _apply_rows, read_source, sha
from app.retrieval.baseline import prepare_baseline, validate_baseline
from app.retrieval.config import (
    CONTEXTUAL_SPEC,
    DEFAULT_SPEC,
    MODEL_ID,
    MODEL_REVISION,
)
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from app.retrieval.search import SearchConfig
from app.retrieval.service import RetrievalService

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "retrieval/reports/2026-10-15-rag-quality-improvement/cases.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def covers(spans, required):
    intervals = sorted((s.start, s.end) for s in spans)
    cursor = required["start"]
    for start, end in intervals:
        if start > cursor:
            break
        cursor = max(cursor, end)
        if cursor >= required["end"]:
            return True
    return False


def complete(items, case):
    spans = [
        s
        for knowledge_id, chunk_spans in items
        if knowledge_id == case["document_id"]
        for s in chunk_spans
    ]
    return all(covers(spans, required) for required in case["required_spans"])


def validate_snapshot(snapshot, documents):
    expected = {
        row["document_id"]: (row["title"], row["document"]) for row in documents
    }
    actual = {doc.knowledge_id: (doc.title, doc.body) for doc in snapshot.documents}
    if actual != expected or len(snapshot.documents) != len(expected):
        raise ValueError("Evaluation snapshot does not match the frozen source")


def validate_freeze(cases, raw):
    if cases["status"] != "frozen_independent_ai_reviewed":
        raise ValueError("Independent qrel review and freeze required")
    if cases["source"]["sha256"] != sha(raw):
        raise ValueError("Source differs from frozen qrels")


def span_metrics(items, case):
    spans = [s for kid, spans in items if kid == case["document_id"] for s in spans]
    present = [covers(spans, required) for required in case["required_spans"]]
    return {
        "included": sum(present),
        "required": len(present),
        "missing": [i for i, found in enumerate(present) if not found],
    }


def run_cases(service, snapshot, cases):
    chunks = {c.chunk_id: c for c, _ in service.repository.current_chunks(snapshot)}
    identities = {d.document_id: d.knowledge_id for d in snapshot.documents}
    rows = []
    for case in cases:
        start = time.perf_counter()
        context = service.retrieve(case["question"], snapshot)
        seconds = time.perf_counter() - start
        candidate_ids = context.candidate_chunk_ids
        ranked = [
            (identities[chunks[cid].document_id], chunks[cid].spans)
            for cid in candidate_ids
        ]
        final = [(e.knowledge_id, e.spans) for e in context.evidence]
        final_spans = [
            s for kid, spans in final if kid == case["document_id"] for s in spans
        ]
        found = [covers(final_spans, required) for required in case["required_spans"]]
        rows.append(
            {
                "span_coverage": {
                    "top5": span_metrics(ranked[:5], case),
                    "candidate10": span_metrics(ranked, case),
                    "final": span_metrics(final, case),
                },
                "required_span_count": len(found),
                "included_span_count": sum(found),
                "missing_spans": [i for i, hit in enumerate(found) if not hit],
                "legacy_top5_hit": (
                    any(
                        identities[chunks[cid].document_id] == case["document_id"]
                        and case["legacy_evidence"] in chunks[cid].text
                        for cid in candidate_ids[:5]
                    )
                    if "legacy_evidence" in case
                    else None
                ),
                "legacy_final_hit": (
                    any(
                        e.knowledge_id == case["document_id"]
                        and case["legacy_evidence"] in e.text
                        for e in context.evidence
                    )
                    if "legacy_evidence" in case
                    else None
                ),
                "case_id": case["case_id"],
                "document_id": case["document_id"],
                "top5_complete": complete(ranked[:5], case),
                "candidate10_complete": complete(ranked, case),
                "final_complete": complete(final, case),
                "body_characters": sum(len(e.text) for e in context.evidence),
                "seconds": seconds,
                "candidate_chunk_ids": list(candidate_ids),
                "evidence": [
                    {
                        "knowledge_id": e.knowledge_id,
                        "spans": [asdict(s) for s in e.spans],
                        "chunk_ids": list(e.chunk_ids),
                        "expanded_chunk_ids": list(e.expanded_chunk_ids),
                        "score": e.score,
                    }
                    for e in context.evidence
                ],
            }
        )
    return rows


def summary(rows):
    return {
        "count": len(rows),
        **{
            key: sum(r[key] for r in rows)
            for key in ("top5_complete", "candidate10_complete", "final_complete")
        },
        "span_coverage": {
            name: {
                "included": sum(r["span_coverage"][name]["included"] for r in rows),
                "required": sum(r["span_coverage"][name]["required"] for r in rows),
            }
            for name in ("top5", "candidate10", "final")
        },
        "mean_body_characters": float(np.mean([r["body_characters"] for r in rows])),
        "seconds_p50": float(np.percentile([r["seconds"] for r in rows], 50)),
        "seconds_p95": float(np.percentile([r["seconds"] for r in rows], 95)),
    }


def improves(previous, candidate, development_ids):
    previous_success = {r["case_id"] for r in previous if r["final_complete"]}
    candidate_success = {r["case_id"] for r in candidate if r["final_complete"]}
    return previous_success <= candidate_success and len(
        candidate_success & development_ids
    ) > len(previous_success & development_ids)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("development", "holdout"), required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--source", type=Path, default=ROOT / "data/company-knowledge/documents.jsonl"
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--cpu-cores", type=int, default=2)
    args = parser.parse_args(argv)
    if args.cpu_cores < 1:
        parser.error("--cpu-cores must be positive")
    out = args.artifact_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / f"{args.phase}.json"
    if result_path.exists() or (out / f"{args.phase}.started.json").exists():
        parser.error(
            "Phase already started; preserve its artifacts and use a new root for development only"
        )
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[: args.cpu_cores])
    cases = json.loads(args.cases.read_text())
    raw, source_rows = read_source(args.source)
    documents = [record[3] for record in source_rows]
    validate_freeze(cases, raw)
    by_id = {d["document_id"]: d["document"] for d in documents}
    for section in ("regression_original_18", "development_20", "holdout_20"):
        for case in cases[section]:
            for required in case["required_spans"]:
                assert (
                    by_id[case["document_id"]][required["start"] : required["end"]]
                    == required["text"]
                )
    manifest = {
        "code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "search_defaults": SearchConfig().to_dict(),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "specs": {
            "baseline": DEFAULT_SPEC.to_dict(),
            "contextual": CONTEXTUAL_SPEC.to_dict(),
        },
        "cases_sha256": digest(args.cases),
        "source_sha256": sha(raw),
        "python": platform.python_version(),
        "cpu_description": next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "unknown",
        )
        if Path("/proc/cpuinfo").exists()
        else platform.processor(),
        "system_memory_kib": next(
            (
                int(line.split()[1])
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemTotal:")
            ),
            None,
        )
        if Path("/proc/meminfo").exists()
        else None,
        "affinity": sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        "actual_llm_calls": 0,
        "implementation_sha256": hashlib.sha256(
            b"".join(
                p.read_bytes() for p in sorted((ROOT / "app/retrieval").glob("*.py"))
            )
            + Path(__file__).read_bytes()
        ).hexdigest(),
    }
    if args.phase == "holdout":
        dev = json.loads((out / "development.json").read_text())
        assert dev["manifest"]["cases_sha256"] == manifest["cases_sha256"]
        assert dev["manifest"]["source_sha256"] == manifest["source_sha256"]
        assert (
            dev["manifest"]["implementation_sha256"]
            == manifest["implementation_sha256"]
        )
    with (out / f"{args.phase}.started.json").open("x") as marker:
        marker.write(json.dumps(manifest, indent=2) + "\n")
    repo = DocumentRepository(out / "documents.sqlite3")
    if not repo.path.exists():
        repo.initialize()
        with repo.transaction() as connection:
            _apply_rows(repo, connection, source_rows, sha(raw), True)
    snapshot = DocumentContextProvider(repository=repo).snapshot()
    validate_snapshot(snapshot, documents)
    manifest["snapshot_fingerprint"] = snapshot.fingerprint
    embedder = TinyEmbedder(args.model)
    embedder.warmup()
    services = {}

    def service(config):
        key = json.dumps(config, sort_keys=True)
        if key not in services:
            spec = CONTEXTUAL_SPEC if config["contextual"] else DEFAULT_SPEC
            bundle = prepare_baseline(args.source, out / "bundles", embedder, spec=spec)
            metadata = validate_baseline(bundle, args.source, spec=spec)
            manifest.setdefault("prepared_bundles", {})[metadata["spec_id"]] = metadata
            index = IndexRepository(out / "indexes", spec=spec)
            value = RetrievalService(
                index,
                embedder,
                baseline_path=bundle,
                spec=spec,
                search_config=SearchConfig(
                    expand_adjacent=config["expand_adjacent"],
                    hybrid_search=config["hybrid_search"],
                ),
            )
            value.reconcile(snapshot)
            services[key] = value
        return services[key]

    baseline = {"contextual": False, "expand_adjacent": False, "hybrid_search": False}
    if args.phase == "development":
        selected = dict(baseline)
        evaluation_cases = cases["regression_original_18"] + cases["development_20"]
        previous = run_cases(service(selected), snapshot, evaluation_cases)
        results = [
            {
                "stage": "baseline",
                "config": dict(selected),
                "adopted": True,
                "summary": summary(previous),
                "rows": previous,
            }
        ]
        for stage, flag in (
            ("heading_context", "contextual"),
            ("adjacent_evidence", "expand_adjacent"),
            ("hybrid_bm25", "hybrid_search"),
        ):
            candidate = {**selected, flag: True}
            rows = run_cases(service(candidate), snapshot, evaluation_cases)
            adopted = improves(
                previous, rows, {c["case_id"] for c in cases["development_20"]}
            )
            results.append(
                {
                    "stage": stage,
                    "config": candidate,
                    "adopted": adopted,
                    "summary": summary(rows),
                    "rows": rows,
                }
            )
            if adopted:
                selected, previous = candidate, rows
        result = {"manifest": manifest, "stages": results, "selected_config": selected}
    else:
        candidate = dev["selected_config"]
        baseline_rows = run_cases(service(baseline), snapshot, cases["holdout_20"])
        candidate_rows = (
            baseline_rows
            if candidate == baseline
            else run_cases(service(candidate), snapshot, cases["holdout_20"])
        )
        accepted = sum(r["final_complete"] for r in candidate_rows) >= sum(
            r["final_complete"] for r in baseline_rows
        )
        result = {
            "manifest": manifest,
            "candidate_config": candidate,
            "accepted": accepted,
            "adopted_config": candidate if accepted else baseline,
            "unanswerable": [],
            "baseline": {"summary": summary(baseline_rows), "rows": baseline_rows},
            "candidate": {"summary": summary(candidate_rows), "rows": candidate_rows},
        }
    if args.phase == "holdout":
        final_service = service(result["adopted_config"])
        for case in cases["unanswerable"]:
            context = final_service.retrieve(case["question"], snapshot)
            result["unanswerable"].append(
                {
                    "case_id": case["case_id"],
                    "selected_documents": [e.knowledge_id for e in context.evidence],
                    "selected_count": context.selected_count,
                    "note": "Search only; no refusal or safety score without generation and review.",
                }
            )
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "result": str(result_path),
                "selected_config": result.get(
                    "selected_config", result.get("adopted_config")
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
