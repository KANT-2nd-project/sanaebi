"""심판 판정의 사람 확인과 지침별 최종 판정 (docs/generation-evaluation.md 1장).

사람 확인표에는 심판이 지침을 하나라도 실패로 본 답변은 전부, 모두 통과로 본 답변은 일부
(PASS_SAMPLE_RATE)를 넣는다. 확인표는 모델 이름을 가리고 순서를 섞는다. 모델은 정답 키
(human_check_key.csv)로만 이어진다. 사람은 human_<지침> 칸에 "통과" 또는 "실패"를 적는다.
최종 판정은 코드 지침은 코드 판정, 심판 지침은 사람 판정이 있으면 사람 판정, 없으면 심판 판정이다.
사람과 심판의 판정이 같은 비율은 agreement로 따로 센다.
"""

import csv
import math
import random
from pathlib import Path

from .checks import CODE, GUIDELINES, JUDGE_GUIDELINES, answer_text
from .judge import expected_text
from .run import record_key

CHECK_SHEET = "human_check.csv"
CHECK_KEY = "human_check_key.csv"
# 심판이 모두 통과로 본 답변 중 사람이 다시 볼 비율 (1장 "통과로 본 답변은 일부")
PASS_SAMPLE_RATE = 0.2
HUMAN_VALUES = {"통과": True, "실패": False}
PENDING, NOT_APPLICABLE = "pending", "n/a"


def judge_text(ok):
    return "통과" if ok else "실패"


def write_check_sheet(
    records, judgments, run_dir, sample_rate=PASS_SAMPLE_RATE, seed=42
):
    """사람 확인표와 정답 키를 쓴다. 이미 있으면 덮어쓰지 않는다. 돌려주는 값: 확인표 행 수."""
    run_dir = Path(run_dir)
    sheet_path, key_path = run_dir / CHECK_SHEET, run_dir / CHECK_KEY
    if sheet_path.exists() or key_path.exists():
        raise FileExistsError(
            f"사람 확인표가 이미 있습니다 (확인 내용 보호): {sheet_path}"
        )

    by_key = {record_key(r): r for r in records}
    judged = sorted(key for key in judgments if key in by_key)
    failed = [
        key
        for key in judged
        if not all(v["ok"] for v in judgments[key]["verdicts"].values())
    ]
    passed = [key for key in judged if key not in failed]
    rng = random.Random(seed)
    chosen = failed + rng.sample(passed, math.ceil(len(passed) * sample_rate))
    rng.shuffle(chosen)

    sheet_rows, key_rows = [], []
    for number, key in enumerate(chosen, start=1):
        record, verdicts = by_key[key], judgments[key]["verdicts"]
        check_id = f"H{number:03d}"
        row = {
            "check_id": check_id,
            "case_id": record["case_id"],
            "question": record["question"],
            "expected_documents": expected_text(record),
            "required_points": " / ".join(record.get("required_points") or []),
            "answer": answer_text(record),
        }
        for guideline in JUDGE_GUIDELINES:
            row[f"judge_{guideline}"] = judge_text(verdicts[guideline]["ok"])
            row[f"judge_{guideline}_reason"] = verdicts[guideline]["reason"]
            row[f"human_{guideline}"] = ""
        row["notes"] = ""
        sheet_rows.append(row)
        key_rows.append(
            {
                "check_id": check_id,
                "case_id": key[0],
                "model_name": key[1],
                "repeat": key[2],
            }
        )
    for path, rows in ((sheet_path, sheet_rows), (key_path, key_rows)):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=list(rows[0]) if rows else ["check_id"]
            )
            writer.writeheader()
            writer.writerows(rows)
    return len(sheet_rows)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def load_human_checks(run_dir):
    """사람이 적은 판정만 {(case_id, model_name, repeat): {지침: True/False}}로 돌려준다.

    확인표가 없으면 빈 딕셔너리. 빈 칸은 확인하지 않은 것으로 본다.
    """
    run_dir = Path(run_dir)
    sheet_path, key_path = run_dir / CHECK_SHEET, run_dir / CHECK_KEY
    if not (sheet_path.exists() and key_path.exists()):
        return {}
    keys = {
        row["check_id"]: (row["case_id"], row["model_name"], int(row["repeat"]))
        for row in read_csv(key_path)
    }
    human = {}
    for row in read_csv(sheet_path):
        checked = {}
        for guideline in JUDGE_GUIDELINES:
            value = (row.get(f"human_{guideline}") or "").strip()
            if not value:
                continue
            if value not in HUMAN_VALUES:
                raise ValueError(
                    f"{row['check_id']} human_{guideline}는 통과 또는 실패여야 합니다: {value!r}"
                )
            checked[guideline] = HUMAN_VALUES[value]
        if checked:
            human[keys[row["check_id"]]] = checked
    return human


def final_verdicts(evaluation, judgment=None, human=None):
    """기록 1개의 지침별 최종 판정 {지침: {"ok", "by", "detail"}}. 지침 판정 대상이 아니면 {}.

    by: "code", "judge", "human", PENDING(심판 판정 전), NOT_APPLICABLE(판정하지 않음)
    """
    code = evaluation["guidelines"]
    if not code:
        return {}
    human = human or {}
    verdicts = {}
    for key, (_, by) in GUIDELINES.items():
        if by == CODE:
            item = code[key]
            source = "code" if item["ok"] is not None else NOT_APPLICABLE
            verdicts[key] = {"ok": item["ok"], "by": source, "detail": item["detail"]}
        elif evaluation["status"] == "empty":
            verdicts[key] = {"ok": None, "by": NOT_APPLICABLE, "detail": "빈 답변"}
        elif judgment is None:
            verdicts[key] = {"ok": None, "by": PENDING, "detail": "심판 판정 전"}
        else:
            reason = judgment["verdicts"][key]["reason"]
            if key in human:
                verdicts[key] = {"ok": human[key], "by": "human", "detail": reason}
            else:
                ok = judgment["verdicts"][key]["ok"]
                verdicts[key] = {"ok": ok, "by": "judge", "detail": reason}
    return verdicts


def all_kept(verdicts):
    """지침을 모두 지켰는가. 판정 전 지침이 있으면 None."""
    if any(v["by"] == PENDING for v in verdicts.values()):
        return None
    return all(v["ok"] is not False for v in verdicts.values())


def verdicts_by_key(evaluations, judgments, human):
    """지침 판정 대상 기록마다 최종 판정."""
    result = {}
    for evaluation in evaluations:
        key = record_key(evaluation)
        verdicts = final_verdicts(evaluation, judgments.get(key), human.get(key))
        if verdicts:
            result[key] = verdicts
    return result


def guideline_summary(verdicts):
    """모델별 지침 통과 수와 반복 일관성.

    {model_name: {"targets", "guidelines": {지침: {"passed", "judged", "pending"}},
                  "repeat_cases", "repeat_split_cases"}}
    반복 일관성: 같은 질문을 두 번 이상 했을 때 '지침을 모두 지켰는가'가 갈린 질문 수.
    """
    summary = {}
    for name in sorted({key[1] for key in verdicts}):
        rows = {key: v for key, v in verdicts.items() if key[1] == name}
        guidelines = {}
        for guideline in GUIDELINES:
            values = [v[guideline] for v in rows.values()]
            guidelines[guideline] = {
                "passed": sum(v["ok"] is True for v in values),
                "judged": sum(v["ok"] is not None for v in values),
                "pending": sum(v["by"] == PENDING for v in values),
            }
        by_case = {}
        for (case_id, _, _), v in rows.items():
            by_case.setdefault(case_id, []).append(all_kept(v))
        repeated = [v for v in by_case.values() if len(v) > 1 and None not in v]
        summary[name] = {
            "targets": len(rows),
            "guidelines": guidelines,
            "repeat_cases": len(repeated),
            "repeat_split_cases": sum(len(set(v)) > 1 for v in repeated),
        }
    return summary


def agreement(judgments, human):
    """지침별 사람과 심판의 판정이 같은 수. {지침: {"checked", "same"}}."""
    result = {guideline: {"checked": 0, "same": 0} for guideline in JUDGE_GUIDELINES}
    for key, checked in human.items():
        judgment = judgments.get(key)
        if judgment is None:
            continue
        for guideline, ok in checked.items():
            result[guideline]["checked"] += 1
            result[guideline]["same"] += judgment["verdicts"][guideline]["ok"] is ok
    return result
