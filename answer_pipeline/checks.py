"""실행 기록을 자동 점검한다: 프롬프트 점검 P1~P5, 응답 점검 A1~A6, 모델별 실측값.

LLM을 다시 부르지 않고 기록만 읽으므로 비용이 없고, 같은 기록이면 결과도 항상 같다.
점검 결과 ok: True = 통과, False = 실패(또는 경고), None = 해당 없음
기준은 docs/generation-evaluation.md B-5다. SEARCH_KNOWLEDGE는 회사 문서 전체로 LLM 답변을 하고,
CLARIFY·UNSUPPORTED는 LLM 없는 고정 안내로 본다 (P1, 기준 문서의 [결정 필요] 항목).
모델별 집계는 모델 설정의 비교 이름(model_name)으로 묶는다.
"""

import json
import re
import statistics

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .run import ANSWER_ROUTE, GRADING_FIELDS

FAIL, WARN = "fail", "warn"
PROMPT_CODES = ("P1", "P2", "P3", "P4", "P5")
ANSWER_CODES = ("A1", "A2", "A3", "A4", "A5", "A6")
WARN_CODES = ("A4", "A5", "A6")
# 사용 가능 답변의 자동 점검 조건 (B-4)
USABLE_AUTO_CODES = ("A1", "A2", "A3")
HANDLING_LABELS = {"llm": "LLM 문서 답변", "fixed": "LLM 없는 안내"}

NUMBER_PATTERN = re.compile(r"\d+")
# A5: 근거 표기 번호 [문서 N]은 숫자 주장이 아니므로 숫자를 찾기 전에 지운다
CITATION_PATTERN = re.compile(r"\[문서\s*\d+\]")
# A6: 실제로 처리한 것처럼 말하는 표현 (생성 모델은 신청·승인을 실행하지 않는다)
CLAIM_PATTERN = re.compile(
    r"(처리|접수|신청|완료|승인|등록|발급|변경|재설정)(했|하였|되었|됐)(습니다|어요)"
)


class AnswerPayload(BaseModel):
    """생성 응답이 가져야 할 구조: {"text": "..."} (다른 필드 없음)"""

    model_config = ConfigDict(extra="forbid")
    text: str

    @field_validator("text")
    @classmethod
    def not_blank(cls, value):
        # 공백만 있는 답변도 빈 답변으로 본다
        if not value.strip():
            raise ValueError("text가 비었습니다.")
        return value


class StructuredAnswerPayload(BaseModel):
    """현재 생성기의 구조화 응답. 과거 text 기록과 별도로 검증한다."""

    model_config = ConfigDict(extra="forbid")
    answer: str
    referenced_documents: list[str]
    note: str


def parse_answer(text):
    """형식이 맞으면 AnswerPayload를, 아니면 None을 돌려준다."""
    if not isinstance(text, str):
        return None
    try:
        return AnswerPayload.model_validate_json(text)
    except ValidationError:
        try:
            structured = StructuredAnswerPayload.model_validate_json(text)
            return AnswerPayload(text=structured.answer)
        except ValidationError:
            return None


def record_payload(record):
    """원문은 보존하고 도구 호출로 전달된 현재 구조화 응답도 검사한다."""
    structured = record.get("structured_response")
    if structured is not None:
        try:
            payload = StructuredAnswerPayload.model_validate(structured)
            return AnswerPayload(text=payload.answer)
        except ValidationError:
            return None
    return parse_answer(record.get("response_text"))


def answer_text(record):
    """내용 점검용 문자열. JSON이면 text, 형식이 깨졌으면 응답 원문 전체."""
    payload = record_payload(record)
    if payload is None:
        return record.get("response_text") or ""
    return payload.text


def check(code, ok, detail="", level=FAIL):
    return {"code": code, "ok": ok, "level": level, "detail": detail}


def not_applicable(codes, reason):
    return [
        check(code, None, reason, WARN if code in WARN_CODES else FAIL)
        for code in codes
    ]


def expected_handling(record):
    """정답 경로에 맞는 처리: SEARCH_KNOWLEDGE → "llm", CLARIFY·UNSUPPORTED → "fixed", 모르면 None."""
    route = record.get("expected_route")
    if route is None:
        return None
    return "llm" if route == ANSWER_ROUTE else "fixed"


def actual_handling(record):
    """실제 처리: LLM을 불렀으면 "llm", 오류 없이 부르지 않았으면 "fixed", 모델 호출 전 오류면 None."""
    if record.get("llm_called"):
        return "llm"
    return None if record.get("error") else "fixed"


def evidence_ids(record):
    return [doc["document_id"] for doc in record.get("evidence") or []]


def missing_documents(record):
    """프롬프트에 넣은 문서에 없는 정답 근거 문서 id (정렬). 정답 문서를 모르면 빈 목록."""
    expected = record.get("expected_document_ids") or []
    return sorted(set(expected) - set(evidence_ids(record)))


def document_problems(record):
    """③근거 문서 제공 단계의 문제 목록. 문서 답변 경로가 아니면 보지 않는다.

    초기 설계는 회사 문서 전체를 프롬프트에 넣으므로, 정답 근거 문서가 빠졌다면 문서 준비나
    전체 문서 불러오기의 문제다. 근거 부족이 정답인 질문(expected_document_ids == [])은 볼 것이 없다.
    """
    if record.get("expected_route") != ANSWER_ROUTE:
        return []
    missing = missing_documents(record)
    return (
        [f"프롬프트에 넣은 문서에 정답 근거 문서가 없음: {missing}"] if missing else []
    )


def question_forms(question):
    # 실행기는 질문을 그대로 넣는다. JSON 문자열로 감싸는 프롬프트도 같이 받는다.
    return (json.dumps(question, ensure_ascii=False), question)


def prompt_checks(record):
    """P1~P5: LangChain 실행기가 정한 호출 경로와 실제로 보낸 프롬프트가 맞는지 본다."""
    handling, wanted = actual_handling(record), expected_handling(record)
    if wanted is None:
        p1 = check("P1", None, "expected_route 없음")
    elif handling is None:
        p1 = check("P1", None, "모델 호출 전에 실행기 오류 (A1에서 판정)")
    elif handling == wanted:
        p1 = check("P1", True)
    else:
        p1 = check(
            "P1",
            False,
            f"{record['expected_route']} 경로는 {HANDLING_LABELS[wanted]}이어야 하는데 "
            f"{HANDLING_LABELS[handling]}",
        )

    prompt = record.get("prompt")
    if handling != "llm" or prompt is None:
        return [p1, *not_applicable(PROMPT_CODES[1:], "LLM을 부르지 않는 경로")]

    # P2 근거 포함: 넘겨받은 근거 문서 본문이 프롬프트에 모두 들어 있어야 한다
    evidence = record.get("evidence") or []
    if not evidence:
        p2 = check("P2", None, "근거 문서 없음")
    else:
        missing = [doc["document_id"] for doc in evidence if doc["text"] not in prompt]
        p2 = check(
            "P2",
            not missing,
            f"프롬프트에 없는 근거 문서: {missing}" if missing else "",
        )

    # P3 질문 포함: 질문 원문(또는 JSON 문자열)이 그대로 있어야 한다
    forms = question_forms(record["question"])
    included = any(form in prompt for form in forms)
    p3 = check("P3", included, "" if included else "질문 원문이 프롬프트에 없음")

    # P4 누출: 근거 문서·질문을 뺀 나머지(템플릿)에 채점 문장이나 채점 필드 이름이 있으면 안 된다
    # (required_points는 근거 문서에서 온 표현이라 근거 문서 제목·본문 안에는 있을 수 있다)
    documents = [doc["text"] for doc in evidence]
    documents += [doc["title"] for doc in evidence if doc.get("title")]
    rest = prompt
    for text in documents + list(forms):
        rest = rest.replace(text, "")
    grading = [*record.get("required_points", []), *record.get("forbidden_claims", [])]
    leaked = [text for text in grading if text in rest]
    leaked += [name for name in GRADING_FIELDS if name in prompt]
    p4 = check(
        "P4", not leaked, f"채점 정보가 프롬프트에 있음: {leaked}" if leaked else ""
    )

    # P5 길이: Ollama는 입력 + 최대 출력이 num_ctx를 넘으면 프롬프트를 잘라 버린다
    tokens = (record.get("usage") or {}).get("input_tokens")
    limits = record.get("limits") or {}
    num_ctx, max_output = limits.get("num_ctx"), limits.get("max_output_tokens")
    if record.get("provider") != "ollama":
        p5 = check("P5", None, "Ollama만 점검")
    elif tokens is None or num_ctx is None or max_output is None:
        p5 = check("P5", None, "입력 토큰 또는 num_ctx·최대 출력 기록 없음")
    else:
        ok = tokens + max_output <= num_ctx
        detail = "" if ok else f"입력 {tokens} + 출력 {max_output} > {num_ctx}"
        p5 = check("P5", ok, detail)
    return [p1, p2, p3, p4, p5]


def answer_checks(record):
    """A1~A6: LLM 응답을 본다. LLM을 부르지 않은 기록은 P1(호출 경로)로만 판정한다."""
    if not record.get("llm_called") and not record.get("error"):
        return not_applicable(ANSWER_CODES, "LLM 미호출")

    if record.get("error"):
        a1 = check("A1", False, f"호출 오류: {record['error']}")
        return [a1, *not_applicable(ANSWER_CODES[1:], "A1 실패로 점검 안 함")]
    a1 = check("A1", True)

    complete = bool(record.get("generation_complete"))
    reason = record.get("finish_reason")
    a2 = check(
        "A2",
        complete,
        "" if complete else f"생성이 끝나지 않음 (finish_reason={reason})",
    )

    valid = record_payload(record) is not None
    a3 = check("A3", valid, "" if valid else "text JSON 형식이 아님")

    content = answer_text(record)

    # A4 핵심 정보 (경고): required_points가 응답에 모두 있어야 한다 (글자 그대로 찾는다)
    required = record.get("required_points", [])
    if not required:
        a4 = check("A4", None, "required_points 없음", WARN)
    else:
        missing = [point for point in required if point not in content]
        a4 = check(
            "A4",
            not missing,
            f"빠진 핵심 정보: {', '.join(missing)}" if missing else "",
            WARN,
        )

    # A5 근거 없는 숫자 (경고): 근거 문서와 질문 어디에도 없는 숫자 (근거 표기 번호 제외)
    reference = " ".join(
        [*(doc["text"] for doc in record.get("evidence") or []), record["question"]]
    )
    allowed = set(NUMBER_PATTERN.findall(reference))
    numbers = NUMBER_PATTERN.findall(CITATION_PATTERN.sub(" ", content))
    unsupported = sorted(set(numbers) - allowed, key=int)
    detail = f"근거·질문에 없는 숫자: {', '.join(unsupported)}" if unsupported else ""
    a5 = check("A5", not unsupported, detail, WARN)

    # A6 처리 완료 주장 (경고)
    claims = sorted({match.group(0) for match in CLAIM_PATTERN.finditer(content)})
    a6 = check(
        "A6", not claims, f"처리 완료 표현: {', '.join(claims)}" if claims else "", WARN
    )
    return [a1, a2, a3, a4, a5, a6]


def evaluate_record(record):
    checks = prompt_checks(record) + answer_checks(record)
    failed = [c["code"] for c in checks if c["ok"] is False and c["level"] == FAIL]
    warnings = [c["code"] for c in checks if c["ok"] is False and c["level"] == WARN]
    return {
        "case_id": record["case_id"],
        "model_name": record["model_name"],
        "repeat": record["repeat"],
        "checks": checks,
        "failed": failed,
        "warnings": warnings,
        # 자동 점검 실패(P1~P5, A1~A3)가 1개 이상이면 이상한 답변. 사람 점수는 debug에서 더한다
        "auto_flagged": bool(failed),
        # 사용 가능 답변의 자동 조건(A1~A3 통과). 나머지 조건은 사람 채점으로 본다
        "auto_usable": bool(record.get("llm_called"))
        and not any(code in failed for code in USABLE_AUTO_CODES),
    }


def evaluate_records(records):
    return [evaluate_record(record) for record in records]


def measure(records):
    """모델 비교용 실측값. 오류 없는 호출만 세고, 지연 평균·중앙값은 첫 호출(cold start)을 뺀다."""
    ok = [r for r in records if not r.get("error")]
    warm = [r["latency_seconds"] for r in ok if not r.get("cold_start")]
    cold = [r["latency_seconds"] for r in ok if r.get("cold_start")]

    def tokens(key):
        return [
            r["usage"][key] for r in ok if (r.get("usage") or {}).get(key) is not None
        ]

    inputs, outputs = tokens("input_tokens"), tokens("output_tokens")
    return {
        "successful_calls": len(ok),
        "latency_mean_seconds": statistics.fmean(warm) if warm else None,
        "latency_median_seconds": statistics.median(warm) if warm else None,
        "latency_max_seconds": max(warm) if warm else None,
        "cold_start_latency_seconds": cold[0] if cold else None,
        "input_tokens_total": sum(inputs) if inputs else None,
        "output_tokens_total": sum(outputs) if outputs else None,
        "output_tokens_mean": statistics.fmean(outputs) if outputs else None,
    }


def summarize(records, evaluations):
    """보고용 집계. P는 질문 단위, A와 실측값은 모델별 호출 단위로 센다."""
    cases = sorted({r["case_id"] for r in records})

    prompt_summary = {}
    for code in PROMPT_CODES:
        counts = {"pass": 0, "fail": 0, "n/a": 0}
        for case_id in cases:
            values = [
                c["ok"]
                for e in evaluations
                if e["case_id"] == case_id
                for c in e["checks"]
                if c["code"] == code and c["ok"] is not None
            ]
            key = "n/a" if not values else ("pass" if all(values) else "fail")
            counts[key] += 1
        prompt_summary[code] = counts

    models = {}
    for name in sorted({e["model_name"] for e in evaluations}):
        subset = [e for e in evaluations if e["model_name"] == name]
        model_records = [r for r in records if r["model_name"] == name]

        def count(code, value, rows=subset):
            return sum(
                c["ok"] is value for e in rows for c in e["checks"] if c["code"] == code
            )

        models[name] = {
            "provider": model_records[0]["provider"],
            "model": model_records[0].get("model"),
            "served_models": sorted(
                {r["served_model"] for r in model_records if r.get("served_model")}
            ),
            "calls": len(subset),
            "failures": {
                code: count(code, False)
                for code in ANSWER_CODES
                if code not in WARN_CODES
            },
            "warnings": {code: count(code, False) for code in WARN_CODES},
            "checked": {code: len(subset) - count(code, None) for code in ANSWER_CODES},
            "flagged": sum(e["auto_flagged"] for e in subset),
            "auto_usable": sum(e["auto_usable"] for e in subset),
            "measured": measure(model_records),
        }

    return {
        "records": len(records),
        "cases": len(cases),
        "prompt_checks": prompt_summary,
        "models": models,
        "no_llm_records": sum(not r.get("llm_called") for r in records),
        "wrong_route_cases": sorted(
            {e["case_id"] for e in evaluations if "P1" in e["failed"]}
        ),
        "document_problem_cases": sorted(
            {r["case_id"] for r in records if document_problems(r)}
        ),
    }
