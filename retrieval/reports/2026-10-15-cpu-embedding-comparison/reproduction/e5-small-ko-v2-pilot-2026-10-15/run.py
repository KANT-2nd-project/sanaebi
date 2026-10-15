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
OUT = Path(__file__).resolve().parent
# Labels and evidence fixed before inference; AI-authored, not independent test data.
CASES = [
    ("휴가를 미리 쓰려고 하는데 어디서 며칠 전에 올려야 해?", "001", "3영업일 전까지"),
    ("연차 취소 버튼이 잠겨 있어. 새로 신청하면 될까?", "001", "새 신청을 중복으로"),
    ("어제 퇴근 체크를 빼먹었어. 기록을 어떻게 고치지?", "006", "인사 > 근태 정정"),
    ("근태 오류를 발견한 지 일주일 지났는데 수정 못 해?", "006", "3영업일이 지난 오류"),
    ("집에서 일하려면 언제까지 신청해야 돼?", "010", "전 영업일 15:00"),
    (
        "외국에 머물면서 재택으로 일해도 일반 재택 신청이면 돼?",
        "010",
        "예정일 10영업일 전까지",
    ),
    ("회사 들어가는 카드를 잃어버렸고 포털도 안 돼.", "013", "#office-help"),
    ("개인 돈으로 업무 비용을 냈는데 언제 입금돼?", "019", "다음 달 15일"),
    ("영수증 제출 기한이 이미 지났으면 어떻게 해?", "019", "팀장과 재무팀의 예외 승인"),
    (
        "인증용 휴대폰을 잃어버렸어. 동료 계정으로 들어가도 돼?",
        "026",
        "타인의 기기나 계정으로 우회 로그인하지",
    ),
    (
        "내가 로그인 안 했는데 인증 승인 알림이 자꾸 와.",
        "026",
        "본인이 시작하지 않은 인증 알림을 승인하지",
    ),
    (
        "회사 ChatGPT 계정이면 고객 이름을 지우고 문의 내용을 넣어도 돼?",
        "033",
        "식별자를 지워도",
    ),
    (
        "AI에 회사 정보를 잘못 넣었어. 대화를 지워야 하나?",
        "033",
        "임의로 삭제해 증거를 없애지",
    ),
    ("내 PR은 내가 승인해서 머지해도 돼?", "067", "작성자와 다른 사람이 최소 1명"),
    (
        "배포하다 장애가 났는데 같은 명령부터 다시 돌리면 돼?",
        "068",
        "추가 배포와 반복 실행을 멈춘다",
    ),
    ("Git에 토큰을 올렸어. 파일에서 지우면 끝이야?", "071", "즉시 폐기·회전"),
    ("연차신청 어디서함", "001", "인사 > 휴가"),
    ("제출한 경비의 지급일인 15일이 은행 쉬는 날이면?", "019", "다음 은행 영업일"),
]
NEGATIVE = [
    "이번 주 구내식당 점심 메뉴가 뭐야?",
    "우리 회사 올해 성과급 지급률은 몇 퍼센트야?",
    "대표님의 개인 휴대전화 번호 알려줘.",
    "내 개인 잔여 연차가 정확히 며칠이야?",
]
cases = [
    {"question": q, "document_id": "ieum-" + d, "evidence": e} for q, d, e in CASES
]
(OUT / "cases.json").write_text(
    json.dumps(
        {
            "answerable": cases,
            "unanswerable": NEGATIVE,
            "provenance": "AI-authored after reading corpus; fixed before inference; not human reviewed",
        },
        ensure_ascii=False,
        indent=2,
    )
)
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
from huggingface_hub import HfApi
from transformers import AutoModel, AutoTokenizer

torch.set_num_threads(2)
torch.set_num_interop_threads(1)
name = "dragonkue/multilingual-e5-small-ko-v2"
revision = HfApi(token=False).model_info(name).sha
print("Loading pinned model", revision, flush=True)
t0 = time.perf_counter()
tok = AutoTokenizer.from_pretrained(name, revision=revision, token=False)
model = AutoModel.from_pretrained(name, revision=revision, token=False).to("cpu").eval()
load_seconds = time.perf_counter() - t0


def encode(texts, batch_size=8):
    result = []
    for start in range(0, len(texts), batch_size):
        batch = tok(
            texts[start : start + batch_size],
            padding=True,
            truncation=False,
            return_tensors="pt",
        )
        assert batch["input_ids"].shape[1] <= 512
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1)
            pooled = (hidden * mask).sum(1) / mask.sum(1)
            result.append(torch.nn.functional.normalize(pooled, p=2, dim=1))
    return torch.cat(result).numpy()


chunks = []
full_lengths = []
for d in docs:
    full_lengths.append(
        len(tok("passage: " + d["title"] + "\n" + d["document"])["input_ids"])
    )
    offsets = tok(d["document"], add_special_tokens=False, return_offsets_mapping=True)[
        "offset_mapping"
    ]
    for start in range(0, len(offsets), 300):
        end = min(start + 360, len(offsets))
        lo = offsets[start][0]
        hi = offsets[end - 1][1]
        body = d["document"][lo:hi]
        text = "passage: " + d["title"] + "\n" + body
        length = len(tok(text)["input_ids"])
        assert length <= 512
        chunks.append(
            {
                "document_id": d["document_id"],
                "title": d["title"],
                "start": lo,
                "end": hi,
                "body": body,
                "text": text,
                "tokens": length,
            }
        )
        if end == len(offsets):
            break
(OUT / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2))
encode(["query: 워밍업입니다."])
t0 = time.perf_counter()
matrix = encode([c["text"] for c in chunks])
indexing = time.perf_counter() - t0
np.save(OUT / "vectors.npy", matrix)
print("Indexed", len(chunks), "chunks in", round(indexing, 3), "seconds", flush=True)
questions = [c["question"] for c in cases] + NEGATIVE
qmat = encode(["query: " + q for q in questions])
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
        vec = encode(["query: " + q])
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
    for k in [1, 3, 5]:
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
    "full_documents_over_512": sum(n > 512 for n in full_lengths),
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
