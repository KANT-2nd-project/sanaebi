"""심판 LLM이 지침 4개를 판정한다 (docs/generation-evaluation.md 1장).

판정 대상은 지침 판정 대상 중 답변이 빈 칸이 아닌 기록이다. 심판에게는 모델 이름을 주지 않고,
모델이 실제로 받은 지침(프롬프트에서 문서 데이터 앞부분), 질문, 답변, 참고 문서를 준다.
참고 문서는 정답 근거 문서와 답변이 제목을 밝힌 문서만 발췌한다 (회사 문서 전체는 너무 길다).
지침마다 통과·실패와 이유를 받아 run_dir/judge.jsonl에 한 줄씩 쌓는다.
다시 실행하면 판정이 없는 기록만 부른다. 심판 호출은 요금이 발생한다.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .checks import (
    GUIDELINES,
    JUDGE_GUIDELINES,
    answer_text,
    call_status,
    guideline_target,
    named_titles,
)
from .run import read_jsonl, record_key

JUDGE_NAME = "judge.jsonl"
DEFAULT_JUDGE_MODEL = "gpt-5.6-luna"
JUDGE_TIMEOUT_SECONDS = 120
JUDGE_WORKERS = 4
# 실행기 프롬프트에서 회사 문서가 시작하는 곳. 그 앞이 모델이 받은 지침과 질문이다
DOCUMENT_MARKER = "<문서 데이터"

# 지침마다 심판이 확인할 것 (1장 "확인할 것")
CRITERIA = {
    "company_data_only": (
        "준 정보 외에 다른 정보를 유추하거나, 모델이 원래 알던 정보로 안내하지 않았는가. "
        "<참고 문서>에 없는 규정·날짜·기한·금액·담당자·절차를 말하면 실패다."
    ),
    "tone_template": "말투와 상황별 안내를 <응대 지침>대로 했는가.",
    "answers_question": (
        "질문에 필요한 핵심 정보를 빠짐없이 답했는가. "
        "정답 근거 문서가 없는 질문이면, 자료가 없다고 밝힌 답을 통과로 본다."
    ),
    "no_false_completion": "처리하지 않은 일을 처리했다고 말하지 않았는가.",
}

PROMPT = """당신은 사내 문의 도우미의 답변이 지침을 지켰는지 판정하는 평가자입니다.
아래 기준으로만 엄격하고 일관되게 판정하세요.

판정할 지침 (지침마다 통과 또는 실패)
{criteria}

<참고 문서>는 회사 문서 중 정답 근거 문서와 답변이 제목을 밝힌 문서만 발췌했습니다.
답변이 발췌에 없는 내용을 말하면 회사 데이터로 확인할 수 없는 정보로 봅니다.
<핵심 정보>와 <하면 안 되는 주장>은 평가 세트에 적어 둔 참고 정보이며, 비어 있을 수 있습니다.

<응대 지침>
{instructions}
</응대 지침>

<질문>
{question}
</질문>

<정답 근거 문서>
{expected}
</정답 근거 문서>

<핵심 정보>
{required}
</핵심 정보>

<하면 안 되는 주장>
{forbidden}
</하면 안 되는 주장>

<참고 문서>
{documents}
</참고 문서>

<판정할 답변>
{answer}
</판정할 답변>

JSON 객체 하나만 출력하세요. 지침마다 {{"passed": true 또는 false, "reason": "판정 이유를 한국어 한 문장으로"}}를 넣습니다.
{{{keys}}}"""


class Verdict(BaseModel):
    passed: bool
    reason: str


class JudgeResult(BaseModel):
    """심판 응답. 필드는 JUDGE_GUIDELINES와 같다."""

    model_config = ConfigDict(extra="ignore")
    company_data_only: Verdict
    tone_template: Verdict
    answers_question: Verdict
    no_false_completion: Verdict


def judge_targets(records):
    """심판 판정 대상: 지침 판정 대상이면서 답변이 빈 칸이 아닌 기록."""
    return [r for r in records if guideline_target(r) and call_status(r) == "answered"]


def model_instructions(record):
    """모델이 받은 지침: 실제 프롬프트에서 문서 데이터 앞부분. 표시가 없으면 문서 본문을 지운 프롬프트."""
    prompt = record.get("prompt") or ""
    head, marker, _ = prompt.partition(DOCUMENT_MARKER)
    if marker:
        return head.strip()
    for doc in record.get("evidence") or []:
        prompt = prompt.replace(doc["text"], "")
    return prompt.strip()


def expected_text(record):
    expected = record.get("expected_document_ids")
    if expected is None:
        return "(평가 세트에 지정하지 않음)"
    if not expected:
        return "(없음: 회사 문서에 답이 없는 질문)"
    titles = {doc["document_id"]: doc["title"] for doc in record.get("evidence") or []}
    return "\n".join(titles.get(i, f"(문서 {i})") for i in expected)


def reference_documents(record, text):
    """정답 근거 문서와 답변이 제목을 밝힌 문서의 제목·본문."""
    expected = set(record.get("expected_document_ids") or [])
    named = named_titles(record, text)
    picked = [
        doc
        for doc in record.get("evidence") or []
        if doc["document_id"] in expected or doc["title"] in named
    ]
    if not picked:
        return "(발췌한 문서 없음)"
    return "\n\n".join(f"제목: {doc['title']}\n{doc['text']}" for doc in picked)


def build_prompt(record):
    text = answer_text(record)
    criteria = "\n".join(
        f"- {key} ({GUIDELINES[key][0]}): {CRITERIA[key]}" for key in JUDGE_GUIDELINES
    )
    keys = ", ".join(f'"{key}": {{...}}' for key in JUDGE_GUIDELINES)
    return PROMPT.format(
        criteria=criteria,
        instructions=model_instructions(record) or "(기록 없음)",
        question=record["question"],
        expected=expected_text(record),
        required="\n".join(record.get("required_points") or []) or "(없음)",
        forbidden="\n".join(record.get("forbidden_claims") or []) or "(없음)",
        documents=reference_documents(record, text),
        answer=text,
        keys=keys,
    )


def openai_judge(model):
    """OpenAI 심판. prompt → 응답 JSON(dict). temperature는 모델 기본값을 쓴다."""
    from langchain_openai import ChatOpenAI

    chat = ChatOpenAI(model=model, timeout=JUDGE_TIMEOUT_SECONDS, max_retries=0).bind(
        response_format={"type": "json_object"}
    )

    def invoke(prompt):
        return json.loads(chat.invoke(prompt).text)

    return invoke


def judge_record(record, invoke, attempts=2):
    """기록 1개를 판정한다. {지침: {"ok", "reason"}}. 응답이 형식에 맞지 않으면 한 번 더 부른다."""
    prompt = build_prompt(record)
    error = None
    for _ in range(attempts):
        try:
            result = JudgeResult.model_validate(invoke(prompt))
        except Exception as exc:  # noqa: BLE001 - 다시 부르고, 끝내 실패하면 종류만 남긴다
            error = exc
            continue
        return {
            key: {
                "ok": getattr(result, key).passed,
                "reason": getattr(result, key).reason.strip(),
            }
            for key in JUDGE_GUIDELINES
        }
    # 예외 원문에는 비밀값이 섞일 수 있어 종류만 남긴다
    raise RuntimeError(f"심판 판정 실패 ({type(error).__name__})")


def load_judgments(run_dir):
    """{(case_id, model_name, repeat): 판정 행}. 파일이 없으면 빈 딕셔너리."""
    path = Path(run_dir) / JUDGE_NAME
    if not path.exists():
        return {}
    return {record_key(row): row for row in read_jsonl(path)}


def run_judge(records, run_dir, invoke, judge_model, log=print, workers=JUDGE_WORKERS):
    """판정이 없는 대상만 심판에게 보내고 끝나는 대로 judge.jsonl에 더한다.

    돌려주는 값: {"targets", "judged", "failed"} (judged = 이번에 판정한 수)
    """
    done = load_judgments(run_dir)
    targets = judge_targets(records)
    todo = [r for r in targets if record_key(r) not in done]
    judged = failed = 0
    path = Path(run_dir) / JUDGE_NAME
    with (
        path.open("a", encoding="utf-8") as stream,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        futures = {pool.submit(judge_record, r, invoke): r for r in todo}
        for future in as_completed(futures):
            record = futures[future]
            try:
                verdicts = future.result()
            except RuntimeError as exc:
                failed += 1
                log(
                    f"  [실패] {record['case_id']} · {record['model_name']} · "
                    f"{record['repeat']}회차: {exc}"
                )
                continue
            row = {
                "case_id": record["case_id"],
                "model_name": record["model_name"],
                "repeat": record["repeat"],
                "judge_model": judge_model,
                "verdicts": verdicts,
            }
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            judged += 1
    return {"targets": len(targets), "judged": judged, "failed": failed}
