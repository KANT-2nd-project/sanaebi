"""지침 준수 비율과 추가 비교를 Markdown 보고서로 만든다 (docs/generation-evaluation.md 1·2장).

보고서는 판정과 측정 결과만 보여 준다. 두 모델이 1장 지침을 잘 지켰는지 보고,
그다음 2장 추가 비교로 어느 모델을 쓸지는 사람이 판단한다.

추정 비용 = 실측 토큰 수 × 사람이 확인한 단가. 단가는 바뀌므로 코드에 넣지 않고 JSON으로 받는다
(예시는 examples/prices.example.json, 키는 모델 설정의 비교 이름). 단가가 없는 모델은 계산하지 않는다.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from .checks import GUIDELINES, JUDGE_GUIDELINES
from .run import ANSWER_ROUTE
from .scoring import CHECK_SHEET, guideline_summary

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


# --- 보고서 ---

PREVIEW_CHARS = 160
BY_LABELS = {"code": "코드", "judge": "심판 LLM", "human": "사람"}
RUN_CHECK_LABELS = {
    "P1": "P1 호출 경로",
    "P2": "P2 회사 문서가 프롬프트에 있음",
    "P3": "P3 질문이 프롬프트에 있음",
    "P4": "P4 채점 정보가 프롬프트에 없음",
    "P5": "P5 프롬프트가 num_ctx 안 (Ollama)",
}
FAILURE_LABELS = {"error": "오류", "timeout": "시간 초과", "empty": "빈 답변"}


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


def ratio(passed, total):
    return "-" if not total else f"{passed}/{total} ({percent(passed / total)})"


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


def render_guidelines(guidelines, copy_limit):
    names = list(guidelines)
    if not names:
        return ["(지침 판정 대상 기록이 없다)"]
    rows = []
    for key, (label, by) in GUIDELINES.items():
        cells = []
        for name in names:
            counts = guidelines[name]["guidelines"][key]
            text = ratio(counts["passed"], counts["judged"])
            if counts["pending"]:
                text += f", 판정 전 {counts['pending']}"
            cells.append(text)
        rows.append([label, BY_LABELS[by], *cells])
    lines = table(["지침", "판정", *names], rows)
    targets = ", ".join(f"{n} {guidelines[n]['targets']}건" for n in names)
    lines += [
        "",
        "- 칸 = 지킨 답변 / 판정한 답변. 판정하지 않은 답변(빈 답변, 정답 문서를 적지 않은 질문 등)은 분모에서 뺀다.",
        f"- 판정 대상: 문서 답변 경로({ANSWER_ROUTE})에서 오류·시간 초과 없이 끝난 호출 ({targets})",
        "- 근거 문서 제목: 정답 문서 제목을 밝히고, 회사 문서에 없는 제목은 밝히지 않아야 통과",
        f"- 베끼기: 공백을 하나로 본 글자 수로 문서와 {copy_limit}자 이상 그대로 겹치면 실패",
        "- 심판 LLM 지침은 사람이 확인한 판정이 있으면 사람 판정을 쓴다.",
    ]
    return lines


def render_extra(summary, guidelines):
    models = summary["models"]
    if not models:
        return ["(문서 답변 경로 호출 기록이 없다)"]
    names = list(models)
    costs = summary.get("costs") or {}

    def failure_text(name):
        stats = models[name]
        counts = ", ".join(
            f"{FAILURE_LABELS[s]} {stats['failures'][s]}" for s in FAILURE_LABELS
        )
        return f"{percent(stats['failure_rate'])} ({counts} / 호출 {stats['calls']})"

    def cost_text(name):
        cost = costs.get(name)
        if not cost or cost["per_call"] is None:
            return "-"
        return f"{cost['per_call']:.6f} {cost['currency']} (합계 {cost['total']:.4f})"

    def repeat_text(name):
        stats = guidelines.get(name)
        if not stats or not stats["repeat_cases"]:
            return "-"
        return f"갈림 {stats['repeat_split_cases']}/{stats['repeat_cases']}문항"

    rows = [
        (
            "응답 시간 평균(초)",
            lambda n: number(models[n]["measured"]["latency_mean_seconds"]),
        ),
        (
            "응답 시간 최대(초)",
            lambda n: number(models[n]["measured"]["latency_max_seconds"]),
        ),
        ("호출 실패율", failure_text),
        ("비용 (추정, 호출당)", cost_text),
        ("반복 일관성", repeat_text),
        ("답변 길이 평균(글자)", lambda n: number(models[n]["answer_length_mean"], 1)),
    ]
    lines = table(
        ["항목", *names], [[label, *(f(n) for n in names)] for label, f in rows]
    )
    lines += [
        "",
        f"- 모두 문서 답변 경로({ANSWER_ROUTE}) 호출을 실행 기록으로 잰 값이다.",
        "- 응답 시간은 실행기 체인 전체를 잰 값이고, 모델별 첫 호출(모델 로딩)을 뺀다.",
        "- 반복 일관성 = 같은 질문을 두 번 이상 했을 때 '지침을 모두 지켰는가'가 갈린 질문 수 / 판정이 끝난 질문 수",
    ]
    if not costs:
        lines.append(
            "- 비용: 단가 파일(`--prices`)을 주면 실측 토큰 × 단가로 계산한다."
        )
    else:
        lines.append(
            "- 비용은 **추정값**이다: 오류 없는 호출의 실측 토큰 × 단가 파일의 단가."
        )
        mismatched = [n for n, c in costs.items() if c and not c["model_matches"]]
        if mismatched:
            lines.append(
                f"- 단가의 모델과 기록된 모델이 다르다: {', '.join(mismatched)}"
            )
    return lines


def render_agreement(agreement):
    checked = sum(a["checked"] for a in agreement.values())
    if not checked:
        return [
            f"(사람 확인 전이다. `{CHECK_SHEET}`의 human_ 칸에 통과 또는 실패를 적고 report를 다시 실행한다)"
        ]
    rows = [
        [
            GUIDELINES[key][0],
            agreement[key]["checked"],
            agreement[key]["same"],
            ratio(agreement[key]["same"], agreement[key]["checked"]),
        ]
        for key in JUDGE_GUIDELINES
    ]
    same = sum(a["same"] for a in agreement.values())
    rows.append(["합계", checked, same, ratio(same, checked)])
    lines = table(["지침", "사람이 본 판정", "같은 판정", "일치율"], rows)
    lines += [
        "",
        "- 심판이 실패로 본 답변은 전부, 모두 통과로 본 답변은 일부를 사람이 다시 본다.",
    ]
    return lines


def render_violations(verdicts):
    rows = []
    for key in sorted(verdicts):
        for guideline, item in verdicts[key].items():
            if item["ok"] is False:
                rows.append(
                    [
                        key[0],
                        key[1],
                        key[2],
                        GUIDELINES[guideline][0],
                        BY_LABELS[item["by"]],
                        preview(item["detail"]),
                    ]
                )
    if not rows:
        return ["없음"]
    return table(["질문 id", "모델", "반복", "지침", "판정", "이유"], rows)


def render_run_checks(summary):
    lines = table(
        ["점검", "통과", "실패", "해당 없음"],
        [
            [RUN_CHECK_LABELS[code], c["pass"], c["fail"], c["n/a"]]
            for code, c in summary["prompt_checks"].items()
        ],
    )
    lines += [
        "",
        f"- 호출 경로(P1)가 틀린 질문: {summary['wrong_route_cases'] or '없음'}",
        f"- 정답 근거 문서가 프롬프트에 빠진 질문: {summary['document_problem_cases'] or '없음'}",
    ]
    for name, stats in summary["models"].items():
        lines.append(
            f"- {name}: 출력 토큰 한도에 걸려 잘린 호출 {stats['truncated']}건,"
            f" 응답한 모델 이름 {', '.join(stats['served_models']) or '-'}"
        )
    lines.append("- 실행 점검이 실패하면 1·2장 결과를 그대로 믿기 어렵다.")
    return lines


def render_report(
    title, records, summary, verdicts, judgments, agreement, meta=None, copy_limit=None
):
    guidelines = guideline_summary(verdicts)
    judge_models = sorted({row.get("judge_model") or "-" for row in judgments.values()})
    lines = [
        f"# 생성 모델 평가 보고서 — {title}",
        "",
        f"- 작성: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        (
            f"- 기록 {len(records)}개 (질문 {summary['cases']}건), 심판 판정 {len(judgments)}건"
            f" ({', '.join(judge_models) or '심판 판정 전'})"
        ),
        "- 기준: docs/generation-evaluation.md (1장 지침 준수, 2장 추가 비교)",
        "",
        "## 1. 지침 준수 (모델별 지킨 비율)",
        "",
        *render_guidelines(guidelines, copy_limit),
        "",
        "## 2. 추가 비교",
        "",
        *render_extra(summary, guidelines),
        "",
        "## 3. 사람 확인 (심판 판정과 같은 비율)",
        "",
        *render_agreement(agreement),
        "",
        "## 4. 지침을 어긴 답변",
        "",
        *render_violations(verdicts),
        "",
        "## 5. 실행 점검",
        "",
        *render_run_checks(summary),
        "",
        "## 6. 실행 정보",
        "",
        *render_conditions(meta),
    ]
    return "\n".join(lines) + "\n"
