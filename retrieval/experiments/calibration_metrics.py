"""Claim-based calibration metrics; no model or provider dependencies."""

import math


def covers(intervals, start, end):
    cursor = start
    for left, right in sorted(intervals):
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return cursor >= end


def claim_metrics(items, case):
    documents = {}
    for document_id, spans in items:
        documents.setdefault(document_id, []).extend(spans)
    claims = case.get("required_claims", [])
    present = []
    for claim in claims:
        hit = any(
            alternative["spans"]
            and all(
                covers(
                    documents.get(alternative["document_id"], []),
                    span["start"],
                    span["end"],
                )
                for span in alternative["spans"]
            )
            for alternative in claim["evidence_alternatives"]
        )
        present.append(hit)
    return {
        "included": sum(present),
        "required": len(claims),
        "recall": sum(present) / len(claims) if claims else None,
        "complete": all(present) if claims else None,
        "missing_claims": [
            c["claim_id"] for c, hit in zip(claims, present, strict=True) if not hit
        ],
    }


def ranking_metrics(ids, grades, k):
    if k < 1:
        raise ValueError("k must be positive")
    ids = ids[:k]
    unknown = sum(cid not in grades for cid in ids)
    if unknown:
        return {"precision": None, "ndcg": None, "unjudged_count": unknown}
    gains = [grades[cid] for cid in ids]
    ideal = sorted(grades.values(), reverse=True)[:k]

    def dcg(values):
        return sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(values))

    denominator = dcg(ideal)
    return {
        "precision": sum(g >= 2 for g in gains) / k,
        "ndcg": dcg(gains) / denominator if denominator else None,
        "unjudged_count": 0,
    }
