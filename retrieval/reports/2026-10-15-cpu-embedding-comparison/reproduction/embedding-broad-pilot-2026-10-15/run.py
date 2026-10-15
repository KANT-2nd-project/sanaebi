"""Local CPU retrieval pilot; no live DB, server or external generation calls."""

import os

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
import hashlib
import json
import platform
import resource
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

BASE = ROOT / "tmp/e5-small-ko-v2-pilot-2026-10-15"
name = sys.argv[1]
OUT = Path(__file__).resolve().parent / name.replace("/", "--")
OUT.mkdir(exist_ok=True)
fixture = json.loads((BASE / "cases.json").read_text())
cases = fixture["answerable"]
NEGATIVE = fixture["unanswerable"]
(OUT / "cases.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2))
raw = (ROOT / "data/company-knowledge/documents.jsonl").read_bytes()
docs = [json.loads(x) for x in raw.splitlines()]
byid = {d["document_id"]: d for d in docs}
for c in cases:
    assert c["evidence"] in byid[c["document_id"]]["document"], c
allowed = sorted(os.sched_getaffinity(0))
os.sched_setaffinity(0, allowed[:2])
import numpy as np
import torch
import transformers
from transformers import AutoModel, AutoTokenizer

torch.set_num_threads(2)
torch.set_num_interop_threads(1)

catalog = {
    r["model"]: r
    for r in json.loads((Path(__file__).parent / "catalog.json").read_text())
}
entry = catalog[name]
revision = entry["revision"]
pooling = entry["1_Pooling/config.json"]
if pooling.get("pooling_mode_cls_token"):
    pool_kind = "cls"
elif pooling.get("pooling_mode_lasttoken"):
    pool_kind = "last"
else:
    assert pooling.get("pooling_mode_mean_tokens")
    pool_kind = "mean"
config = entry["config.json"]
max_length = entry.get("sentence_bert_config.json", {}).get(
    "max_seq_length",
    config["max_position_embeddings"]
    - (2 if config["model_type"] == "xlm-roberta" else 0),
)
is_e5 = "e5" in name.lower() or name == "nlpai-lab/KoE5"
query_prefix = "query: " if is_e5 or name.startswith("Snowflake/") else ""
passage_prefix = "passage: " if is_e5 else ""
if name.startswith("microsoft/"):
    query_prefix = entry["config_sentence_transformers.json"]["prompts"][
        "web_search_query"
    ]
print("START", name, revision, pool_kind, max_length, flush=True)
(OUT / "contract.json").write_text(
    json.dumps(
        {
            "pooling": pool_kind,
            "max_length": max_length,
            "query_prefix": query_prefix,
            "passage_prefix": passage_prefix,
            "dtype": "float32",
            "backend": "pytorch",
        },
        indent=2,
    )
)
t0 = time.perf_counter()
tok = AutoTokenizer.from_pretrained(name, revision=revision, token=False)
model = (
    AutoModel.from_pretrained(name, revision=revision, token=False, dtype=torch.float32)
    .to("cpu")
    .eval()
)
if hasattr(model.config, "reference_compile"):
    model.config.reference_compile = False
load_seconds = time.perf_counter() - t0
assert all(p.device.type == "cpu" for p in model.parameters())


def encode(texts, batch_size=8):
    result = []
    for start in range(0, len(texts), batch_size):
        batch = tok(
            texts[start : start + batch_size],
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        assert batch["input_ids"].shape[1] <= max_length
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            if pool_kind == "cls":
                pooled = hidden[:, 0]
            elif pool_kind == "mean":
                mask = batch["attention_mask"].unsqueeze(-1)
                pooled = (hidden * mask).sum(1) / mask.sum(1)
            else:
                indices = (
                    (
                        torch.arange(hidden.shape[1]).unsqueeze(0)
                        * batch["attention_mask"]
                    )
                    .max(1)
                    .values
                )
                pooled = hidden[torch.arange(hidden.shape[0]), indices]
            result.append(torch.nn.functional.normalize(pooled, p=2, dim=1))
        if len(texts) > 30 and start % 40 == 0:
            print(
                "ENCODE", start + len(batch["input_ids"]), "/", len(texts), flush=True
            )
    return torch.cat(result).numpy()


# Keep exact original source spans; only model-specific prefixes differ.
assert (
    hashlib.sha256(raw).hexdigest()
    == json.loads((BASE / "results.json").read_text())["dataset_sha256"]
)
chunks = json.loads((BASE / "chunks.json").read_text())
full_lengths = []
for c in chunks:
    c["text"] = passage_prefix + c["title"] + "\n" + c["body"]
    c["tokens"] = len(tok(c["text"])["input_ids"])
    assert c["tokens"] <= max_length or "MiniLM" in name, (
        name,
        c["tokens"],
        max_length,
    )
(OUT / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2))
encode([query_prefix + "워밍업입니다."])
t0 = time.perf_counter()
matrix = encode([c["text"] for c in chunks])
indexing = time.perf_counter() - t0
np.save(OUT / "vectors.npy", matrix)
print("Indexed", len(chunks), "chunks in", round(indexing, 3), "seconds", flush=True)
questions = [c["question"] for c in cases] + NEGATIVE
qmat = encode([query_prefix + q for q in questions])
np.save(OUT / "query_vectors.npy", qmat)
results = []
for i, q in enumerate(questions):
    scores = matrix @ qmat[i]
    order = np.argsort(-scores, kind="stable")
    hits = [
        {
            "rank": k + 1,
            "score": float(scores[j]),
            "chunk_index": int(j),
            "document_id": chunks[j]["document_id"],
            "title": chunks[j]["title"],
            "body": chunks[j]["body"],
        }
        for k, j in enumerate(order[:5])
    ]
    r = {"question": q, "answerable": i < len(cases), "hits": hits}
    if i < len(cases):
        c = cases[i]
        r.update(expected_document_id=c["document_id"], evidence=c["evidence"])
        r["document_rank"] = next(
            k + 1
            for k, j in enumerate(order)
            if chunks[j]["document_id"] == c["document_id"]
        )
        evidence_ranks = [
            k + 1
            for k, j in enumerate(order)
            if chunks[j]["document_id"] == c["document_id"]
            and c["evidence"] in chunks[j]["body"]
        ]
        assert evidence_ranks, c
        r["evidence_rank"] = min(evidence_ranks)
    results.append(r)
(OUT / "predictions.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
latencies = []
search_latencies = []
for repeat in range(4):
    for q in questions:
        t0 = time.perf_counter()
        vec = encode([query_prefix + q])
        latencies.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        np.argsort(-(matrix @ vec[0]))[:5]
        search_latencies.append((time.perf_counter() - t0) * 1000)


def stats(values):
    return {
        k: float(v)
        for k, v in zip(["p50", "p95", "max"], np.percentile(values, [50, 95, 100]))
    }


metrics = {}
for kind in ["document", "evidence"]:
    ranks = [r[kind + "_rank"] for r in results if r["answerable"]]
    for k in [1, 3, 5, 10]:
        metrics[kind + "_hit_at_" + str(k)] = sum(r <= k for r in ranks) / len(ranks)
    metrics[kind + "_mrr"] = float(np.mean([1 / r for r in ranks]))
report = {
    "model": name,
    "revision": revision,
    "dataset_sha256": hashlib.sha256(raw).hexdigest(),
    "git_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "documents": len(docs),
    "chunks": len(chunks),
    "pooling": pool_kind + "_normalized",
    "truncated_chunks": sum(c["tokens"] > max_length for c in chunks),
    "query_prefix": query_prefix,
    "passage_prefix": passage_prefix,
    "max_length": max_length,
    "retrieval_mode": "dense_only",
    "chunk_provenance": "unchanged E5-tokenized source spans",
    "max_chunk_tokens": max(c["tokens"] for c in chunks),
    "chunk_body_tokens": 360,
    "overlap_tokens": 60,
    "dimension": matrix.shape[1],
    "device": "cpu",
    "affinity": sorted(os.sched_getaffinity(0)),
    "torch_threads": torch.get_num_threads(),
    "platform": platform.platform(),
    "torch": torch.__version__,
    "transformers": transformers.__version__,
    "load_including_download_seconds": load_seconds,
    "indexing_seconds": indexing,
    "indexing_batch_size": 8,
    "query_timing_samples": len(latencies),
    "query_ms": stats(latencies),
    "search_ms": stats(search_latencies),
    "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    "metrics": metrics,
    "limitations": [
        "AI-authored corpus-aware small questions; not independent quality evaluation",
        "CPU affinity 2 on developer workstation is not deployed 2vCPU",
        "No classifier contention, concurrency, live DB, publish/update lifecycle or LLM evaluated",
        "Document hits use one designated source; other relevant sources may exist",
    ],
}
(OUT / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
