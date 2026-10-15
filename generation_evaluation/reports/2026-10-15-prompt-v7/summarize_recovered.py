"""Summarize restored answer judgments without inventing lost measurements."""

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parents[1] / "experiments/prompt-v7-20261015"


def main():
    summaries = {}
    sections = [
        "# 복구한 문항별 응답·판정·근거",
        "",
        "답변 본문과 판정은 세션 로그에서 복구했다. 익명 매핑은 고정 실행 순서와 기록된 seed로 재구성했다. 원 provider JSON·호출별 토큰·시간 파일은 소실되어 이 문서에 임의 생성하지 않는다. 복구 출처와 한계는 recovery/ 자료를 따른다.",
        "",
    ]
    for stage, judgment_file, fixture in [
        (
            "development",
            "judgments/development-judgments-rechecked.json",
            "development.json",
        ),
        ("final", "final-judgments-merged.json", "selection.json"),
    ]:
        mappings = json.loads((HERE / f"recovery/{stage}-mapping.json").read_text())
        rows = {
            row["anonymous_id"]: row
            for row in map(
                json.loads,
                (HERE / f"recovery/{stage}-responses.jsonl").read_text().splitlines(),
            )
        }
        judgments = json.loads((HERE / "recovery" / judgment_file).read_text())[
            "responses"
        ]
        cases = {
            c["id"]: c for c in json.loads((EXPERIMENT / fixture).read_text())["cases"]
        }
        groups = defaultdict(list)
        for judgment in judgments:
            identity = mappings[judgment["anonymous_id"]]
            groups[identity["profile"]].append({**identity, **judgment})
        profile_summary = {}
        for profile, group in groups.items():
            per_case = defaultdict(list)
            for row in group:
                per_case[row["case_id"]].append(row)
            stable = [
                key
                for key, values in per_case.items()
                if len(values) == (3 if stage == "final" else 1)
                and all(v["content"] == "pass" for v in values)
            ]
            profile_summary[profile] = {
                "responses": len(group),
                "content": dict(Counter(row["content"] for row in group)),
                "all_repetitions_pass_cases": sorted(stable),
                "missing_required_groups": sum(
                    c["status"] == "missing"
                    for row in group
                    for c in row["required_checks"]
                ),
                "uncertain_required_groups": sum(
                    c["status"] == "uncertain"
                    for row in group
                    for c in row["required_checks"]
                ),
                "common_readability_pass": sum(
                    row["common_readability"] == "pass" for row in group
                ),
                "structure_pass": sum(row["structure"] == "pass" for row in group),
                "major_error_responses": sum(
                    row["major_grounded_or_authority_error"] for row in group
                ),
                "unnecessary_guidance": sum(
                    row["unnecessary_guidance"] for row in group
                ),
                "conditional_sequence_error": sum(
                    row["conditional_sequence_error"] for row in group
                ),
                "unnecessary_formatting": sum(
                    row["unnecessary_formatting"] for row in group
                ),
                "per_response_latency_and_usage": None,
            }
        summaries[stage] = profile_summary
        sections += ["## " + stage, ""]
        for case_id, case in cases.items():
            sections += [f"### {case_id} — {case['question']}", "", "**필수 기준**", ""]
            sections += [
                f"{i + 1}. {value}" for i, value in enumerate(case["required"])
            ]
            sections += ["", "**근거**", ""]
            for evidence in case["evidence"]:
                sections += [
                    "- "
                    + evidence.get("document_id", evidence.get("path", "runtime"))
                    + ": "
                    + evidence["quote"].replace("\n", " ")
                ]
            sections += [""]
            for profile, group in sorted(groups.items()):
                for row in sorted(group, key=lambda row: row["repetition"]):
                    if row["case_id"] != case_id:
                        continue
                    answer = rows[row["anonymous_id"]]
                    sections += [
                        f"#### {profile} · 반복 {row['repetition']}",
                        "",
                        f"내용 {row['content']} / 가독성 {row['common_readability']} / 구조 {row['structure']} / 중대한 오류 {row['major_grounded_or_authority_error']}",
                        "",
                        answer["answer"],
                        "",
                        "판정: " + row["rationale"],
                        "",
                    ]
                    sections += [
                        f"- 필수 {c['index'] + 1}: {c['status']} — {c['rationale']}"
                        for c in row["required_checks"]
                        if c["status"] != "met"
                    ]
                    sections += [
                        "",
                        "복구 ID: "
                        + row["anonymous_id"]
                        + "; 호출별 시간·사용량: 미복구.",
                        "",
                    ]
    (HERE / "quality-summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n"
    )
    (HERE / "case-results.md").write_text("\n".join(sections) + "\n")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
