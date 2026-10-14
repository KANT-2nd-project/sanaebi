"""자동 점검·사람 채점 결과로 이상한 답변의 원인을 거슬러 찾고, Markdown 비교 보고서를 만든다.

보고 순서는 docs/generation-evaluation.md E장을 따른다. 선정은 C-3 규칙을 기계적으로
적용한 결과만 보여 주고, 최종 결정과 해석은 사람이 적는다.

역순 디버깅 (D장)
  정상 흐름:  ①입력 → ③근거 문서 제공 → ④프롬프트 → ⑤호출 → ⑥형식 → ⑦내용
  ⑦에서 증상을 보고 ①까지 거슬러 올라가며 모든 단계를 검사한다. 원인 = 문제가 있는 가장 앞쪽
  단계, 그 뒤의 문제는 전파된 증상이다. 정상 단계를 만나도 멈추지 않는다 (예: 형식은 멀쩡한데
  정답 근거 문서가 빠져 핵심 정보가 빠짐). ②요청 분류는 정답 경로를 고정 입력으로 쓰므로 보지 않는다.
  디버깅 대상: 자동 점검 실패(P1~P5, A1~A3)가 있거나 사람 채점에서 사용 불가인 기록.

추정 비용 = 실측 토큰 수 × 사람이 확인한 단가. 단가는 바뀌므로 코드에 넣지 않고 JSON으로 받는다
(예시는 examples/prices.example.json, 키는 모델 설정의 비교 이름). 단가가 없는 모델은 계산하지 않는다.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from .checks import (
    ANSWER_CODES,
    USABLE_AUTO_CODES,
    WARN_CODES,
    document_problems,
)
from .run import ANSWER_ROUTE, record_key
from .scoring import (
    CRITICAL_CODES,
    SCORE_FIELDS,
    is_usable,
    summarize_human_scores,
    usable_by_tag,
    zero_fields,
)

# --- 추정 비용 ---


PRICE_FIELDS = (
    "model",
    "input_per_1m_tokens",
    "output_per_1m_tokens",
    "currency",
    "checked_on",
    "source",
)
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def load_prices(path):
    """단가 파일을 읽고 검사한다. 빈 칸이나 예시 값이 남아 있으면 막는다."""
    prices = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(prices, dict) or not prices:
        raise ValueError(f"단가 파일은 {{비교 이름: 단가}} 객체여야 합니다: {path}")
    for name, price in prices.items():
        missing = [f for f in PRICE_FIELDS if f not in (price or {})]
        if missing:
            raise ValueError(f"{name} 단가에 빠진 항목: {missing}")
        for field in ("input_per_1m_tokens", "output_per_1m_tokens"):
            value = price[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
            ):
                raise ValueError(
                    f"{name} {field}는 0 이상의 숫자여야 합니다: {value!r}"
                )
        if not DATE_PATTERN.fullmatch(str(price["checked_on"])):
            raise ValueError(
                f"{name} checked_on은 YYYY-MM-DD 날짜여야 합니다: {price['checked_on']!r}"
            )
        for field in ("model", "currency", "source"):
            if not str(price[field]).strip():
                raise ValueError(f"{name} {field}가 비었습니다.")
    return prices


def estimate_costs(summary, records, prices):
    """모델별 추정 비용. 단가가 없는 모델은 None.

    오류 없는 호출의 토큰만 센다 (summary의 measured와 같은 기준). 실패한 호출도 요금이
    나갈 수 있으므로 실제 청구액과 다를 수 있다. 기록의 모델 이름이 단가의 모델과 다르면
    model_matches가 False가 된다.
    """
    costs = {}
    for name, stats in summary["models"].items():
        price = prices.get(name)
        if price is None:
            costs[name] = None
            continue
        measured = stats["measured"]
        input_tokens = measured["input_tokens_total"] or 0
        output_tokens = measured["output_tokens_total"] or 0
        total = (
            input_tokens / 1_000_000 * price["input_per_1m_tokens"]
            + output_tokens / 1_000_000 * price["output_per_1m_tokens"]
        )
        calls = measured["successful_calls"]
        recorded = sorted(
            {r["model"] for r in records if r["model_name"] == name and r.get("model")}
        )
        costs[name] = {
            "model": price["model"],
            "recorded_models": recorded,
            "model_matches": recorded == [price["model"]],
            "currency": price["currency"],
            "total": total,
            "per_call": total / calls if calls else None,
            "checked_on": price["checked_on"],
            "source": price["source"],
        }
    return costs


# --- 역순 디버깅 ---


STAGES = ("input", "documents", "prompt", "call", "format", "content")
STAGE_LABELS = {
    "input": "①입력",
    "documents": "③근거 문서 제공",
    "prompt": "④프롬프트",
    "call": "⑤호출",
    "format": "⑥형식",
    "content": "⑦내용",
}
# 자동 점검 코드가 어느 단계의 문제인지
STAGE_OF_CHECK = {
    "P1": "prompt",
    "P2": "prompt",
    "P3": "prompt",
    "P4": "prompt",
    "P5": "prompt",
    "A1": "call",
    "A2": "format",
    "A3": "format",
}
NEXT_ACTION = {
    "input": "평가 데이터 확인: required_points가 정답 근거 문서에 실제로 있는지, "
    "expected_route·expected_document_ids가 맞는지",
    "documents": "답변용 회사 문서 확인: 정답 근거 문서가 문서 JSONL에 있는지, "
    "전체 문서를 빠짐없이 프롬프트에 넣었는지",
    "prompt": "LangChain 실행기 확인: 실패한 P 항목(호출 경로, 근거·질문 포함, 채점 정보 누출, 길이)",
    "call": "모델 서버 상태, API 키, 시간 제한 확인",
    "format": "출력 토큰 한도(잘림) 또는 형식 지시문을 모델이 따르는지 확인",
    "content": "모델의 응답 내용 문제: 아래 '해석'(다른 반복·다른 모델 비교)을 보고 판단",
}


def stage_problems(record, evaluation, human=None):
    """단계별 문제 목록. 빈 목록이면 그 단계는 정상이다."""
    problems = {stage: [] for stage in STAGES}

    # ① 입력: 정답 근거 문서를 모두 찾았는데도 required_points가 그 문서들에 없으면 채점 데이터가 틀린 것이다
    expected_ids = record.get("expected_document_ids") or []
    found = {doc["document_id"]: doc["text"] for doc in record.get("evidence") or []}
    if expected_ids and all(i in found for i in expected_ids):
        texts = [found[i] for i in expected_ids]
        absent = [
            point
            for point in record.get("required_points", [])
            if not any(point in text for text in texts)
        ]
        if absent:
            problems["input"].append(
                f"required_points {absent}가 정답 근거 문서에 없음"
            )

    # ③ 근거 문서 제공
    problems["documents"].extend(document_problems(record))

    # ④~⑥: 자동 점검 실패 (경고 A4~A6은 원인 판정에 넣지 않는다)
    for item in evaluation["checks"]:
        stage = STAGE_OF_CHECK.get(item["code"])
        if stage and item["ok"] is False and item["level"] == "fail":
            problems[stage].append(f"{item['code']} {item['detail']}".strip())

    # ⑦: 사람 채점에서 사용 불가 (치명 결함, 0점, grounded 2점 미만)
    if human is not None:
        for code in human["critical"]:
            problems["content"].append(f"치명 결함 {code}")
        for field in zero_fields(human):
            problems["content"].append(f"사람 채점 {field} = 0")
        if is_usable(evaluation, human) is False and not problems["content"]:
            grounded = human["scores"]["grounded"]
            if grounded != 2:
                problems["content"].append(f"사람 채점 grounded = {grounded}")
    return problems


def trace_back(problems):
    """⑦에서 ①로 거슬러 올라가며 검사한다. (원인 단계, 검사 경로)를 돌려준다."""
    origin, path = None, []
    for stage in reversed(STAGES):
        path.append({"stage": stage, "problems": problems[stage]})
        if problems[stage]:
            origin = stage  # 멈추지 않고 끝까지 올라가며 가장 앞쪽 문제로 갱신한다
    return origin, path


def is_flagged(evaluation, human=None):
    """이상한 답변: 자동 점검 실패 1개 이상, 또는 사람 채점에서 사용 불가."""
    if evaluation["auto_flagged"]:
        return True
    return human is not None and is_usable(evaluation, human) is False


def compare_siblings(record, flagged_by_key):
    """⑤~⑦이 원인일 때 같은 질문의 다른 반복·다른 모델과 비교해 원인을 좁힌다."""
    case_id, name = record["case_id"], record["model_name"]
    same = [v for k, v in flagged_by_key.items() if k[0] == case_id and k[1] == name]
    others = [v for k, v in flagged_by_key.items() if k[0] == case_id and k[1] != name]
    if not all(same):
        return "우연한 변동: 같은 모델의 다른 반복은 정상"
    if not others:
        return "비교할 다른 모델 기록 없음"
    if all(others):
        return "프롬프트·근거 의심: 모든 모델이 실패"
    return "모델 한계: 이 모델만 반복 모두 실패"


def debug_records(records, evaluations, human_by_key=None):
    """모든 기록의 역추적 결과. 이상한 답변이 아니어도 앞 단계 문제가 있으면 남긴다 (숨은 문제)."""
    human_by_key = human_by_key or {}
    evaluation_by_key = {record_key(e): e for e in evaluations}
    flagged_by_key = {
        key: is_flagged(evaluation, human_by_key.get(key))
        for key, evaluation in evaluation_by_key.items()
    }

    traces = []
    for record in records:
        key = record_key(record)
        human = human_by_key.get(key)
        evaluation = evaluation_by_key[key]
        problems = stage_problems(record, evaluation, human)
        origin, path = trace_back(problems)
        flagged = flagged_by_key[key]
        interpretation = None
        if flagged and origin in ("call", "format", "content"):
            interpretation = compare_siblings(record, flagged_by_key)
        traces.append(
            {
                "case_id": record["case_id"],
                "model_name": record["model_name"],
                "repeat": record["repeat"],
                "flagged": flagged,
                "symptoms": evaluation["failed"]
                + [f"치명:{c}" for c in (human or {}).get("critical", [])]
                + [f"사람:{f}" for f in zero_fields(human)],
                "warnings": evaluation["warnings"],
                "origin": origin,
                "path": path,
                "interpretation": interpretation,
                "next_action": NEXT_ACTION.get(origin) if origin else None,
                "human_scores": human,
            }
        )
    return traces


def origin_distribution(traces):
    """이상한 답변의 원인 단계별 건수 (모델별)."""
    names = sorted({t["model_name"] for t in traces})
    table = {stage: {n: 0 for n in names} for stage in STAGES}
    for trace in traces:
        if trace["flagged"] and trace["origin"]:
            table[trace["origin"]][trace["model_name"]] += 1
    return table


# --- 보고서 ---

PREVIEW_CHARS = 160
# C-3 출시 기준과 선정 규칙 (제안값)
MAX_CRITICAL_RATE = 0.025
MAX_AUTO_FAILURE_RATE = 0.10
LOCAL_PREFERENCE_GAP = 0.10
SLOW_LATENCY_SECONDS = 10.0


def cell(text):
    # 표 칸 안에서 줄바꿈과 | 가 표를 깨지 않게 한다
    return str(text).replace("|", "\\|").replace("\n", " ")


def preview(text, limit=PREVIEW_CHARS):
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def number(value, digits=2):
    if value is None:
        return "-"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def percent(value):
    return "-" if value is None else f"{value * 100:.1f}%"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return lines


def model_verdicts(summary, usable, human_summary):
    """모델별 C-3 판정 재료: 호출 수, 사용 가능 비율, 치명 결함, A1~A3 실패, 출시 기준."""
    verdicts = {}
    for name, stats in usable.items():
        calls, auto_failures = stats["calls"], stats["auto_failures"]
        critical = (human_summary.get(name) or {}).get("critical_responses")
        release = None
        if calls and stats["pending"] == 0 and critical is not None:
            release = (
                critical / calls <= MAX_CRITICAL_RATE
                and auto_failures / calls <= MAX_AUTO_FAILURE_RATE
            )
        verdicts[name] = {
            "provider": summary["models"].get(name, {}).get("provider"),
            "calls": calls,
            "usable": stats["usable"],
            "pending": stats["pending"],
            "usable_ratio": stats["usable_ratio"],
            "critical": critical,
            "auto_failures": auto_failures,
            "release": release,
        }
    return verdicts


def select_model(verdicts):
    """C-3 선정 규칙. (선정 모델 또는 None, 설명 줄 목록)."""
    if not verdicts:
        return None, ["LLM 호출 기록이 없다."]
    pending = [n for n, v in verdicts.items() if v["release"] is None]
    if pending:
        return None, [
            f"사람 채점이 끝나지 않아 판정하지 않았다: {', '.join(pending)}",
        ]
    ratios = {n: v["usable_ratio"] for n, v in verdicts.items()}
    passed = [n for n, v in verdicts.items() if v["release"]]
    lines = [
        (
            f"출시 기준 통과: {', '.join(passed) or '없음'} "
            f"(치명 결함 {MAX_CRITICAL_RATE:.1%} 이하, A1~A3 실패 {MAX_AUTO_FAILURE_RATE:.0%} 이하)"
        )
    ]
    candidates = passed or list(verdicts)
    best = max(candidates, key=lambda n: ratios[n])
    if len(passed) == 1:
        lines.append(f"한 모델만 통과해 {best}를 고른다.")
        return best, lines
    if not passed:
        lines.append(
            f"모두 통과하지 못해 비율이 가장 높은 {best}를 고르고, "
            "서비스 기본 경로로는 부족하다고 적는다."
        )
        return best, lines
    locals_ = [
        n
        for n in passed
        if verdicts[n]["provider"] == "ollama"
        and ratios[best] - ratios[n] <= LOCAL_PREFERENCE_GAP
    ]
    if locals_:
        choice = max(locals_, key=lambda n: ratios[n])
        lines.append(
            f"최고 비율 {best} {percent(ratios[best])}와 Local {choice} "
            f"{percent(ratios[choice])}의 차이가 {LOCAL_PREFERENCE_GAP:.0%}p 이하라 Local을 고른다."
        )
        return choice, lines
    lines.append(f"비율 차이가 {LOCAL_PREFERENCE_GAP:.0%}p를 넘어 {best}를 고른다.")
    return best, lines


def render_conditions(meta):
    if not meta:
        return ["(meta.json이 없어 실행 조건을 표시하지 않는다)"]
    lines = [
        f"- 실행일: {meta.get('created', '-')}",
        (
            f"- 평가 세트: {meta.get('eval_set_path', '-')}"
            f" (sha256 {str(meta.get('eval_set_sha256', '-'))[:12]}),"
            f" 구분 {', '.join(meta.get('splits') or []) or '-'},"
            f" 질문 {meta.get('cases', '-')}건, 반복 {meta.get('repeats', '-')}회"
        ),
    ]
    executor = meta.get("executor") or {}
    if executor:
        lines += [
            (
                f"- 실행기: {executor.get('file')}"
                f" (sha256 {str(executor.get('sha256'))[:12]},"
                f" 커밋 {executor.get('git_commit') or '-'}),"
                f" 프롬프트 sha256 {str(executor.get('prompt_sha256'))[:12]}"
            ),
            (
                f"- 회사 문서: {executor.get('documents_path')}"
                f" ({executor.get('documents')}건,"
                f" sha256 {str(executor.get('documents_sha256'))[:12]})"
            ),
        ]
    models = meta.get("models") or []
    if models:
        keys = [k for k in models[0] if k != "name"]
        for model in models[1:]:
            keys += [k for k in model if k != "name" and k not in keys]
        lines += [
            "",
            "실행기가 실제로 쓴 호출 조건 (빈 값 = 모델·라이브러리 기본값):",
            "",
        ]
        lines += table(
            ["항목", *(m["name"] for m in models)],
            [[key, *(number(m.get(key)) for m in models)] for key in keys],
        )
    return lines


def render_summary_table(summary, usable, verdicts, human_summary):
    names = list(verdicts)
    if not names:
        return ["(SEARCH_KNOWLEDGE 경로 기록 없음)"]
    models = summary["models"]
    costs = summary.get("costs") or {}

    def ratio_text(name):
        v = verdicts[name]
        if v["pending"]:
            passed = v["calls"] - v["auto_failures"]
            return f"채점 대기 {v['pending']}건 (A1~A3 통과 {passed}건)"
        return f"{v['usable']}/{v['calls']} ({percent(v['usable_ratio'])})"

    def repeat_text(name):
        stats = usable[name]
        if not stats["repeat_cases"]:
            return "-"
        return f"갈림 {stats['repeat_split_cases']}/{stats['repeat_cases']}문항"

    def cost_text(name):
        c = costs.get(name)
        if not c:
            return "-"
        return (
            f"{c['per_call']:.6f} {c['currency']}/회 (추정)" if c["per_call"] else "-"
        )

    rows = [
        ("판정 호출 수 (SEARCH_KNOWLEDGE)", lambda n: verdicts[n]["calls"]),
        ("**사용 가능 답변**", ratio_text),
        (
            "치명 결함 응답 수",
            lambda n: (
                "-" if verdicts[n]["critical"] is None else verdicts[n]["critical"]
            ),
        ),
        ("A1~A3 실패", lambda n: verdicts[n]["auto_failures"]),
        (
            "출시 기준",
            lambda n: {None: "판정 전", True: "통과", False: "미통과"}[
                verdicts[n]["release"]
            ],
        ),
        ("반복 일관성 (사용 가능 여부)", repeat_text),
        (
            "지연 평균 (초, 첫 호출 제외)",
            lambda n: number(models[n]["measured"]["latency_mean_seconds"]),
        ),
        (
            "출력 토큰 평균",
            lambda n: number(models[n]["measured"]["output_tokens_mean"], 1),
        ),
        ("비용", cost_text),
        ("응답한 모델 이름", lambda n: ", ".join(models[n]["served_models"]) or "-"),
    ]
    lines = table(
        ["항목", *names], [[label, *(f(n) for n in names)] for label, f in rows]
    )
    lines += [
        "",
        (
            "- 사용 가능 답변 = A1~A3 통과 + 치명 결함 없음 + grounded 2점"
            " + 나머지 항목 1점 이상 (B-4). 분모는 정답 경로가 SEARCH_KNOWLEDGE인 기록 전체다."
        ),
        "- 반복 일관성 = 같은 질문의 반복 사이에 사용 가능 여부가 갈린 문항 수 / 판정한 문항 수.",
    ]
    slow = [
        n
        for n in names
        if (models[n]["measured"]["latency_mean_seconds"] or 0) > SLOW_LATENCY_SECONDS
    ]
    if slow:
        lines.append(
            f"- 평균 응답이 {SLOW_LATENCY_SECONDS:g}초를 넘는 모델: {', '.join(slow)} (한계로 적는다)"
        )
    return lines


def render_selection(verdicts):
    choice, explanation = select_model(verdicts)
    lines = [f"- {line}" for line in explanation]
    lines.append(f"- 규칙 적용 결과: **{choice or '판정 전'}**")
    lines += [
        "",
        "### 선정 결정 (직접 작성)",
        "",
        "- 선정 모델:",
        "- 근거 (출시 기준 → 비율 차이 → 결론):",
        "- 조건 차이 (모델·버전, temperature, 최대 출력 토큰, 반복 수, 실행 장비):",
        "- 실측값과 추정값 구분 (비용은 추정):",
        "- 한계와 미검증 사항:",
    ]
    return lines


def render_prompt_checks(summary):
    return table(
        ["점검", "통과", "실패", "해당 없음"],
        [
            [code, c["pass"], c["fail"], c["n/a"]]
            for code, c in summary["prompt_checks"].items()
        ],
    )


def render_answer_checks(summary):
    models = summary["models"]
    if not models:
        return ["(LLM 호출 기록 없음)"]
    names = list(models)
    rows = [["호출 수", *(models[n]["calls"] for n in names)]]
    for code in ANSWER_CODES:
        kind, key = ("경고", "warnings") if code in WARN_CODES else ("실패", "failures")
        rows.append(
            [
                code,
                *(
                    f"{kind} {models[n][key][code]} / {models[n]['checked'][code]}"
                    for n in names
                ),
            ]
        )
    rows.append(["이상한 답변(자동)", *(models[n]["flagged"] for n in names)])
    return table(["점검", *names], rows)


def render_measurements(summary):
    models = summary["models"]
    if not models:
        return ["(LLM 호출 기록 없음)"]
    rows = [
        ("성공 호출", "successful_calls", 0),
        ("지연 평균(초)", "latency_mean_seconds", 2),
        ("지연 중앙값(초)", "latency_median_seconds", 2),
        ("지연 최대(초)", "latency_max_seconds", 2),
        ("첫 호출 지연(초)", "cold_start_latency_seconds", 2),
        ("입력 토큰 합계", "input_tokens_total", 0),
        ("출력 토큰 합계", "output_tokens_total", 0),
        ("출력 토큰 평균", "output_tokens_mean", 1),
    ]
    names = list(models)
    return table(
        ["항목", *names],
        [
            [label, *(number(models[n]["measured"][key], d) for n in names)]
            for label, key, d in rows
        ],
    )


def render_costs(summary):
    costs = summary.get("costs")
    if not costs:
        return [
            "- 비용: 단가 파일(`--prices`)을 주지 않아 계산하지 않았다. 위 토큰 수 × 확인한 단가로 계산한다."
        ]
    names = list(costs)

    def per_call(c):
        return "-" if c["per_call"] is None else f"{c['per_call']:.6f} {c['currency']}"

    rows = [
        ("단가 기준 모델", lambda c: c["model"]),
        ("기록된 모델", lambda c: ", ".join(c["recorded_models"]) or "-"),
        ("모델 일치", lambda c: "예" if c["model_matches"] else "**아니요**"),
        ("추정 비용 합계", lambda c: f"{c['total']:.4f} {c['currency']}"),
        ("호출당 추정 비용", per_call),
        ("단가 확인일", lambda c: c["checked_on"]),
        ("단가 출처", lambda c: c["source"]),
    ]
    lines = table(
        ["항목", *names],
        [
            [label, *("단가 없음" if costs[n] is None else f(costs[n]) for n in names)]
            for label, f in rows
        ],
    )
    lines += [
        "",
        "- **추정값**이다: 오류 없는 호출의 실측 토큰 × 단가 파일의 단가. 실패한 호출 요금은 들어가지 않는다.",
    ]
    return lines


def render_human_scores(human_summary):
    if not human_summary:
        return [
            "(채점한 응답이 없다. `human_scores_blind.csv`를 채운 뒤 report를 다시 실행한다)"
        ]
    names = list(human_summary)
    rows = [["채점한 응답 수", *(human_summary[n]["scored"] for n in names)]]
    for field in SCORE_FIELDS:
        rows.append(
            [
                field,
                *(
                    f"평균 {number(human_summary[n]['means'][field])} · 0점 {human_summary[n]['zeros'][field]}"
                    for n in names
                ),
            ]
        )
    for code in CRITICAL_CODES:
        rows.append(
            [f"치명 {code}", *(human_summary[n]["critical"][code] for n in names)]
        )
    return table(["항목 (0~2점)", *names], rows)


def render_by_tag(records, usable, tag):
    by_tag = usable_by_tag(records, usable, tag)
    if not by_tag:
        return ["(사람 채점이 끝난 응답이 없어 집계하지 않았다)"]
    names = list(by_tag)
    values = sorted({v for counts in by_tag.values() for v in counts})

    def ratio(name, value):
        hit, total = by_tag[name].get(value, (0, 0))
        return "-" if not total else f"{hit}/{total} ({percent(hit / total)})"

    lines = table(
        [tag, *names], [[value, *(ratio(n, value) for n in names)] for value in values]
    )
    lines += ["", "- 칸마다 표본이 작으므로 경향만 본다."]
    return lines


def render_report(title, records, summary, traces, human, usable, meta=None):
    human_summary = summarize_human_scores(human or {})
    verdicts = model_verdicts(summary, usable, human_summary)
    splits = sorted({r.get("split") or "-" for r in records})
    record_by_key = {record_key(r): r for r in records}
    flagged = [t for t in traces if t["flagged"]]
    hidden = [t for t in traces if not t["flagged"] and t["origin"]]

    lines = [
        f"# 생성 모델 비교·답변 평가 보고서 — {title}",
        "",
        f"- 작성: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        (
            f"- 기록 {len(records)}개 (질문 {summary['cases']}건, "
            f"LLM 미호출 {summary['no_llm_records']}개), 이상한 답변 {len(flagged)}개"
        ),
        "- 이상한 답변 = 자동 점검 실패(P1~P5, A1~A3) 1개 이상 또는 사람 채점에서 사용 불가",
        f"- 평가 세트 구분(split): {', '.join(splits)}",
        "- 사람 채점 반영: "
        + (
            f"{len(human)}건"
            if human
            else "아니요 (채점표가 비어 있어 자동 점검만 반영)"
        ),
        "- 원인 = ⑦에서 ①로 거슬러 올라가며 문제가 있는 가장 앞쪽 단계",
        "",
        "## 1. 실행 정보",
        "",
        *render_conditions(meta),
        "",
        "## 2. 요약 비교표",
        "",
        *render_summary_table(summary, usable, verdicts, human_summary),
        "",
        "## 3. 선정 규칙 적용 (C-3)",
        "",
        *render_selection(verdicts),
        "",
        "## 4. 질문 형식별 사용 가능 비율",
        "",
        *render_by_tag(records, usable, "question_type"),
        "",
        "## 5. 주제별 사용 가능 비율",
        "",
        *render_by_tag(records, usable, "topic"),
        "",
        "## 6. 근거 위치별 사용 가능 비율",
        "",
        *render_by_tag(records, usable, "evidence_position"),
        "",
        "## 7. 사람 채점 (모델별)",
        "",
        *render_human_scores(human_summary),
        "",
        "## 8. 프롬프트 점검 (질문 단위)",
        "",
        *render_prompt_checks(summary),
        "",
        f"- 호출 경로(P1)가 틀린 질문: {summary['wrong_route_cases'] or '없음'}",
        f"- 근거 문서 제공 문제가 있는 질문: {summary['document_problem_cases'] or '없음'}",
        "",
        "## 9. 응답 점검 (모델별, 실패·경고 수 / 판정한 호출 수)",
        "",
        *render_answer_checks(summary),
        "",
        f"- 사용 가능 답변의 자동 조건은 {', '.join(USABLE_AUTO_CODES)} 통과다.",
        "",
        "## 10. 실측값 (오류 없는 호출 기준)",
        "",
        *render_measurements(summary),
        "",
        (
            "- 지연은 실행기 체인 전체(문서 읽기, 프롬프트 조립, 모델 호출)를 잰 값이다."
            " 평균·중앙값·최대는 모델별 첫 호출(모델 로딩)을 뺀다."
        ),
        "",
        *render_costs(summary),
        "",
        "## 11. 원인 단계 분포 (이상한 답변 기준)",
        "",
    ]

    distribution = origin_distribution(traces)
    names = sorted({t["model_name"] for t in traces})
    lines += table(
        ["단계", *names, "합계"],
        [
            [
                STAGE_LABELS[stage],
                *(distribution[stage][n] for n in names),
                sum(distribution[stage].values()),
            ]
            for stage in STAGES
        ],
    )

    lines += ["", "## 12. 이상한 답변 목록", ""]
    if not flagged:
        lines.append("없음")
    else:
        lines += table(
            ["질문 id", "모델", "반복", "증상", "원인 단계", "해석"],
            [
                [
                    t["case_id"],
                    t["model_name"],
                    t["repeat"],
                    ", ".join(t["symptoms"]),
                    STAGE_LABELS[t["origin"]] if t["origin"] else "-",
                    t["interpretation"] or "-",
                ]
                for t in flagged
            ],
        )

    lines += ["", "## 13. 사례별 역추적 (⑦ → ①)", ""]
    for t in flagged:
        record = record_by_key[(t["case_id"], t["model_name"], int(t["repeat"]))]
        documents = [doc["document_id"] for doc in record.get("evidence") or []]
        origin = STAGE_LABELS[t["origin"]] if t["origin"] else "-"
        lines += [
            f"### {t['case_id']} · {t['model_name']} · {t['repeat']}회차",
            "",
            f"- 질문: {record['question']}",
            f"- 경로: {record.get('expected_route')} (정답 경로를 고정 입력으로 사용)",
            f"- 근거 문서: {len(documents)}건 / 정답: {record.get('expected_document_ids')}",
            f"- 응답: {preview(record['response_text'])}",
            f"- **원인: {origin}** — {t['next_action'] or '-'}",
        ]
        if t["interpretation"]:
            lines.append(f"- 해석: {t['interpretation']}")
        lines += [""]
        lines += table(
            ["단계", "확인 결과"],
            [
                [
                    STAGE_LABELS[step["stage"]],
                    "; ".join(step["problems"]) if step["problems"] else "정상",
                ]
                for step in t["path"]
            ],
        )
        lines.append("")

    lines += [
        "## 14. 숨은 문제 (이상한 답변은 아니지만 앞 단계에 문제가 있는 기록)",
        "",
    ]
    if not hidden:
        lines.append("없음")
    for t in hidden:
        problems = [p for step in t["path"] for p in step["problems"]]
        lines.append(
            f"- {t['case_id']} · {t['model_name']} · {t['repeat']}회차: "
            f"{STAGE_LABELS[t['origin']]} — {'; '.join(problems)}"
        )
    lines += [
        "",
        f"- {ANSWER_ROUTE}가 아닌 경로의 기록은 P1(호출 경로)로만 판정하고 사용 가능 비율에 넣지 않는다.",
    ]
    return "\n".join(lines) + "\n"
