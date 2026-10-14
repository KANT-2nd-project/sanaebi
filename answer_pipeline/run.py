"""평가 세트의 같은 질문을 main의 LangChain 실행기로 모델마다 실행해 기록을 남긴다.

실행기의 체인(sanaebi_assistant.create_chain)을 그대로 부른다. 프롬프트·문서·출력 처리는
실행기가 정하고, 여기서는 LangChain 콜백으로 실제 프롬프트, 모델 원문 응답, 토큰 수,
종료 사유, 응답 모델 이름을 받아 기록만 한다. 답변을 고치거나 재시도하지 않는다.
생성 답변을 평가하므로 분류 라벨은 평가 세트의 정답 경로(expected_route)를 고정 입력으로 넘긴다.

모델 설정 파일 (JSON 목록, 한 항목 = 비교할 모델 1개, 예시는 examples/models.example.json):
  name, provider(ollama|openai), model, base_url, temperature, num_ctx, max_output_tokens,
  timeout_seconds. 값을 비우면 실행기 기본값을 쓴다. API 키는 이 파일에 넣지 않는다.
실행기는 아직 모델 설정을 인자로 받지 않아, 호출하는 동안만 실행기의 모듈 상수를 바꿔 둔다
(executor_settings). 시간 제한은 두 모델이 같은 상수를 쓴다. 실행기가 받지 않는 설정
(OpenAI temperature·num_ctx·base_url)은 막는다. OpenAI 모델은 temperature 기본값만 받는다.
"""

import contextlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

import sanaebi_assistant as assistant
from contracts.classification import LABELS, SEARCH_KNOWLEDGE

# 요청 처리 분류기의 세 경로 (docs/service-architecture.md "질문 처리 라벨 세 가지")
ROUTES = LABELS
# 회사 문서로 LLM 답변을 시도하는 경로. 나머지는 되묻기·지원 범위 안내다
ANSWER_ROUTE = SEARCH_KNOWLEDGE
# 평가 세트 구분: 개발용(프롬프트·코드 조정)과 최종 비교용(조정 금지)
SPLITS = ("dev", "final")
# 채점에만 쓰고 실행기에는 넘기지 않는 필드 (P4 누출 점검 대상)
GRADING_FIELDS = (
    "expected_route",
    "expected_document_ids",
    "required_points",
    "forbidden_claims",
)
# 평가 세트에 적어 두는 태그. 평가 축이 아니다
TAG_FIELDS = ("topic", "question_type", "evidence_position")
EVAL_FIELDS = ("id", "question", "split", "note", *GRADING_FIELDS, *TAG_FIELDS)
# 질문 형식 태그
QUESTION_TYPES = (
    "answerable",
    "partial",
    "no_evidence",
    "mixed",
    "situational",
    "conflict",
    "injection",
)
EVIDENCE_POSITIONS = ("front", "middle", "back")

PROVIDERS = ("ollama", "openai")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# 설정 항목 → 실행기 모듈 상수. 없는 항목은 실행기가 그 설정을 받지 않는다는 뜻이다
EXECUTOR_CONSTANTS = {
    "ollama": {
        "model": "OLLAMA_MODEL",
        "base_url": "OLLAMA_URL",
        "temperature": "OLLAMA_TEMPERATURE",
        "num_ctx": "OLLAMA_NUM_CTX",
        "max_output_tokens": "OLLAMA_NUM_PREDICT",
        "timeout_seconds": "TIMEOUT",
    },
    "openai": {
        "model": "OPENAI_MODEL",
        "timeout_seconds": "TIMEOUT",
        "max_output_tokens": "OPENAI_MAX_TOKENS",
    },
}
# 실행 조건에 함께 남길 고정값 (설정으로 바꿀 수 없음)
EXECUTOR_FIXED = {
    "ollama": {"api": "langchain_ollama.ChatOllama", "max_retries": "MAX_RETRIES"},
    "openai": {"api": "langchain_openai.ChatOpenAI", "max_retries": "MAX_RETRIES"},
}


# --- 기록 파일 ---


def read_jsonl(path):
    rows = []
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path} {number}번째 줄이 JSON이 아닙니다: {exc.msg}"
            ) from exc
    return rows


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as stream:
        stream.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def record_key(record):
    """실행 기록 1개를 가리키는 키: (질문 id, 비교 모델 이름, 반복 번호)."""
    return (record["case_id"], record["model_name"], int(record["repeat"]))


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def text_list(raw, field, case_id):
    """문자열 목록 필드를 읽는다. 없으면 빈 목록."""
    values = raw.get(field) or []
    if not isinstance(values, list) or not all(is_text(v) for v in values):
        raise ValueError(f"{case_id}: {field}는 문자열 목록이어야 합니다.")
    return list(values)


# --- 모델 설정 ---


@dataclass(frozen=True)
class ModelConfig:
    name: str
    provider: str
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    num_ctx: int | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None


def parse_model_configs(rows, source="모델 설정"):
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{source}: 모델 설정은 1개 이상의 객체 목록이어야 합니다.")
    fields = set(ModelConfig.__dataclass_fields__)
    configs, names = [], set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise TypeError(f"{source}: 모델 설정 항목은 객체여야 합니다: {raw!r}")
        unknown = sorted(set(raw) - fields)
        if unknown:
            raise ValueError(f"{source}: 모르는 설정 항목입니다: {unknown}")
        name = raw.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise ValueError(
                f"{source}: name은 영문·숫자·._-로 쓴 비교 이름이어야 합니다: {name!r}"
            )
        if name in names:
            raise ValueError(f"{source}: name이 겹칩니다: {name}")
        names.add(name)
        provider = raw.get("provider")
        if provider not in PROVIDERS:
            raise ValueError(
                f"{name}: provider는 {PROVIDERS} 중 하나여야 합니다: {provider!r}"
            )
        config = ModelConfig(**raw)
        unsupported = [
            field
            for field, value in asdict(config).items()
            if value is not None
            and field not in ("name", "provider")
            and field not in EXECUTOR_CONSTANTS[provider]
        ]
        if unsupported:
            raise ValueError(
                f"{name}: 실행기가 {provider}에 적용하지 않는 설정입니다: {unsupported}. "
                "실행기에 설정 인자가 생기기 전까지는 비워 둡니다."
            )
        configs.append(config)
    return configs


def load_model_configs(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return parse_model_configs(rows, str(path))


@contextlib.contextmanager
def executor_settings(config):
    """호출하는 동안만 실행기 모듈 상수를 설정 값으로 바꾸고, 끝나면 되돌린다."""
    constants = EXECUTOR_CONSTANTS[config.provider]
    saved = {name: getattr(assistant, name) for name in constants.values()}
    try:
        for field, name in constants.items():
            value = getattr(config, field)
            if value is not None:
                setattr(assistant, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(assistant, name, value)


def applied_conditions(config):
    """실행기가 실제로 쓰는 호출 조건 (설정 값 + 실행기 기본값). 실행 기록에 남긴다."""
    with executor_settings(config):
        values = {
            field: getattr(assistant, name)
            for field, name in EXECUTOR_CONSTANTS[config.provider].items()
        }
        fixed = {
            key: getattr(assistant, value) if value.isupper() else value
            for key, value in EXECUTOR_FIXED[config.provider].items()
        }
    # 실행기가 정하지 않는 값은 모델·라이브러리 기본값이다
    values.setdefault("temperature", None)
    values.setdefault("num_ctx", None)
    values["max_input_chars"] = assistant.MAX_INPUT_CHARS
    return {"name": config.name, "provider": config.provider, **values, **fixed}


# --- 평가 세트와 회사 문서 ---


def load_documents(path=None):
    """실행기가 읽는 회사 문서 JSONL({"title", "document"})을 {document_id: {"title", "text"}}로 읽는다.

    명시 ID가 전혀 없는 구형 파일은 파일 안 순번(빈 줄 제외, 1부터)을 사용한다.
    명시 ID가 있으면 모든 ID가 비어 있지 않고 고유한 문자열이어야 한다.
    본문은 실행기와 같은 normalize_text로 정리해 프롬프트에 들어간 글자와 맞춘다.
    """
    path = Path(path or assistant.DOCUMENTS_PATH)
    rows = read_jsonl(path)
    documents = {}
    has_explicit_ids = [isinstance(row, dict) and "document_id" in row for row in rows]
    if any(has_explicit_ids) and not all(has_explicit_ids):
        raise ValueError(
            f"{path}: document_id가 있는 문서와 없는 문서를 섞을 수 없습니다."
        )
    for number, row in enumerate(rows, start=1):
        if (
            not isinstance(row, dict)
            or not is_text(row.get("title"))
            or not is_text(row.get("document"))
        ):
            raise ValueError(f"{path} {number}번째 문서에 title·document가 없습니다.")
        has_id = "document_id" in row
        if has_id:
            document_id = row["document_id"]
            if not is_text(document_id):
                raise ValueError(
                    f"{path} {number}번째 문서의 document_id는 비어 있지 않은 문자열이어야 합니다."
                )
        else:
            document_id = str(number)
        if document_id in documents:
            raise ValueError(f"{path} {number}번째 문서의 document_id가 중복됩니다.")
        documents[document_id] = {
            "title": assistant.normalize_text(row["title"]),
            "text": assistant.normalize_text(row["document"]),
        }
    if not documents:
        raise ValueError(f"회사 문서가 없습니다: {path}")
    return documents


def load_eval_set(path, max_input_chars=None):
    """평가 세트 JSONL을 읽고 형식을 검사한다. 모르는 필드는 오타로 보고 막는다."""
    max_input_chars = max_input_chars or assistant.MAX_INPUT_CHARS
    rows, seen = [], set()
    for raw in read_jsonl(path):
        case_id = str(raw.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"id가 비었거나 겹칩니다: {case_id!r}")
        seen.add(case_id)
        unknown = sorted(set(raw) - set(EVAL_FIELDS))
        if unknown:
            raise ValueError(f"{case_id}: 평가 세트에 없는 필드입니다: {unknown}")
        if not is_text(raw.get("question")):
            raise ValueError(f"{case_id}: question이 비었습니다.")
        if len(raw["question"].strip()) > max_input_chars:
            raise ValueError(f"{case_id}: question이 {max_input_chars}자를 넘습니다.")
        for field, allowed, required in (
            ("split", SPLITS, True),
            ("expected_route", ROUTES, False),
            ("question_type", QUESTION_TYPES, False),
            ("evidence_position", EVIDENCE_POSITIONS, False),
        ):
            value = raw.get(field)
            if (required or value is not None) and value not in allowed:
                raise ValueError(
                    f"{case_id}: {field}는 {allowed} 중 하나여야 합니다: {value!r}"
                )
        topic = raw.get("topic")
        if topic is not None and not is_text(topic):
            raise ValueError(f"{case_id}: topic은 문자열이어야 합니다.")
        expected_ids = raw.get("expected_document_ids")
        rows.append(
            {
                "id": case_id,
                "question": raw["question"].strip(),
                "split": raw["split"],
                "expected_route": raw.get("expected_route"),
                "expected_document_ids": None
                if expected_ids is None
                else text_list(raw, "expected_document_ids", case_id),
                "required_points": text_list(raw, "required_points", case_id),
                "forbidden_claims": text_list(raw, "forbidden_claims", case_id),
                **{field: raw.get(field) for field in TAG_FIELDS},
                "note": raw.get("note") or "",
            }
        )
    if not rows:
        raise ValueError(f"평가 질문이 없습니다: {path}")
    return rows


def check_eval_set(rows, documents):
    """정답 정보를 회사 문서와 대조한다. (오류 목록, 경고 목록)을 돌려준다.

    오류: 실행하거나 채점할 수 없게 되는 문제 (정답 경로 없음, 없는 문서, 문서에 없는 핵심 표현,
         모순된 정답)
    경고: 판정이 빠지거나 약해지는 빈 칸
    """
    errors, warnings = [], []
    for row in rows:
        case_id = row["id"]
        expected_ids = row["expected_document_ids"]
        route = row["expected_route"]

        if route is None:
            errors.append(f"{case_id}: expected_route가 없어 실행기에 넘길 경로가 없음")
        unknown = [i for i in expected_ids or [] if i not in documents]
        if unknown:
            errors.append(f"{case_id}: 회사 문서에 없는 document_id {unknown}")
        known = [documents[i]["text"] for i in expected_ids or [] if i in documents]
        if known:
            absent = [
                p
                for p in row["required_points"]
                if not any(p in text for text in known)
            ]
            if absent:
                errors.append(
                    f"{case_id}: required_points {absent}가 정답 근거 문서에 없음"
                )
        if route is not None and route != ANSWER_ROUTE and expected_ids:
            errors.append(
                f"{case_id}: {route} 경로인데 정답 근거 문서가 있음 {expected_ids}"
            )

        if route == ANSWER_ROUTE:
            if expected_ids is None:
                warnings.append(
                    f"{case_id}: expected_document_ids가 없어 근거 문서 제목 지침을 판정하지 않음"
                )
            if not row["required_points"]:
                warnings.append(
                    f"{case_id}: required_points가 없어 심판이 핵심 정보 목록 없이 판정함"
                )
    return errors, warnings


# --- 실행 ---


class CallCapture(BaseCallbackHandler):
    """체인 안의 모델 호출 1번을 기록한다 (프롬프트, 원문 응답, 사용량, 종료 사유)."""

    def __init__(self):
        self.prompt = None
        self.raw_text = None
        self.structured_response = None
        self.usage = {"input_tokens": None, "output_tokens": None}
        self.finish_reason = None
        self.served_model = None
        self.llm_calls = 0

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.llm_calls += 1
        self.prompt = "\n".join(str(message.content) for message in messages[0])

    def on_llm_end(self, response, **kwargs):
        generation = response.generations[0][0]
        self.raw_text = generation.text
        message = getattr(generation, "message", None)
        tool_calls = getattr(message, "tool_calls", None) or []
        if len(tool_calls) == 1 and tool_calls[0].get("name") == "AssistantResponse":
            self.structured_response = tool_calls[0].get("args")
        usage = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}
        # 사용량이 없으면 0이 아니라 알 수 없음(None)으로 남긴다
        self.usage = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
        # Ollama는 done_reason, OpenAI는 finish_reason으로 끝난 이유를 준다
        self.finish_reason = metadata.get("done_reason") or metadata.get(
            "finish_reason"
        )
        self.served_model = metadata.get("model_name") or metadata.get("model")


def executor_request(case):
    """실행기 입력 규약(AssistantRequest)대로 질문과 고정 경로를 넘긴다. 정답 정보는 넣지 않는다."""
    return {
        "response": {"ok": True, "text": case["question"], "reason": ""},
        "classification_label": case["expected_route"],
    }


def invoke_executor(config, request, capture, documents_path=None):
    with executor_settings(config):
        chain = (
            assistant.create_chain(config.provider)
            if documents_path is None
            else assistant.create_chain(config.provider, documents_path=documents_path)
        )
        return chain.invoke(request, config={"callbacks": [capture]})


def run_case(case, config, invoke=invoke_executor, documents_path=None):
    """질문 1건 × 모델 1개 × 1회. 실패도 기록으로 남기고 예외를 밖으로 던지지 않는다."""
    capture = CallCapture()
    output, error = None, None
    started = time.perf_counter()
    try:
        if documents_path is None:
            output = invoke(config, executor_request(case), capture)
        else:
            output = invoke(
                config,
                executor_request(case),
                capture,
                documents_path=documents_path,
            )
    except Exception as exc:  # noqa: BLE001 - 실패도 기록으로 남기고 다음 호출을 계속한다
        # 예외 원문에는 비밀값이 섞일 수 있어 종류만 남긴다
        error = type(exc).__name__
    latency = time.perf_counter() - started
    # 모델은 답했는데 체인이 그 출력을 풀다 멈춘 예외는 호출 오류(A1)가 아니라 출력 정리 오류로 따로 남긴다.
    # 잘림(A2)과 형식(A3)은 모델 원문으로 판정한다
    output_error = None
    if error is not None and capture.raw_text is not None:
        error, output_error = None, error
    finish_reason = capture.finish_reason or ("error" if error else None)
    return {
        "llm_called": capture.llm_calls > 0,
        "prompt": capture.prompt,
        "response_text": capture.raw_text or "",
        "structured_response": capture.structured_response,
        "executor_output": output,
        "usage": capture.usage,
        "generation_complete": error is None
        and capture.raw_text is not None
        and finish_reason not in (None, "length"),
        "finish_reason": finish_reason,
        "served_model": capture.served_model,
        "latency_seconds": latency,
        "error": error,
        "output_error": output_error,
    }


def make_record(case, config, conditions, repeat, result, documents, cold_start):
    """실행 기록 1개. 평가 세트 정보 + 실행 조건 + 호출 결과."""
    route = case["expected_route"]
    # 실행기는 SEARCH_KNOWLEDGE일 때만 회사 문서 전체를 프롬프트에 넣는다
    evidence = (
        [{"document_id": i, **doc} for i, doc in documents.items()]
        if route == ANSWER_ROUTE
        else []
    )
    return {
        "case_id": case["id"],
        "question": case["question"],
        "expected_route": route,
        "evidence": evidence,
        "expected_document_ids": case["expected_document_ids"],
        "required_points": case["required_points"],
        "forbidden_claims": case["forbidden_claims"],
        "split": case["split"],
        **{field: case.get(field) for field in TAG_FIELDS},
        "repeat": repeat,
        "model_name": config.name,
        "provider": config.provider,
        "model": conditions.get("model"),
        "limits": {
            "num_ctx": conditions.get("num_ctx"),
            "max_output_tokens": conditions.get("max_output_tokens"),
        },
        **result,
        "cold_start": cold_start,
    }


def run_comparison(
    cases,
    run_dir,
    configs,
    repeats,
    documents,
    run_fn=run_case,
    log=print,
    documents_path=None,
):
    """질문 × 반복 × 모델을 실행해 run_dir/results.jsonl에 한 줄씩 기록한다.

    - 같은 질문을 모든 모델에 같은 입력으로 보낸다 (공정 비교).
    - 모델별 첫 호출은 cold_start로 표시한다 (Ollama 모델 로딩 시간).
    - 호출 하나가 끝날 때마다 저장한다. 중간에 멈춰도 끝난 기록은 남는다.
    """
    run_dir = Path(run_dir)
    results_path = run_dir / "results.jsonl"
    if results_path.exists():
        raise FileExistsError(
            f"이미 실행 기록이 있습니다. 다른 --run-dir을 쓰세요: {results_path}"
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    conditions = {config.name: applied_conditions(config) for config in configs}

    records, called = [], set()
    with results_path.open("w", encoding="utf-8") as stream:
        for index, case in enumerate(cases, start=1):
            for repeat in range(1, repeats + 1):
                for config in configs:
                    if documents_path is None:
                        result = run_fn(case, config)
                    else:
                        result = run_fn(case, config, documents_path=documents_path)
                    record = make_record(
                        case,
                        config,
                        conditions[config.name],
                        repeat,
                        result,
                        documents,
                        cold_start=config.name not in called,
                    )
                    called.add(config.name)
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                    records.append(record)
            log(f"{index}/{len(cases)} {case['id']}: 경로 {case['expected_route']}")
    return records
