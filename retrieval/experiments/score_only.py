"""Offline evidence-limit/threshold sweep; never changes server defaults."""

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.documents.context import DocumentContextProvider
from app.documents.transfer import read_source
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from retrieval.experiments import legacy_service as runtime
from retrieval.experiments.quality import (
    complete,
    validate_freeze,
    validate_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve previous evidence")
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    cases_path = (
        ROOT / "retrieval/reports/2026-10-15-rag-quality-improvement/cases.json"
    )
    cases = json.loads(cases_path.read_text())
    raw, records = read_source(ROOT / "data/company-knowledge/documents.jsonl")
    validate_freeze(cases, raw)
    manifest = json.loads((args.artifact_root / "manifest.json").read_text())
    source_db = args.artifact_root / "source/documents.sqlite3"
    snapshot = DocumentContextProvider(database_path=source_db).snapshot()
    validate_snapshot(snapshot, [r[3] for r in records])
    assert snapshot.fingerprint == manifest["source"]["snapshot_fingerprint"]
    corpus = {d.knowledge_id: d.body for d in snapshot.documents}
    positives = cases["regression_original_18"] + cases["development_20"]
    negatives = cases["unanswerable"]
    for case in positives:
        for span in case["required_spans"]:
            assert (
                corpus[case["document_id"]][span["start"] : span["end"]] == span["text"]
            )
    all_cases = positives + negatives
    variants = [("top10_max5", 10, 5, None, 8000, 2000)]
    variants += [
        (f"score{t:g}_{mode}", None, float("inf"), t, total, per_item)
        for t in (0.25, 0.3, 0.35, 0.375, 0.4, 0.425, 0.45, 0.475, 0.5, 0.55, 0.6)
        for mode, total, per_item in (
            ("budget8000", 8000, 2000),
            ("only", float("inf"), float("inf")),
        )
    ]
    embedder = TinyEmbedder(args.model)
    embedder.warmup()
    original_index = (
        args.artifact_root
        / "retrieval/schema-v1"
        / manifest["source"]["retrieval_spec_id"]
        / "index.sqlite3"
    )
    wal = Path(str(original_index) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    hashes_before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (source_db, original_index)
    }
    rows, score_rows = [], []
    with tempfile.TemporaryDirectory() as temporary:
        index = Path(temporary) / original_index.relative_to(
            args.artifact_root / "retrieval"
        )
        index.parent.mkdir(parents=True)
        shutil.copyfile(original_index, index)
        repository = IndexRepository(temporary)
        actual = runtime.LegacyRetrievalService(repository, embedder)
        assert actual.status(snapshot)["ready"]
        current = repository.current_chunks(snapshot)
        matrix = np.stack([v for _, v in current])
        for case in all_cases:
            started = time.perf_counter()
            query = embedder.encode_queries([case["question"]])[0]
            scores = matrix @ query
            ranking = sorted(
                range(len(current)),
                key=lambda i: (-float(scores[i]), current[i][0].chunk_id),
            )
            query_ms = (time.perf_counter() - started) * 1000
            positive = "required_spans" in case
            score_rows.append(
                {
                    "case_id": case["case_id"],
                    "answerable": positive,
                    "max_score": float(scores[ranking[0]]),
                    "query_ms": query_ms,
                }
            )
            for name, pool, maximum, threshold, total, per_item in variants:
                started = time.perf_counter()
                chosen = ranking[:pool] if pool is not None else ranking
                hits = [
                    (current[i][0], float(scores[i]))
                    for i in chosen
                    if threshold is None or float(scores[i]) >= threshold
                ]
                with (
                    patch.object(runtime, "MAX_EVIDENCE_COUNT", maximum),
                    patch.object(runtime, "MAX_TOTAL_EVIDENCE_CHARS", total),
                    patch.object(runtime, "MAX_EVIDENCE_CHARS", per_item),
                ):
                    evidence = runtime._apply_budgets(
                        runtime._merge_hits(hits, snapshot), snapshot
                    )
                assert sum(len(e.text) for e in evidence) <= total
                assert len(evidence) <= maximum
                assert all(len(e.text) <= per_item for e in evidence)
                if name.endswith("_only"):
                    selected_ids = {cid for e in evidence for cid in e.chunk_ids}
                    assert selected_ids == {chunk.chunk_id for chunk, _ in hits}
                    from retrieval.experiments.quality import covers

                    for chunk, _ in hits:
                        delivered = [
                            s
                            for e in evidence
                            if e.document_id == chunk.document_id
                            for s in e.spans
                        ]
                        assert all(
                            covers(delivered, {"start": s.start, "end": s.end})
                            for s in chunk.spans
                        )
                if threshold is not None:
                    assert all(score >= threshold for _, score in hits)
                if name == "top10_max5":
                    reference = actual.retrieve(case["question"], snapshot)
                    assert [(e.chunk_ids, e.text) for e in reference.evidence] == [
                        (e.chunk_ids, e.text) for e in evidence
                    ]
                rows.append(
                    {
                        "variant": name,
                        "case_id": case["case_id"],
                        "answerable": positive,
                        "complete": complete(
                            [(e.knowledge_id, e.spans) for e in evidence], case
                        )
                        if positive
                        else None,
                        "candidate_count": len(hits),
                        "evidence_count": len(evidence),
                        "characters": sum(len(e.text) for e in evidence),
                        "other_document_characters": sum(
                            len(e.text)
                            for e in evidence
                            if e.knowledge_id != case.get("document_id")
                        )
                        if positive
                        else None,
                        "assembly_ms": (time.perf_counter() - started) * 1000,
                        "evidence": [
                            {
                                "document_id": e.knowledge_id,
                                "score": e.score,
                                "spans": [
                                    {"start": s.start, "end": s.end} for s in e.spans
                                ],
                            }
                            for e in evidence
                        ],
                    }
                )
    assert hashes_before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (source_db, original_index)
    }
    summaries = []
    baseline_success = {
        r["case_id"] for r in rows if r["variant"] == "top10_max5" and r["complete"]
    }
    for name, pool, maximum, threshold, total, per_item in variants:
        selected = [r for r in rows if r["variant"] == name]
        positive = [r for r in selected if r["answerable"]]
        negative = [r for r in selected if not r["answerable"]]
        success = {r["case_id"] for r in positive if r["complete"]}
        summaries.append(
            {
                "variant": name,
                "pool": pool,
                "max_evidence": maximum if np.isfinite(maximum) else None,
                "total_char_budget": total if np.isfinite(total) else None,
                "per_evidence_budget": per_item if np.isfinite(per_item) else None,
                "threshold": threshold,
                "complete_38": len(success),
                "regression_18": sum(
                    r["complete"] for r in positive if r["case_id"].startswith("R")
                ),
                "development_20": sum(
                    r["complete"] for r in positive if r["case_id"].startswith("D")
                ),
                "lost": sorted(baseline_success - success),
                "gained": sorted(success - baseline_success),
                "answerable_empty": sum(r["evidence_count"] == 0 for r in positive),
                "unanswerable_empty_10": sum(
                    r["evidence_count"] == 0 for r in negative
                ),
                "mean_positive_chars": round(
                    float(np.mean([r["characters"] for r in positive]))
                ),
                "max_positive_chars": max(r["characters"] for r in positive),
                "mean_negative_chars": round(
                    float(np.mean([r["characters"] for r in negative]))
                ),
                "mean_other_document_chars": round(
                    float(np.mean([r["other_document_characters"] for r in positive]))
                ),
                "mean_evidence_count": round(
                    float(np.mean([r["evidence_count"] for r in positive])), 2
                ),
            }
        )
    args.output.mkdir(parents=True)
    output = {
        "source_sha": cases["source"]["sha256"],
        "cases_sha": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "snapshot": snapshot.fingerprint,
        "protocol": "23 variants fixed before this run; no count cap for threshold variants; budget8000 versus no character cap; regression18+development20+unanswerable10; holdout excluded; shared query embedding; no LLM",
        "summary": summaries,
        "query_scores": score_rows,
        "rows": rows,
        "preserved_source_and_index": True,
    }
    (args.output / "results.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    with (args.output / "comparison.csv").open("w") as file:
        writer = csv.DictWriter(file, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
