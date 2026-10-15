"""Record a known equivalent-evidence case without changing original metrics."""

import json
from pathlib import Path

base = Path(__file__).resolve().parent
paths = [
    base.parent / "e5-small-ko-v2-pilot-2026-10-15",
    base.parent / "embedding-comparison-2026-10-15/BAAI--bge-m3",
    base.parent / "embedding-comparison-2026-10-15/nlpai-lab--KURE-v1",
] + [p.parent for p in sorted(base.glob("*/results.json"))]
rows = []
for folder in paths:
    questions = json.loads((folder / "predictions.json").read_text())
    result = json.loads((folder / "results.json").read_text())
    question = next(q for q in questions if "PR" in q["question"])
    ranks = [
        hit["rank"]
        for hit in question["hits"]
        if "PR 작성자 혼자 자기 변경을 승인한 것으로 계산하지 않는다" in hit["body"]
    ]
    rows.append(
        {
            "model": result["model"],
            "specified_evidence_rank": question["evidence_rank"],
            "alternative_explicit_evidence_top5_ranks": ranks,
        }
    )
(base / "pr-evidence-audit.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
)
print("Audited PR evidence for", len(rows), "models; original metrics unchanged")
