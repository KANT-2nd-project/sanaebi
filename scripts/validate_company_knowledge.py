"""회사 정책 릴리스의 구조·참조·해시 검사. 의미·법률 검토를 대신하지 않는다."""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "data/company-knowledge"


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def validate(base=DEFAULT):
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    docs = jsonl(base / "documents.jsonl")
    evaluations = jsonl(base / "evaluations/eval_set.jsonl")
    evidence = jsonl(base / "evaluations/evidence.jsonl")
    sources = csv_rows(base / "sources.csv")
    decisions = csv_rows(base / "policy-decisions.csv")
    mapping = csv_rows(base / "topic-map.csv")
    reviews = csv_rows(base / "document-review.csv")
    manifest = json.loads((base / "manifests/release.json").read_text())
    docmap = {d["document_id"]: d for d in docs}
    source_ids = {s["source_id"] for s in sources}
    decision_ids = {d["decision_id"] for d in decisions}
    require(len(docs) == len(docmap) == 52, "52개 고유 문서 필요")
    require(len(source_ids) == len(sources), "출처 ID 중복")
    require(len(decision_ids) == len(decisions), "결정 ID 중복")
    require(len(evaluations) == 208, "평가 질문 208개 필요")
    require(len({e["id"] for e in evaluations}) == 208, "평가 ID 중복")
    require(len({e["question"] for e in evaluations}) == 208, "평가 질문 중복")
    for source in sources:
        required = (
            "source_id",
            "title",
            "publisher",
            "source_url",
            "version_or_publication_date",
            "accessed_at",
            "verified_sections",
            "verified_facts",
            "policy_topics",
            "intended_use_and_limits",
            "reuse_status",
            "rights_or_license_evidence_url",
        )
        require(
            all(source.get(k, "").strip() for k in required),
            f"{source.get('source_id')}: 출처 필수 정보 누락",
        )
        require(
            source.get("source_url", "").startswith("https://"),
            f"{source.get('source_id')}: 출처 URL 오류",
        )
    for decision in decisions:
        require(
            all(
                decision.get(k, "").strip()
                for k in (
                    "decision_id",
                    "decision",
                    "decision_value",
                    "rationale",
                    "applies_to",
                    "status",
                )
            ),
            f"{decision.get('decision_id')}: 결정 필수 정보 누락",
        )
        targets = (
            set(docmap)
            if decision.get("applies_to") == "모든 정책"
            else {x.strip() for x in decision.get("applies_to", "").split(",")}
        )
        require(
            targets <= set(docmap),
            f"{decision.get('decision_id')}: 결정 적용 문서 누락",
        )
        actual = {
            d["document_id"]
            for d in docs
            if decision["decision_id"] in d.get("policy_decision_ids", [])
        }
        require(
            targets == actual, f"{decision.get('decision_id')}: 결정 적용 문서 불일치"
        )
    for doc in docs:
        did = doc["document_id"]
        require(
            all(
                isinstance(doc.get(k), str) and doc[k].strip()
                for k in ("document_id", "title", "document", "version", "category")
            ),
            f"{did}: 필수 문자열",
        )
        require(doc.get("review_status") == "ai_reviewed", f"{did}: 독립 검수 미완료")
        require(
            bool(doc.get("source_ids")) and set(doc["source_ids"]) <= source_ids,
            f"{did}: 출처 참조",
        )
        require(
            bool(doc.get("policy_decision_ids"))
            and set(doc["policy_decision_ids"]) <= decision_ids,
            f"{did}: 결정 참조",
        )
        sections = doc.get("source_sections", [])
        require(
            {s.get("source_id") for s in sections} == set(doc.get("source_ids", [])),
            f"{did}: 출처 구역 누락",
        )
        require(
            all(
                all(
                    s.get(k) for k in ("source_id", "section", "verified_fact", "usage")
                )
                for s in sections
            ),
            f"{did}: 출처 구역 필수 필드",
        )
    require(
        len(mapping) == 52
        and {int(m["original_row"]) for m in mapping} == set(range(1, 53)),
        "원본 주제 대응 누락",
    )
    require({m["document_id"] for m in mapping} == set(docmap), "주제 문서 대응 불일치")
    original_topics = jsonl(ROOT / "data/archive/company-knowledge-v0/ieum_works.jsonl")
    for m in mapping:
        number = int(m["original_row"])
        require(
            1 <= number <= len(original_topics)
            and m["original_title"] == original_topics[number - 1]["title"],
            "원본 주제 제목 불일치",
        )
        require(
            m["new_title"] == docmap.get(m["document_id"], {}).get("title"),
            "주제 제목 불일치",
        )
    artifact_paths = (
        "documents.jsonl",
        "sources.csv",
        "policy-decisions.csv",
        "topic-map.csv",
        "document-review.csv",
        "evaluations/eval_set.jsonl",
        "evaluations/evidence.jsonl",
    )
    artifacts = manifest.get("artifact_sha256", {})
    require(set(artifacts) == set(artifact_paths), "manifest 산출물 해시 목록 누락")
    for relative in artifact_paths:
        current = hashlib.sha256((base / relative).read_bytes()).hexdigest()
        require(artifacts.get(relative) == current, f"{relative}: 산출물 해시 불일치")
    entries = manifest["documents"]
    require(
        [m["document_id"] for m in entries] == [d["document_id"] for d in docs],
        "manifest 순서 불일치",
    )
    for entry in entries:
        doc = docmap.get(entry["document_id"], {})
        require(
            entry["content_sha256"] == digest(doc.get("document", "")),
            f"{entry['document_id']}: manifest 해시 불일치",
        )
        require(entry["version"] == doc.get("version"), "manifest 버전 불일치")
    reviewmap = {r["document_id"]: r for r in reviews}
    require(
        len(reviews) == len(reviewmap) == 52 and set(reviewmap) == set(docmap),
        "52개 문서 검수 연결 필요",
    )
    for did, doc in docmap.items():
        review = reviewmap.get(did, {})
        require(
            review.get("content_sha256") == digest(doc["document"]),
            f"{did}: 검수 해시 불일치",
        )
        require(
            review.get("status") == "ai_reviewed" and bool(review.get("reviewer")),
            f"{did}: 검수 근거 누락",
        )
        require(
            review.get("human_approved") == "false", f"{did}: 사람 승인 상태 불일치"
        )
    evidencemap = {e["eval_id"]: e for e in evidence}
    require(len(evidence) == len(evidencemap) == 208, "평가 근거 208개 필요")
    require(set(evidencemap) == {e["id"] for e in evaluations}, "평가 근거 ID 불일치")
    owners = Counter()
    kinds = {}
    for row in evaluations:
        eid = row["id"]
        ev = evidencemap.get(eid, {})
        ids = row.get("expected_document_ids", [])
        require(set(ids) <= set(docmap), f"{eid}: 없는 문서 참조")
        require(
            row["expected_route"] == "SEARCH_KNOWLEDGE", f"{eid}: 답변 평가 라벨 불일치"
        )
        require(
            ev.get("expected_document_ids") == ids
            and bool(ev.get("expected_behavior")),
            f"{eid}: 평가 근거·기대 행동 불일치",
        )
        require(
            ev.get("forbidden_claims") == row.get("forbidden_claims"),
            f"{eid}: 금지 주장 불일치",
        )
        owner = eid.rsplit("-", 1)[0]
        owners[owner] += 1
        kinds.setdefault(owner, set()).add(eid.rsplit("-", 1)[1])
        if row.get("question_type") == "no_evidence":
            require(
                ids == []
                and ev.get("answerability") in ("insufficient", "no_evidence"),
                f"{eid}: 미기재 조건 불일치",
            )
        else:
            require(
                bool(ids) and bool(row.get("required_points")),
                f"{eid}: 근거·필수 사실 누락",
            )
        texts = [docmap[did]["document"] for did in ids if did in docmap]
        for point in row.get("required_points", []):
            require(
                any(point in text for text in texts),
                f"{eid}: 본문에 없는 필수 표현 {point}",
            )
        refs = ev.get("evidence_sections", [])
        if row.get("question_type") != "no_evidence":
            require(
                {r.get("document_id") for r in refs} == set(ids),
                f"{eid}: 근거 위치 누락",
            )
        else:
            require(refs == [], f"{eid}: 미기재 질문에 근거 인용")
        for ref in refs:
            target = docmap.get(ref["document_id"], {}).get("document", "")
            parts = re.split(r"(?m)^## +", target)
            sections = {
                part.split("\n", 1)[0].strip(): part.split("\n", 1)[1]
                if "\n" in part
                else ""
                for part in parts[1:]
            }
            require(
                ref.get("section") in sections
                and ref.get("quote", "") in sections.get(ref.get("section"), ""),
                f"{eid}: 근거 구역 불일치",
            )
            require(
                ref["document_id"] in ids
                and bool(ref.get("section"))
                and bool(ref.get("quote"))
                and ref["quote"] in target,
                f"{eid}: 근거 위치·인용 불일치",
            )
    require(
        set(owners) == set(docmap) and set(owners.values()) == {4},
        "문서당 4개 평가 필요",
    )
    require(
        all(v == {"direct", "condition", "missing", "action"} for v in kinds.values()),
        "문서별 평가 유형 누락",
    )
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT)
    args = parser.parse_args()
    try:
        errors = validate(args.base)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise SystemExit(f"회사 정책 검증 실패: {exc}") from exc
    if errors:
        raise SystemExit("\n".join(errors))
    print("회사 정책 검증 통과: 문서 52개, 평가 208개, 출처·결정·검수·manifest 연결")


if __name__ == "__main__":
    main()
