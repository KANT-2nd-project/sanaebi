"""실행 기록을 코드로 점검한다: 코드가 판정하는 지침 4개, 실행 점검 P1~P5, 모델별 실측값.

LLM을 다시 부르지 않고 기록만 읽으므로 비용이 없고, 같은 기록이면 결과도 항상 같다.
판정 값 ok: True = 통과, False = 실패, None = 판정하지 않음
지침과 판정 주체는 docs/generation-evaluation.md 1장, 추가 비교는 2장을 따른다.
심판 LLM이 판정하는 지침은 judge.py, 사람 확인과 지침별 최종 판정은 scoring.py가 맡는다.
지침은 문서 답변 경로(SEARCH_KNOWLEDGE)에서 오류 없이 끝난 호출만 판정한다.
실행 점검 P1~P5는 평가가 의도대로 실행됐는지 본다: 호출 경로, 문서·질문이 프롬프트에 들어갔는지,
채점 정보가 새지 않았는지, 프롬프트가 num_ctx를 넘지 않았는지.
모델별 집계는 모델 설정의 비교 이름(model_name)으로 묶는다.
"""

import json
import re
import statistics

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .run import ANSWER_ROUTE, GRADING_FIELDS

CODE, JUDGE = "code", "judge"
# 1장 지침: 키 → (지침, 판정 주체). 보고서도 이 순서로 쓴다
GUIDELINES = {
    "json_format": ("출력 형식을 JSON으로 준다", CODE),
    "company_data_only": ("답은 회사 데이터 안에서 알 수 있는 정보로만 준다", JUDGE),
    "tone_template": ("응대 말투와 상황별 안내 템플릿 가이드라인을 따른다", JUDGE),
    "answers_question": ("질문에 답한다", JUDGE),
    "document_titles": ("근거 문서의 제목을 밝힌다", CODE),
    "no_false_completion": ("신청·변경·조회를 처리한 것처럼 말하지 않는다", JUDGE),
    "korean_only": ("한국어로만 답한다", CODE),
    "no_long_copy": ("문서를 길게 베끼지 않고 질문에 맞게 요약한다", CODE),
}
CODE_GUIDELINES = tuple(k for k, (_, by) in GUIDELINES.items() if by == CODE)
JUDGE_GUIDELINES = tuple(k for k, (_, by) in GUIDELINES.items() if by == JUDGE)
PROMPT_CODES = ("P1", "P2", "P3", "P4", "P5")
HANDLING_LABELS = {"llm": "LLM 문서 답변", "fixed": "LLM 없는 안내"}

# 호출 결과 (2장 호출 실패율). 시간 초과는 예외 이름으로 가린다 (ReadTimeout, APITimeoutError 등)
FAILURE_STATUSES = ("error", "timeout", "empty")
TIMEOUT_PATTERN = re.compile(r"time\s*out", re.IGNORECASE)

# 베끼기 기준 길이 (공백을 하나로 줄인 글자 수). 1장대로 테스트하면서 정하고 --copy-limit으로 바꾼다
COPY_LIMIT_CHARS = 100
# 영어 문장: 라틴 문자 단어가 이만큼 이어지면 문장으로 본다 (메뉴·제품 이름은 보통 이보다 짧다)
ENGLISH_RUN_WORDS = 5
URL_PATTERN = re.compile(
    r"(?:https?://|www\.)\S+|\S+\.(?:com|co\.kr|kr|net|org|io)(?:/\S*)?", re.IGNORECASE
)
FOREIGN_SCRIPT = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+")
ENGLISH_RUN = re.compile(
    rf"[A-Za-z][A-Za-z'-]*(?:[\s,.:;!?()]+[A-Za-z][A-Za-z'-]*){{{ENGLISH_RUN_WORDS - 1},}}"
)
DETAIL_CHARS = 60


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


def check(code, ok, detail=""):
    return {"code": code, "ok": ok, "detail": detail}


def not_applicable(codes, reason):
    return [check(code, None, reason) for code in codes]


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
        p1 = check("P1", None, "모델 호출 전에 실행기 오류 (호출 실패로 집계)")
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


def squash(text):
    return re.sub(r"\s+", " ", text or "").strip()


def short(text, limit=DETAIL_CHARS):
    return text if len(text) <= limit else text[:limit] + "…"


def structured_payload(record):
    """현재 생성기의 구조화 응답(answer·referenced_documents·note). 없거나 깨졌으면 None."""
    structured = record.get("structured_response")
    try:
        if structured is not None:
            return StructuredAnswerPayload.model_validate(structured)
        return StructuredAnswerPayload.model_validate_json(
            record.get("response_text") or ""
        )
    except ValidationError:
        return None


def call_status(record):
    """호출 결과: "answered"(답변 있음), "empty"(빈 답변), "timeout", "error".

    구조화 응답이면 answer가 비었는지 보고, 아니면 응답 원문이 비었는지 본다.
    """
    error = record.get("error")
    if error:
        return "timeout" if TIMEOUT_PATTERN.search(error) else "error"
    payload = structured_payload(record)
    text = payload.answer if payload else answer_text(record)
    return "answered" if text.strip() else "empty"


def guideline_target(record):
    """지침 판정 대상: 문서 답변 경로에서 오류·시간 초과 없이 끝난 호출 (빈 답변 포함)."""
    return record.get("expected_route") == ANSWER_ROUTE and call_status(record) in (
        "answered",
        "empty",
    )


def verdict(ok, detail=""):
    return {"ok": ok, "detail": detail}


def named_titles(record, text):
    """답변이 밝힌 문서 제목: 구조화 응답의 referenced_documents와 답변 본문에 나온 회사 문서 제목."""
    payload = structured_payload(record)
    named = {squash(t) for t in payload.referenced_documents} if payload else set()
    named |= {
        doc["title"]
        for doc in record.get("evidence") or []
        if doc.get("title") and doc["title"] in text
    }
    return named - {""}


def title_check(record, text):
    """밝힌 문서 제목이 정답 근거 문서와 맞는가: 정답 문서 제목이 있고, 없는 문서 제목은 없어야 한다."""
    expected = record.get("expected_document_ids")
    if not expected:
        reason = "정답 문서 미지정" if expected is None else "근거 문서가 없는 질문"
        return verdict(None, reason)
    titles = {doc["document_id"]: doc["title"] for doc in record.get("evidence") or []}
    wanted = {titles[i] for i in expected if i in titles}
    named = named_titles(record, text)
    if not named:
        return verdict(False, "밝힌 문서 제목 없음")
    unknown = sorted(named - set(titles.values()))
    if unknown:
        return verdict(False, f"회사 문서에 없는 제목: {', '.join(unknown)}")
    if not named & wanted:
        return verdict(
            False, f"정답 문서 제목이 없음 (밝힌 제목: {', '.join(sorted(named))})"
        )
    return verdict(True)


def korean_check(record, text):
    """중국어·일본어 문자나 영어 문장이 섞였는가. 주소와 회사 문서 제목은 빼고 본다."""
    rest = URL_PATTERN.sub(" ", text)
    for doc in record.get("evidence") or []:
        if doc.get("title"):
            rest = rest.replace(doc["title"], " ")
    found = FOREIGN_SCRIPT.findall(rest)
    found += [match.group(0) for match in ENGLISH_RUN.finditer(rest)]
    if not found:
        return verdict(True)
    return verdict(False, f"다른 언어: {short(' / '.join(found))}")


def longest_copy(text, sources):
    """답변과 문서가 그대로 겹치는 가장 긴 부분 (글자 수, 그 부분). 주소는 빼고, 공백은 하나로 본다.

    문서 경계를 넘는 겹침은 세지 않는다. 시작 위치마다 지금까지 찾은 길이보다 긴 겹침만 찾는다.
    """
    answer = squash(URL_PATTERN.sub(" ", text))
    corpus = "\0".join(squash(source) for source in sources)
    best, start = 0, 0
    for i in range(len(answer)):
        while i + best < len(answer) and answer[i : i + best + 1] in corpus:
            best += 1
            start = i
    return best, answer[start : start + best]


def copy_check(record, text, limit):
    sources = [doc["text"] for doc in record.get("evidence") or []]
    length, part = longest_copy(text, sources)
    if length < limit:
        return verdict(True, f"가장 긴 겹침 {length}자"), length
    return verdict(False, f"문서와 {length}자 그대로 겹침: {short(part)}"), length


def code_checks(record, copy_limit=COPY_LIMIT_CHARS):
    """코드가 판정하는 지침 4개와 가장 긴 겹침 길이. 판정 대상이 아니면 ({}, None).

    빈 답변은 JSON 형식만 판정한다 (빈 answer는 형식 실패).
    """
    if not guideline_target(record):
        return {}, None
    valid = record_payload(record) is not None
    results = {"json_format": verdict(valid, "" if valid else "JSON 형식이 아님")}
    if call_status(record) == "empty":
        empty = verdict(None, "빈 답변")
        return {**results, **{k: empty for k in CODE_GUIDELINES[1:]}}, None
    text = answer_text(record)
    results["document_titles"] = title_check(record, text)
    results["korean_only"] = korean_check(record, text)
    results["no_long_copy"], overlap = copy_check(record, text, copy_limit)
    return {key: results[key] for key in CODE_GUIDELINES}, overlap


def evaluate_record(record, copy_limit=COPY_LIMIT_CHARS):
    run_checks = prompt_checks(record)
    guidelines, overlap = code_checks(record, copy_limit)
    return {
        "case_id": record["case_id"],
        "model_name": record["model_name"],
        "repeat": record["repeat"],
        "status": call_status(record),
        "run_checks": run_checks,
        "run_failed": [c["code"] for c in run_checks if c["ok"] is False],
        "guidelines": guidelines,
        "copy_overlap": overlap,
    }


def evaluate_records(records, copy_limit=COPY_LIMIT_CHARS):
    return [evaluate_record(record, copy_limit) for record in records]


def measure(records):
    """응답 시간·토큰 실측값. 오류 없는 호출만 세고, 지연 평균·중앙값·최대는 첫 호출(cold start)을 뺀다."""
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
    """보고용 집계. 실행 점검은 질문 단위, 2장 추가 비교는 모델별 문서 답변 경로 호출 단위로 센다."""
    cases = sorted({r["case_id"] for r in records})

    prompt_summary = {}
    for code in PROMPT_CODES:
        counts = {"pass": 0, "fail": 0, "n/a": 0}
        for case_id in cases:
            values = [
                c["ok"]
                for e in evaluations
                if e["case_id"] == case_id
                for c in e["run_checks"]
                if c["code"] == code and c["ok"] is not None
            ]
            key = "n/a" if not values else ("pass" if all(values) else "fail")
            counts[key] += 1
        prompt_summary[code] = counts

    models = {}
    for name in sorted({r["model_name"] for r in records}):
        pairs = [
            (r, e)
            for r, e in zip(records, evaluations)
            if r["model_name"] == name and r.get("expected_route") == ANSWER_ROUTE
        ]
        if not pairs:
            continue
        subset = [r for r, _ in pairs]
        statuses = {
            s: sum(e["status"] == s for _, e in pairs) for s in FAILURE_STATUSES
        }
        lengths = [len(answer_text(r)) for r, e in pairs if e["status"] == "answered"]
        overlaps = [
            e["copy_overlap"] for _, e in pairs if e["copy_overlap"] is not None
        ]
        models[name] = {
            "provider": subset[0]["provider"],
            "model": subset[0].get("model"),
            "served_models": sorted(
                {r["served_model"] for r in subset if r.get("served_model")}
            ),
            "calls": len(subset),
            "failures": statuses,
            "failure_rate": sum(statuses.values()) / len(subset),
            # 오류 없이 끝났지만 출력 토큰 한도에 걸려 잘린 호출
            "truncated": sum(
                not r.get("error") and r.get("finish_reason") == "length"
                for r in subset
            ),
            "answer_length_mean": statistics.fmean(lengths) if lengths else None,
            "copy_overlap_max": max(overlaps) if overlaps else None,
            "measured": measure(subset),
        }

    return {
        "records": len(records),
        "cases": len(cases),
        "prompt_checks": prompt_summary,
        "models": models,
        "no_llm_records": sum(not r.get("llm_called") for r in records),
        "wrong_route_cases": sorted(
            {e["case_id"] for e in evaluations if "P1" in e["run_failed"]}
        ),
        "document_problem_cases": sorted(
            {r["case_id"] for r in records if document_problems(r)}
        ),
    }
