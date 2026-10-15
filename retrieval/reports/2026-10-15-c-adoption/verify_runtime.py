"""Compare the live C path to preserved C evidence without calling a paid LLM."""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np

from app.documents.context import DocumentContextProvider
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from app.retrieval.service import RetrievalService


def verify(source_root, model, expected, qrels, output):
    if output.exists():
        raise ValueError("Preserve previous verification output")
    original = json.loads(gzip.decompress(expected.read_bytes()))
    expected_rows = {
        r["case_id"]: r for r in original["rows"] if r["variant_id"] == "C_unlimited"
    }
    cases = json.loads(qrels.read_text())["cases"]
    manifest = json.loads((source_root / "manifest.json").read_text())
    spec = manifest["source"]["retrieval_spec_id"]
    source_db = source_root / "source/documents.sqlite3"
    index = source_root / "retrieval/schema-v1" / spec / "index.sqlite3"
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in [source_db, index]}
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    encoder = TinyEmbedder(model)
    encoder.warmup()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copyfile(source_db, root / "documents.sqlite3")
        snapshot = DocumentContextProvider(
            database_path=root / "documents.sqlite3"
        ).snapshot()
        assert snapshot.fingerprint == original["snapshot_fingerprint"]
        target = root / "retrieval/schema-v1" / spec / "index.sqlite3"
        target.parent.mkdir(parents=True)
        shutil.copyfile(index, target)
        service = RetrievalService(IndexRepository(root / "retrieval"), encoder)
        for case in cases:
            result = service.retrieve(case["question"], snapshot)
            actual = json.loads(json.dumps([asdict(e) for e in result.evidence]))
            expected_evidence = expected_rows[case["case_id"]]["evidence"]
            assert len(actual) == len(expected_evidence), case["case_id"]
            for a, e in zip(actual, expected_evidence, strict=True):
                a_score, e_score = a.pop("score"), e["score"]
                assert np.isclose(a_score, e_score, atol=1e-6, rtol=0), case["case_id"]
                assert a == {k: v for k, v in e.items() if k != "score"}, case[
                    "case_id"
                ]
            rows.append(
                {
                    "case_id": case["case_id"],
                    "evidence_count": len(actual),
                    "candidate_count": result.candidate_count,
                    "equivalent": True,
                }
            )
    assert all(
        hashlib.sha256(p.read_bytes()).hexdigest() == v for p, v in hashes.items()
    )
    payload = {
        "cases": len(rows),
        "equivalent": len(rows),
        "real_tiny_queries": len(rows),
        "paid_llm_calls": 0,
        "source_files_unchanged": True,
        "snapshot_fingerprint": original["snapshot_fingerprint"],
        "spec_id": spec,
        "search_config_id": result.search_config_id,
        "score_tolerance": 1e-6,
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in payload.items() if k != "rows"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.source_root, args.model, args.expected, args.qrels, args.output)
