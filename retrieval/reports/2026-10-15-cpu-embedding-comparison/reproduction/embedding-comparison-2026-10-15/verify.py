"""Validate stored embeddings and recompute ranking metrics without inference."""

import hashlib
import json
from pathlib import Path

import numpy as np

base = Path(__file__).resolve().parent
prior = base.parent / "e5-small-ko-v2-pilot-2026-10-15"
original_chunks = json.loads((prior / "chunks.json").read_text())
original_cases = json.loads((prior / "cases.json").read_text())
verified = []
for folder in sorted(base.iterdir()):
    if not (folder / "results.json").is_file():
        continue
    result = json.loads((folder / "results.json").read_text())
    chunks = json.loads((folder / "chunks.json").read_text())
    cases = json.loads((folder / "cases.json").read_text())
    predictions = json.loads((folder / "predictions.json").read_text())
    vectors = np.load(folder / "vectors.npy")
    queries = np.load(folder / "query_vectors.npy")
    assert cases == original_cases
    assert len(chunks) == len(original_chunks) == 186
    for actual, expected in zip(chunks, original_chunks):
        for key in ["document_id", "title", "body", "start", "end"]:
            assert actual[key] == expected[key]
    assert vectors.shape == (186, 1024)
    assert queries.shape == (22, 1024)
    for array in [vectors, queries]:
        assert np.isfinite(array).all()
        assert np.allclose(np.linalg.norm(array, axis=1), 1, atol=1e-5)
    for i, prediction in enumerate(predictions):
        scores = vectors @ queries[i]
        order = np.argsort(-scores, kind="stable")
        assert [h["chunk_index"] for h in prediction["hits"]] == order[:5].tolist()
        if prediction["answerable"]:
            case = cases["answerable"][i]
            for kind in ["document", "evidence"]:
                rank = next(
                    k + 1
                    for k, j in enumerate(order)
                    if chunks[j]["document_id"] == case["document_id"]
                    and (kind == "document" or case["evidence"] in chunks[j]["body"])
                )
                assert rank == prediction[kind + "_rank"]
    for kind in ["document", "evidence"]:
        ranks = [r[kind + "_rank"] for r in predictions if r["answerable"]]
        for k in [1, 3, 5, 10]:
            assert (
                sum(x <= k for x in ranks) / len(ranks)
                == result["metrics"][kind + "_hit_at_" + str(k)]
            )
    corpus = base.parents[1] / "data/company-knowledge/documents.jsonl"
    assert hashlib.sha256(corpus.read_bytes()).hexdigest() == result["dataset_sha256"]
    verified.append(result["model"])
assert verified
(base / "verification.json").write_text(
    json.dumps(
        {
            "passed": True,
            "models": verified,
            "checks": [
                "same fixed questions and exact source spans",
                "finite unit vectors",
                "rankings and metrics recomputed from saved vectors",
                "source SHA unchanged",
            ],
        },
        indent=2,
    )
)
print("Verified:", verified)
