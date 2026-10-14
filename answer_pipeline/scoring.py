"""사람 채점표와 사용 가능 답변 판정 (docs/generation-evaluation.md B-3, B-4, B-7).

채점표는 모델 이름을 가리고 순서를 섞는다. 정답 키(answer_key.csv)는 채점이 끝난 뒤에만 연다.
채운 채점표는 load_human_scores로 읽어 사용 가능 답변 비율과 역순 디버깅에 반영한다.
"""

import csv
import random
from pathlib import Path

from .checks import answer_text
from .run import ANSWER_ROUTE, record_key

# 각 0~2점. 응답 형식·오류·시간·토큰은 자동으로 재므로 사람은 내용만 본다
SCORE_FIELDS = (
    "grounded",  # 근거 충실성
    "citation",  # 근거 표기 (문서 내용을 말하지 않은 응답은 NA)
    "relevance",  # 질문 적합성
    "handling",  # 질문 형식별 처리
    "required_points",  # 핵심 정보
    "clarity",  # 명확성
)
NOT_APPLICABLE = "NA"
NA_ALLOWED = ("citation",)
CRITICAL_FIELD = "critical_defects"
CRITICAL_CODES = ("C1", "C2", "C3", "C4", "C5")
SHEET_NAME = "human_scores_blind.csv"
KEY_NAME = "answer_key.csv"


def evidence_titles(record):
    """채점자가 볼 정답 근거 문서. 정답 문서를 모르면 프롬프트에 넣은 문서 수만 적는다."""
    evidence = record.get("evidence") or []
    if not evidence:
        return "(근거 문서 없음)"
    expected = record.get("expected_document_ids")
    if expected is None:
        return f"회사 문서 전체 {len(evidence)}건 (정답 근거 문서 미지정)"
    if not expected:
        return f"회사 문서 전체 {len(evidence)}건 (정답: 근거 부족)"
    by_id = {doc["document_id"]: doc for doc in evidence}
    return "\n".join(
        f"[문서 {i}] {(by_id.get(i) or {}).get('title') or '(프롬프트에 없음)'}"
        for i in expected
    )


def scorable(record):
    """채점 대상: 정답 경로가 SEARCH_KNOWLEDGE이고 오류 없이 LLM이 답한 기록.

    CLARIFY·UNSUPPORTED는 LLM 없는 고정 안내로 보고 P1로만 판정한다 (B-2, [결정 필요]).
    호출 오류(A1 실패)는 응답이 없어 채점하지 않는다 (B-7).
    """
    return (
        record.get("expected_route") == ANSWER_ROUTE
        and record.get("llm_called")
        and not record.get("error")
    )


def write_blind_sheet(records, out_dir, seed=42):
    """채점 대상 응답만 담은 채점표를 쓴다. 이미 있으면 덮어쓰지 않는다.

    채점표에는 자동 점검 정보와 모델 정보를 넣지 않는다 (B-7).
    """
    out_dir = Path(out_dir)
    sheet_path, key_path = out_dir / SHEET_NAME, out_dir / KEY_NAME
    if sheet_path.exists() or key_path.exists():
        raise FileExistsError(f"채점표가 이미 있습니다 (채점 내용 보호): {sheet_path}")

    scored = [r for r in records if scorable(r)]
    order = list(range(len(scored)))
    random.Random(seed).shuffle(order)
    sheet_rows, key_rows = [], []
    for number, position in enumerate(order, start=1):
        record = scored[position]
        sheet_id = f"S{number:03d}"
        sheet_rows.append(
            {
                "sheet_id": sheet_id,
                "case_id": record["case_id"],
                "question": record["question"],
                "expected_route": record.get("expected_route") or "",
                "question_type": record.get("question_type") or "",
                "evidence": evidence_titles(record),
                "text": answer_text(record),
                "required_points_expected": " / ".join(
                    record.get("required_points", [])
                ),
                "forbidden_claims": " / ".join(record.get("forbidden_claims", [])),
                **{field: "" for field in SCORE_FIELDS},
                CRITICAL_FIELD: "",
                "notes": "",
            }
        )
        key_rows.append(
            {
                "sheet_id": sheet_id,
                "case_id": record["case_id"],
                "repeat": record["repeat"],
                "model_name": record["model_name"],
                "model": record.get("model") or "",
            }
        )
    for path, rows in ((sheet_path, sheet_rows), (key_path, key_rows)):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=list(rows[0]) if rows else ["sheet_id"]
            )
            writer.writeheader()
            writer.writerows(rows)
    return len(sheet_rows)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_score_row(row):
    """채점표 한 행. 모두 비었으면 None(미채점), 일부만 채웠으면 오류."""
    sheet_id = row.get("sheet_id")
    raw = {field: (row.get(field) or "").strip() for field in SCORE_FIELDS}
    critical_raw = (row.get(CRITICAL_FIELD) or "").strip()
    if not any(raw.values()) and not critical_raw:
        return None
    missing = [field for field, value in raw.items() if not value]
    if missing:
        raise ValueError(f"{sheet_id}: 채점하지 않은 항목이 있습니다: {missing}")
    scores = {}
    for field, value in raw.items():
        if value.upper() == NOT_APPLICABLE and field in NA_ALLOWED:
            scores[field] = None
        elif value in ("0", "1", "2"):
            scores[field] = int(value)
        else:
            allowed = "0·1·2" + (" 또는 NA" if field in NA_ALLOWED else "")
            raise ValueError(f"{sheet_id} {field}는 {allowed}여야 합니다: {value!r}")
    critical = sorted(
        {code.strip().upper() for code in critical_raw.split(",") if code.strip()}
    )
    unknown = [code for code in critical if code not in CRITICAL_CODES]
    if unknown:
        raise ValueError(
            f"{sheet_id} {CRITICAL_FIELD}는 {CRITICAL_CODES}를 쉼표로 적습니다: {unknown}"
        )
    return {"scores": scores, "critical": critical}


def load_human_scores(run_dir):
    """채점한 행만 {(case_id, model_name, repeat): {"scores", "critical"}}로 돌려준다.

    채점표가 없으면 빈 딕셔너리.
    """
    run_dir = Path(run_dir)
    sheet_path, key_path = run_dir / SHEET_NAME, run_dir / KEY_NAME
    if not (sheet_path.exists() and key_path.exists()):
        return {}
    keys = {
        row["sheet_id"]: (row["case_id"], row["model_name"], int(row["repeat"]))
        for row in read_csv(key_path)
    }
    human = {}
    for row in read_csv(sheet_path):
        parsed = parse_score_row(row)
        if parsed is not None:
            human[keys[row["sheet_id"]]] = parsed
    return human


def is_usable(evaluation, human):
    """사용 가능 답변 판정 (B-4). 사람 채점 전이면 None.

    A1~A3 통과, 치명 결함 없음, grounded 2점, 나머지 항목 1점 이상 (citation NA 제외).
    """
    if not evaluation["auto_usable"]:
        return False
    if human is None:
        return None
    scores = human["scores"]
    return (
        not human["critical"]
        and scores["grounded"] == 2
        and all(
            value >= 1
            for field, value in scores.items()
            if field != "grounded" and value is not None
        )
    )


def zero_fields(human):
    return [f for f, v in (human or {}).get("scores", {}).items() if v == 0]


def summarize_human_scores(human_by_key):
    """모델별 사람 채점 집계: 채점 수, 항목별 평균·0점 수, 치명 결함 코드별 수.

    {model_name: {"scored", "means": {항목: 평균 또는 None}, "zeros": {항목: 개수},
                  "critical": {코드: 개수}, "critical_responses": 치명 결함이 있는 응답 수}}
    """
    summary = {}
    for name in sorted({key[1] for key in human_by_key}):
        rows = [v for k, v in human_by_key.items() if k[1] == name]
        means, zeros = {}, {}
        for field in SCORE_FIELDS:
            values = [
                r["scores"][field] for r in rows if r["scores"][field] is not None
            ]
            means[field] = sum(values) / len(values) if values else None
            zeros[field] = sum(v == 0 for v in values)
        summary[name] = {
            "scored": len(rows),
            "means": means,
            "zeros": zeros,
            "critical": {
                code: sum(code in r["critical"] for r in rows)
                for code in CRITICAL_CODES
            },
            "critical_responses": sum(bool(r["critical"]) for r in rows),
        }
    return summary


def usable_summary(records, evaluations, human_by_key):
    """모델별 사용 가능 답변 비율과 반복 일관성 (B-4, B-6).

    분모는 정답 경로가 SEARCH_KNOWLEDGE인 기록 전체다 (호출 오류 포함, C-3의 "모델당 40회").
    사람 채점이 끝나지 않은 응답이 있으면 비율은 None이고 pending에 남은 수를 적는다.
    """
    evaluation_by_key = {record_key(e): e for e in evaluations}
    result = {}
    for name in sorted({r["model_name"] for r in records}):
        subset = [
            r
            for r in records
            if r["model_name"] == name and r.get("expected_route") == ANSWER_ROUTE
        ]
        verdicts = {
            record_key(r): is_usable(
                evaluation_by_key[record_key(r)], human_by_key.get(record_key(r))
            )
            for r in subset
        }
        usable = sum(v is True for v in verdicts.values())
        pending = sum(v is None for v in verdicts.values())
        by_case = {}
        for (case_id, _, _), verdict in verdicts.items():
            by_case.setdefault(case_id, []).append(verdict)
        judged_cases = [v for v in by_case.values() if len(v) > 1 and None not in v]
        result[name] = {
            "calls": len(subset),
            # A1~A3 실패 (호출 오류·잘림·형식). 출시 기준의 두 번째 조건
            "auto_failures": sum(
                not evaluation_by_key[record_key(r)]["auto_usable"] for r in subset
            ),
            "usable": usable,
            "pending": pending,
            "usable_ratio": None if pending or not subset else usable / len(subset),
            "repeat_cases": len(judged_cases),
            "repeat_split_cases": sum(len(set(v)) > 1 for v in judged_cases),
            "verdicts": verdicts,
        }
    return result


def usable_by_tag(records, usable, tag):
    """모델 × 태그 값별 (사용 가능 수, 판정 수). 태그가 없는 기록은 "(없음)"."""
    table = {}
    for record in records:
        verdict = usable[record["model_name"]]["verdicts"].get(record_key(record))
        if verdict is None:
            continue
        value = record.get(tag) or "(없음)"
        cell = table.setdefault(record["model_name"], {}).setdefault(value, [0, 0])
        cell[0] += verdict is True
        cell[1] += 1
    return table
