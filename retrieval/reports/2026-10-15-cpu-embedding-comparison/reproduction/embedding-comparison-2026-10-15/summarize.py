import csv
import json
from pathlib import Path

base = Path(__file__).resolve().parent
paths = [
    base.parent / "e5-small-ko-v2-pilot-2026-10-15",
    base / "BAAI--bge-m3",
    base / "nlpai-lab--KURE-v1",
]
rows = []
all_predictions = []
for path in paths:
    r = json.loads((path / "results.json").read_text())
    p = json.loads((path / "predictions.json").read_text())
    all_predictions.append(p)
    row = {
        "model": r["model"],
        "doc_hit1": sum(x.get("document_rank", 999) <= 1 for x in p),
        "doc_hit5": sum(x.get("document_rank", 999) <= 5 for x in p),
        "evidence_hit1": sum(x.get("evidence_rank", 999) <= 1 for x in p),
        "evidence_hit5": sum(x.get("evidence_rank", 999) <= 5 for x in p),
        "evidence_hit10": sum(x.get("evidence_rank", 999) <= 10 for x in p),
        "questions": 18,
        "query_p50_ms": r["query_ms"]["p50"],
        "query_p95_ms": r["query_ms"]["p95"],
        "index_seconds": r["indexing_seconds"],
        "peak_rss_mib": r["peak_process_rss_mib"],
    }
    rows.append(row)
with (base / "comparison.csv").open("w") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
lines = [
    "# 모델별 실측 결과",
    "",
    "실험 범위·입력 계약·한계는 [README](README.md)를 먼저 확인한다. KLUE가 아닌 KURE-v1을 비교했다.",
    "",
    "| 모델 | 문서 @1 / @5 | 지정 근거 @1 / @5 / @10 | 질문 p50 / p95 ms | 색인 초 | 최대 RSS MiB |",
    "|---|---|---|---|---|---|",
]
for r in rows:
    lines.append(
        f"| {r['model']} | {r['doc_hit1']}/18 / {r['doc_hit5']}/18 | {r['evidence_hit1']}/18 / {r['evidence_hit5']}/18 / {r['evidence_hit10']}/18 | {r['query_p50_ms']:.2f} / {r['query_p95_ms']:.2f} | {r['index_seconds']:.2f} | {r['peak_rss_mib']:.1f} |"
    )
lines += [
    "",
    "## 문항별 지정 근거의 순위",
    "",
    "| 질문 | E5 | BGE-M3 | KURE-v1 |",
    "|---|---:|---:|---:|",
]
for i, p in enumerate(all_predictions[0][:18]):
    lines.append(
        "| "
        + p["question"]
        + " | "
        + " | ".join(str(ps[i]["evidence_rank"]) for ps in all_predictions)
        + " |"
    )
lines += [
    "",
    "## 답 없는 질문의 최고 유사도",
    "",
    "| 질문 | E5 | BGE-M3 | KURE-v1 |",
    "|---|---:|---:|---:|",
]
for i in range(18, 22):
    lines.append(
        "| "
        + all_predictions[0][i]["question"]
        + " | "
        + " | ".join(f"{ps[i]['hits'][0]['score']:.4f}" for ps in all_predictions)
        + " |"
    )
lines += [
    "",
    "유사도 척도는 모델마다 다르다. 서로의 숫자를 직접 비교해 정확성이나 거절 임계값을 결정하지 않는다. 최고 유사도는 답이 있다는 증거가 아니다.",
    "",
    "최대 RSS는 로딩·색인 포함 프로세스 최대값이고 모델만의 메모리가 아니다. 개발 PC의 CPU 2개 제한이며 배포 서버 측정이 아니다. E5는 앞 실험의 측정값으로 실행 시점 차이가 있다. 신규 모델 추론은 순차 실행했으나 BGE 실행 중 KURE 다운로드가 겹쳤다. 사용자 프로세스와 메모리 경합은 격리하지 않았다.",
    "",
    "## 정합성 검증",
    "",
    "verification.json에 원문 SHA, 질문·청크 범위 동일성, 벡터 정규화·유한성, 저장 벡터로 순위와 지표를 재계산한 결과를 기록한다.",
]
(base / "report.md").write_text("\n".join(lines) + "\n")
print(json.dumps(rows, ensure_ascii=False, indent=2))
