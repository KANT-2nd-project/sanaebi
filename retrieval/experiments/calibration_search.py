"""Offline, claim-based retrieval calibration using immutable prepared vectors."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.documents.context import DocumentContextProvider
from app.retrieval import service as runtime
from app.retrieval.chunking import token_count
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from generation.documents import render_document
from retrieval.experiments.calibration_metrics import claim_metrics

ROOT = Path(__file__).resolve().parents[2]


def evidence_items(evidence):
    return [(e.knowledge_id, [(s.start, s.end) for s in e.spans]) for e in evidence]


def proxy_tokens(tokenizer, evidence):
    return token_count(
        tokenizer,
        "\n\n".join(
            "[현재 게시 문서의 발췌 근거]\n"
            + render_document(e.knowledge_id, e.title, e.text, e.revision)
            for e in evidence
        ),
        special_tokens=False,
    )


def select_evidence(
    hits,
    snapshot,
    maximum,
    tokenizer,
    token_budget=None,
    *,
    total_chars=8000,
    per_evidence_chars=2000,
):
    per_limit = float("inf") if per_evidence_chars is None else per_evidence_chars
    with patch.object(runtime, "MAX_EVIDENCE_CHARS", per_limit):
        groups = runtime._merge_hits(hits, snapshot)

    def at_budget(budget):
        with (
            patch.object(runtime, "MAX_EVIDENCE_CHARS", per_limit),
            patch.object(runtime, "MAX_EVIDENCE_COUNT", maximum),
            patch.object(runtime, "MAX_TOTAL_EVIDENCE_CHARS", budget),
        ):
            return runtime._apply_budgets(groups, snapshot)

    selected = at_budget(float("inf") if total_chars is None else total_chars)
    if token_budget is None or proxy_tokens(tokenizer, selected) <= token_budget:
        return selected
    # Find a conservative character budget, checking the actual proxy encoding.
    low, high = (
        0,
        (sum(len(e.text) for e in selected) if total_chars is None else total_chars),
    )
    best = []
    while low <= high:
        middle = (low + high) // 2
        candidate = at_budget(middle)
        if proxy_tokens(tokenizer, candidate) <= token_budget:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    assert proxy_tokens(tokenizer, best) <= token_budget
    return best


def evaluate(args):
    output = args.output
    if output.exists():
        raise ValueError(
            "Preserve existing output; use a new explicit output directory"
        )
    qrels = json.loads(args.qrels.read_text())
    if qrels["status"] not in ("frozen_independent_ai_reviewed", "ai_draft"):
        raise ValueError("Unexpected qrel state")
    manifest = json.loads((args.artifact_root / "manifest.json").read_text())
    snapshot = DocumentContextProvider(
        database_path=args.artifact_root / "source/documents.sqlite3"
    ).snapshot()
    assert snapshot.fingerprint == manifest["source"]["snapshot_fingerprint"]
    documents = {d.knowledge_id: d for d in snapshot.documents}
    for case in qrels["cases"]:
        for claim in case.get("required_claims", []):
            assert claim["evidence_alternatives"]
            for alternative in claim["evidence_alternatives"]:
                body = documents[alternative["document_id"]].body
                for span in alternative["spans"]:
                    assert body[span["start"] : span["end"]] == span["text"]
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    embedder = TinyEmbedder(args.model)
    embedder.warmup()
    original = (
        args.artifact_root
        / "retrieval/schema-v1"
        / manifest["source"]["retrieval_spec_id"]
        / "index.sqlite3"
    )
    wal = Path(str(original) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    configs = [
        (
            name if budget is None else f"{name}_proxy{budget}",
            pool,
            maximum,
            threshold,
            budget,
            8000,
            2000,
        )
        for name, pool, maximum, threshold in [
            ("baseline", 10, 5, None),
            ("score040_max8", None, 8, 0.4),
            ("score035_unlimited", None, float("inf"), 0.35),
        ]
        for budget in (None, 1000, 2000, 4000)
    ]
    if getattr(args, "context_limits", False):
        configs = [
            ("A_existing", None, float("inf"), 0.35, 4000, 8000, 2000),
            ("B_tokens_only", None, float("inf"), 0.35, 4000, None, None),
            ("C_unlimited", None, float("inf"), 0.35, None, None, None),
        ]
    rows, ranking_rows, packets = [], [], []
    queries = {}
    cached = {}
    cache_sha = None
    if args.query_cache:
        cache_sha = hashlib.sha256(args.query_cache.read_bytes()).hexdigest()
        meta = json.loads(args.query_cache.with_suffix(".json").read_text())
        if meta != {
            "model_revision": "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
            "dimension": 384,
            "normalization": "l2",
            "sha256": cache_sha,
        }:
            raise ValueError("Query cache provenance mismatch")
        cached = np.load(args.query_cache, allow_pickle=False)
        if any(
            v.shape != (384,)
            or not np.isfinite(v).all()
            or not np.isclose(np.linalg.norm(v), 1, atol=1e-4)
            for v in cached.values()
        ):
            raise ValueError("Query cache vector contract mismatch")
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / original.relative_to(args.artifact_root / "retrieval")
        target.parent.mkdir(parents=True)
        shutil.copyfile(original, target)
        repository = IndexRepository(temp)
        actual = runtime.RetrievalService(repository, embedder)
        assert actual.status(snapshot)["ready"]
        current = repository.current_chunks(snapshot)
        matrix = np.stack([v for _, v in current])
        identities = {d.document_id: d.knowledge_id for d in snapshot.documents}
        for case in qrels["cases"]:
            started = time.perf_counter()
            query_key = hashlib.sha256(case["question"].encode()).hexdigest()
            query = (
                cached[query_key]
                if query_key in cached
                else embedder.encode_queries([case["question"]])[0]
            )
            queries[query_key] = query
            scores = matrix @ query
            order = sorted(
                range(len(current)),
                key=lambda i: (-float(scores[i]), current[i][0].chunk_id),
            )
            query_ms = (time.perf_counter() - started) * 1000
            all_ranked = [
                (
                    identities[current[i][0].document_id],
                    [(s.start, s.end) for s in current[i][0].spans],
                )
                for i in order
            ]
            first_complete = next(
                (
                    i
                    for i in range(1, len(order) + 1)
                    if claim_metrics(all_ranked[:i], case)["complete"]
                ),
                None,
            )
            ranking_rows.append(
                {
                    "case_id": case["case_id"],
                    "query_ms": query_ms,
                    "all_claim_rank": first_complete,
                    "cutoffs": {
                        str(k): claim_metrics(all_ranked[:k], case)
                        for k in (5, 10, 20, 40, len(order))
                    },
                    "ranking": [
                        {
                            "chunk_id": current[i][0].chunk_id,
                            "score": float(scores[i]),
                            "document_id": identities[current[i][0].document_id],
                            "spans": [asdict(v) for v in current[i][0].spans],
                        }
                        for i in order
                    ],
                }
            )
            selected_pool = set()
            for (
                variant_id,
                pool,
                maximum,
                threshold,
                budget,
                total_chars,
                per_chars,
            ) in configs:
                chosen = order[:pool] if pool is not None else order
                hits = [
                    (current[i][0], float(scores[i]))
                    for i in chosen
                    if threshold is None or float(scores[i]) >= threshold
                ]
                candidate_claims = claim_metrics(
                    [
                        (identities[c.document_id], [(v.start, v.end) for v in c.spans])
                        for c, score in hits
                    ],
                    case,
                )
                if args.variants and variant_id not in args.variants:
                    continue
                selection_start = time.perf_counter()
                selected = select_evidence(
                    hits,
                    snapshot,
                    maximum,
                    embedder.tokenizer,
                    budget,
                    total_chars=total_chars,
                    per_evidence_chars=per_chars,
                )
                selection_ms = (time.perf_counter() - selection_start) * 1000
                if variant_id == "baseline":
                    reference = actual.retrieve(case["question"], snapshot).evidence
                    assert [(e.chunk_ids, e.text) for e in selected] == [
                        (e.chunk_ids, e.text) for e in reference
                    ]
                selected_pool.update(cid for e in selected for cid in e.chunk_ids)
                row = {
                    "case_id": case["case_id"],
                    "variant_id": variant_id,
                    "total_chars_limit": total_chars,
                    "per_evidence_chars_limit": per_chars,
                    "proxy_budget": budget,
                    "answerability": case["answerability"],
                    **claim_metrics(evidence_items(selected), case),
                    "characters": sum(len(e.text) for e in selected),
                    "proxy_tokens": proxy_tokens(embedder.tokenizer, selected),
                    "evidence_count": len(selected),
                    "candidate_count": len(hits),
                    "candidate_claims": candidate_claims,
                    "selection_ms": selection_ms,
                    "evidence": [asdict(e) for e in selected],
                }
                rows.append(row)
            # Blind ordering and omit scores/configurations; IDs remain join keys.
            packets.append(
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "answerability": case["answerability"],
                    "required_claims": case.get("required_claims", []),
                    "passages": [
                        {
                            "chunk_id": c.chunk_id,
                            "document_id": identities[c.document_id],
                            "title": documents[identities[c.document_id]].title,
                            "text": c.text,
                        }
                        for c, _ in sorted(current, key=lambda v: v[0].chunk_id)
                        if c.chunk_id in selected_pool
                        or c.chunk_id in {current[i][0].chunk_id for i in order[:40]}
                    ],
                }
            )
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    output.mkdir(parents=True)
    np.savez(output / "query-vectors.npz", **queries)
    (output / "query-vectors.json").write_text(
        json.dumps(
            {
                "model_revision": "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
                "dimension": 384,
                "normalization": "l2",
                "sha256": hashlib.sha256(
                    (output / "query-vectors.npz").read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    payload = {
        "snapshot_fingerprint": snapshot.fingerprint,
        "qrels_sha": hashlib.sha256(args.qrels.read_bytes()).hexdigest(),
        "model_revision": "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
        "query_vectors_reused": bool(args.query_cache),
        "query_cache_sha": cache_sha,
        "source_index_sha": before,
        "retrieval_spec": manifest["source"]["retrieval_spec_id"],
        "code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "token_measure": "Tiny proxy, not Luna provider tokens",
        "rows": rows,
        "ranking": ranking_rows,
    }
    (output / "search.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "relevance-packet.json").write_text(
        json.dumps(packets, ensure_ascii=False, indent=2) + "\n"
    )
    summary = []
    for variant in dict.fromkeys(row["variant_id"] for row in rows):
        selected = [r for r in rows if r["variant_id"] == variant]
        scored = [r for r in selected if r["required"]]
        summary.append(
            {
                "variant_id": variant,
                "claim_cases": len(scored),
                "complete": sum(bool(r["complete"]) for r in scored),
                "included": sum(r["included"] for r in scored),
                "required": sum(r["required"] for r in scored),
                "empty_answerable": sum(
                    r["evidence_count"] == 0
                    for r in selected
                    if r["answerability"] == "answerable"
                ),
                "mean_chars": round(
                    float(np.mean([r["characters"] for r in selected]))
                ),
                "mean_proxy_tokens": round(
                    float(np.mean([r["proxy_tokens"] for r in selected]))
                ),
            }
        )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query-cache", type=Path)
    parser.add_argument("--variants", nargs="+")
    parser.add_argument("--context-limits", action="store_true")
    evaluate(parser.parse_args())
