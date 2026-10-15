"""Summarize observed runs without additional model inference."""

import csv
import json
from pathlib import Path

base = Path(__file__).resolve().parent
paths = [
    base.parent / "e5-small-ko-v2-pilot-2026-10-15",
    base.parent / "embedding-comparison-2026-10-15/BAAI--bge-m3",
    base.parent / "embedding-comparison-2026-10-15/nlpai-lab--KURE-v1",
] + [p.parent for p in sorted(base.glob("*/results.json"))]
rows = []
details = []
for p in paths:
    r = json.loads((p / "results.json").read_text())
    pred = json.loads((p / "predictions.json").read_text())
    row = {
        "model": r["model"],
        "source": "previous" if p.parent != base else "new",
        "doc_at1": sum(x.get("document_rank", 999) <= 1 for x in pred),
        "doc_at5": sum(x.get("document_rank", 999) <= 5 for x in pred),
        "evidence_at1": sum(x.get("evidence_rank", 999) <= 1 for x in pred),
        "evidence_at5": sum(x.get("evidence_rank", 999) <= 5 for x in pred),
        "evidence_at10": sum(x.get("evidence_rank", 999) <= 10 for x in pred),
        "evidence_mrr": r["metrics"]["evidence_mrr"],
        "p50_ms": r["query_ms"]["p50"],
        "p95_ms": r["query_ms"]["p95"],
        "index_seconds": r["indexing_seconds"],
        "peak_rss_mib": r["peak_process_rss_mib"],
        "truncated_chunks": r.get("truncated_chunks", 0),
        "revision": r["revision"],
    }
    rows.append(row)
    for q in pred:
        details.append(
            {
                "model": r["model"],
                "question": q["question"],
                "answerable": q["answerable"],
                "document_rank": q.get("document_rank"),
                "evidence_rank": q.get("evidence_rank"),
                "top_score": q["hits"][0]["score"],
                "top_document": q["hits"][0]["document_id"],
            }
        )
for name, items in [("comparison.csv", rows), ("per-question.csv", details)]:
    with (base / name).open("w") as f:
        w = csv.DictWriter(f, fieldnames=items[0].keys())
        w.writeheader()
        w.writerows(items)
lines = [
    "# 로컬 CPU 임베딩 후보 확장 실험 결과",
    "",
    "상세 조건·입력 계약·범위는 [README](README.md), 후보 판단은 [해석](interpretation.md). 질문 18개와 답 없는 질문 4개, 동일한 원문 청크 186개. 아래 수치는 답변 정확도가 아닌 지정 근거 검색의 개발 실험이다.",
    "",
    f"측정 완료: 신규 {sum(r['source'] == 'new' for r in rows)}종 + 기존 3종 = {len(rows)}종. 질문 시간은 토큰화·임베딩의 p50/p95이며 HTTP·분류기·LLM 전체 시간이 아니다.",
    "",
    "| 모델 | 문서 @5 | 근거 @1 / @5 / @10 | p50 / p95 ms | 색인 초 | 최대 RSS MiB | 잘린 입력 |",
    "|---|---:|---|---|---:|---:|---:|",
]
for r in rows:
    lines.append(
        f"| {r['model']} | {r['doc_at5']}/18 | {r['evidence_at1']}/18 / {r['evidence_at5']}/18 / {r['evidence_at10']}/18 | {r['p50_ms']:.2f} / {r['p95_ms']:.2f} | {r['index_seconds']:.2f} | {r['peak_rss_mib']:.1f} | {r['truncated_chunks']} |"
    )
lines += [
    "",
    "## 미실행·실패",
    "",
    "- google/embeddinggemma-300m: 공개 접근에서 GatedRepoError. 사용자 동의·인증 변경 또는 우회 없음.",
]
for status in json.loads((base / "batch-status.json").read_text()):
    if status["status"] != "completed":
        lines.append("- " + str(status))
lines += [
    "",
    "## 해석 시 주의",
    "",
    "- 이전 3개 모델은 앞 실험의 결과를 보존해 합쳤다. 신규 모델도 실행 시점·다운로드·다른 프로세스 경합을 통제한 반복 벤치마크가 아니다.",
    "- CPU 2개 제한은 배포 2vCPU의 처리량이나 동시 요청 성능 보증이 아니다. 최대 RSS는 다운로드·로딩·배치 색인까지 포함하며 모델 자체 메모리와 다르다.",
    "- PyTorch FP32 기본 경로이다. Bekko 공개 OpenVINO 수치와 직접 비교하지 않는다. Potion은 Model2Vec CPU 경로다.",
    "- MiniLM은 기본 128토큰으로 입력을 자른 조건이다. 그 모델에 맞춘 짧은 청크를 따로 검증한 결과가 아니다.",
    "- PR 질문에는 지정 문자열과 다른 동등한 근거가 있다. 문자열 순위의 개선을 실제 답변 가능 여부의 개선으로 그대로 해석하지 않는다.",
    "- 부정 질문에도 최근접 문서는 반환된다. 서로 다른 모델의 점수 척도를 섞거나 공통 거절 임계값으로 사용하지 않는다.",
    "- 이 작은 질문 집합에서 18/18이어도 실서비스 100% 정확도나 최종 선정 완료가 아니다. 별도 질문·배포 환경·최신 문서 반영·실제 답변 검증이 남는다.",
    "",
    "질문별 전체 비교는 [per-question.csv](per-question.csv), 각 모델의 결과 JSON·예측·벡터는 모델명 폴더에 보존했다.",
]
(base / "report.md").write_text("\n".join(lines) + "\n")
print("Completed model measurements:", len(rows))
for r in rows:
    print(r["model"], r["evidence_at1"], r["evidence_at5"], round(r["p50_ms"], 2))
