"""문의 요청을 모델에 전달하고 결과와 실행 메타데이터를 JSONL로 저장합니다.

기본 흐름: 요청 객체 변환 → 질문과 라벨 확인 → 프롬프트 생성 → 모델 호출 →
응답 및 실행 기록 저장.
  라벨은 요청에서 받는 값이며, `call`, `chain`, provider를 병렬 호출하는 `compare` 모드를
명령행에서 선택할 수 있음.
"""

import argparse
import getpass
import json
import os
import re
import sys
import time
import uuid  # 요청 처리마다 uuid.uuid4().hex로 실행 ID를 생성
import warnings  # 요청은 계속 처리하되 자료 문제를 실행 화면에 알림
from collections.abc import Mapping  # 매핑은 키로 값을 찾는 자료형
from datetime import UTC, datetime
from pathlib import Path

import httpx  # HTTP 요청을 보내는 외부 라이브러리
from langchain_core.runnables import RunnableLambda, RunnableParallel
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
INQUIRY_DIR = ROOT / "artifacts" / "step_by_step" / "inquiries"  # 공통 폴더 저장

RESPONSE_PATH = INQUIRY_DIR / "responses.jsonl"
EXECUTION_PATH = INQUIRY_DIR / "execution_records.jsonl"

# [SAMPLE_CASES] 비교 입력 파일이 없는 경우
INPUT_PATH = ROOT / "steps" / "examples" / "inquiries_development.jsonl"
COMPANY_DATABASE_PATH = ROOT / "company_database" / "ieum_works.jsonl"
COMPANY_CATALOG_PATH = ROOT / "company_database" / "required_documents.jsonl"
COMPANY_DATABASE_PATHS = (COMPANY_DATABASE_PATH, COMPANY_CATALOG_PATH)

# 새 모델 실험 결과는 기존 development01 파일과 분리해 저장합니다.
COMPARISON_PATH = INQUIRY_DIR / "comparisons" / "development02" / "results.jsonl"


# 환경 변수

PROVIDER = os.getenv("PROVIDER", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
# 전체 가중치 모델 대신 Ollama에서 실행할 DeepSeek 증류 모델을 기본으로 씁니다.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-r1:8b")
# Kimi 공식 가중치를 Ollama용으로 양자화한 커뮤니티 모델을 사용합니다.
KIMI_MODEL = os.getenv("KIMI_MODEL", "richardyoung/kimi-vl-a3b-thinking")
# API 키 입력은 비교에서 사용하는 OpenAI에만 필요합니다.
API_KEY_ENV = {"openai": "OPENAI_API_KEY"}
# 연결 제한 시간은 초 단위이며, 질문의 길이는 문자 수로 제한합니다.
TIMEOUT = float(os.getenv("GENERATION_TIMEOUT_SECONDS", "600"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "4000"))
# 생성 길이 제한에 걸려 끝난 상태값입니다(Ollama done_reason, OpenAI Responses status).
TRUNCATED_REASONS = {"length", "incomplete"}
# 분류기가 없으므로 라벨을 요청에서 받지 못했을 때 사용할 더미 기본값입니다.
DUMMY_LABEL = "others"

# 라벨별 최소 정책 문구입니다. 이 표는 라벨을 예측하지 않고 프롬프트에 지침만
# 넣습니다. 입력 라벨이 아래 키 중 하나가 아니면 build_prompt에서 거부합니다.
POLICIES = {
    "operating": "조직과 절차는 제공된 근거만 안내합니다.",
    "human_resources": "인사와 복지는 정책에 있는 내용만 안내하고 신청과 승인을 구분합니다.",
    "accounting": "비용과 구매는 정책에 있는 내용만 안내하고 승인과 지급을 단정하지 않습니다.",
    "IT": "계정과 보안은 확인된 절차만 안내하고 인증 정보를 묻지 않습니다.",
    "others": "자료에 없는 정책, 절차, 담당자, 일정을 만들지 않습니다.",
}

# CLI를 인자 없이 실행할 때 사용하는 대표 문의입니다.
SAMPLE_INPUT = {
    "inquiries": "다음 주에 하루 연차를 신청하려고 합니다. 신청 경로와 승인 여부는 어디서 확인하면 되나요."
}
# 비교 입력 파일이 없을 때 사용하는 단일 샘플입니다.
# comparison 결과를 식별할 id와, 이 샘플에 명시적으로 지정할 라벨을 포함합니다.
SAMPLE_CASES = [
    {
        "id": "sample-001",
        "text": SAMPLE_INPUT["inquiries"],
        "classification_label": "human_resources",
    }
]


def payload_dict(value):
    """매핑 또는 Pydantic 요청 객체를 일반 dict로 바꿉니다.

    Pydantic v2의 `model_dump()`를 먼저 시도하고, v1 호환 메서드인 `dict()`를
    다음으로 시도합니다. 반환값도 Mapping이어야 하며, 그 외 입력은 명시적으로
    거부합니다.
    """
    # 이미 매핑이면 얕은 복사본만 만들어 후속 처리에서 원본을 직접 바꾸지 않습니다.
    if isinstance(value, Mapping):
        return dict(value)
    # FastAPI에서 넘어올 수 있는 Pydantic 객체의 버전별 변환 메서드를 확인합니다.
    for name in ("model_dump", "dict"):
        dump = getattr(value, name, None)
        # 이름만 같은 속성이 아니라 실제 호출 가능한 메서드인지 확인합니다.
        if callable(dump):
            payload = dump()
            # 변환 메서드가 Mapping을 반환할 때만 표준 dict로 정규화합니다.
            if isinstance(payload, Mapping):
                return dict(payload)
    # 지원하지 않는 객체를 조용히 빈 요청으로 처리하지 않고 호출자에게 알립니다.
    raise TypeError("요청은 매핑 또는 Pydantic 모델이어야 합니다.")


def question_from(payload):
    """요청에서 질문을 찾아 필수값과 최대 길이를 확인한 뒤 반환합니다."""
    # 여러 입력 형식을 허용하되 inquiries를 가장 먼저, text를 마지막으로 봅니다.
    question = next(
        (payload[key] for key in ("inquiries", "question", "text") if key in payload),
        None,
    )
    # 질문이 문자열이 아니거나 공백뿐이면 모델 호출 전에 입력 오류를 냅니다.
    if not isinstance(question, str) or not question.strip():
        raise ValueError("질문을 입력해야 합니다.")
    # 길이 제한은 공백 제거 전 원문을 기준으로 적용합니다.
    if len(question) > MAX_INPUT_CHARS:
        raise ValueError(f"질문은 {MAX_INPUT_CHARS}자 이하여야 합니다.")
    # 모델에는 앞뒤 공백을 제거한 질문을 전달합니다.
    return question.strip()


def label_from(payload):
    """요청의 라벨을 반환하고, 라벨이 없거나 None이면 더미 라벨을 사용합니다."""
    # Pydantic Optional 필드는 값이 없을 때 None으로 덤프되므로 키 누락과 같게 봅니다.
    label = payload.get("classification_label")
    return DUMMY_LABEL if label is None else label


def read_jsonl(path):
    """JSONL 파일의 각 줄을 JSON 객체로 읽고, 객체가 아닌 줄은 경고 후 건너뜁니다."""
    records = []
    # Windows 편집기가 붙이는 UTF-8 BOM을 허용하고 빈 줄은 건너뜁니다.
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        # 잘못된 줄 하나 때문에 모든 요청이 실패하지 않도록 해당 줄만 제외합니다.
        if not isinstance(record, dict):
            warnings.warn(
                f"JSON 객체가 아닌 줄을 건너뜁니다: {path}:{number}", stacklevel=2
            )
            continue
        records.append(record)
    return records


def retrieve_company_data(question, label):
    """라벨과 질문에 맞는 회사 자료를 JSONL 데이터베이스에서 최대 세 건 찾습니다.

    문서 리트리버 파이프라인만 준비한 상태이며, 응답 모델 프롬프트에는 반영하지 않습니다.
    """
    # 질문의 한국어·영어 단어를 뽑아 자료의 제목과 본문에서 겹치는 단어를 셉니다.
    question_terms = set(re.findall(r"[가-힣A-Za-z0-9]+", question.casefold()))
    matches = []
    # 예시 정책과 50개 문서 카탈로그를 같은 검색 흐름에서 읽습니다.
    records = []
    for path in COMPANY_DATABASE_PATHS:
        # 새 clone처럼 파일이 없을 때 빈 검색 결과를 조용히 반환하지 않도록 경고를 남깁니다.
        if not path.exists():
            warnings.warn(
                f"회사 자료 파일이 없어 검색에서 제외합니다: {path}", stacklevel=2
            )
            continue
        records.extend(read_jsonl(path))
    for record in records:
        # labels가 null이거나 문자열 하나로 적혀 있어도 태그 목록으로 비교합니다.
        labels = record.get("labels")
        if isinstance(labels, str):
            labels = [labels]
        elif not isinstance(labels, list):
            labels = []
        # others는 분류 라벨이 불명확하므로 모든 분야의 자료를 검색합니다.
        if label != "others" and label not in labels:
            continue
        document_terms = re.findall(
            r"[가-힣A-Za-z0-9]+",
            " ".join(
                str(record.get(field, ""))
                for field in (
                    "title",
                    "content",
                    "obligation",
                    "applies_when",
                    "legal_basis",
                    "labels",
                )
            ).casefold(),
        )
        # 한국어 조사가 붙은 단어도 제목의 짧은 핵심어와 맞으면 검색 결과로 봅니다.
        score = sum(
            any(term in word or word in term for word in document_terms)
            for term in question_terms
            if len(term) > 1
        )
        if score:
            matches.append((score, record))
    # 관련도가 높은 자료 세 건만 반환합니다.
    return [
        record
        for _, record in sorted(matches, key=lambda item: item[0], reverse=True)[:3]
    ]


def build_prompt(question, label):
    """확인된 질문과 라벨 정책으로 모델 입력 문자열을 만듭니다."""
    # 임의 라벨로 정책 키 조회가 실패하거나 정책 없이 호출되는 것을 방지합니다.
    if label not in POLICIES:
        raise ValueError(f"알 수 없는 classification_label: {label}")
    # 응답 모델 단계이므로 문서 리트리버 결과는 프롬프트에 넣지 않습니다.
    return (
        # 답변의 언어와 JSON 모양을 지정하고, 확인되지 않은 정보를 만들지 않도록 합니다.
        '한국어로 간단히 답하고 JSON 객체 {"answer": "...", "next_steps": []}로 작성하세요. '
        "근거가 없는 정보나 절차는 만들지 마세요.\n"
        # 라벨에 연결된 최소 정책 문구를 프롬프트에 추가합니다.
        f"정책: {POLICIES[label]}\n"
        # JSON 인코딩으로 질문 내부의 따옴표와 줄바꿈을 안전하게 표현합니다.
        # ensure_ascii=False라 한국어를 유니코드 이스케이프 없이 읽을 수 있습니다.
        f"질문: {json.dumps(question, ensure_ascii=False)}"
    )


def call_ollama(prompt, model=OLLAMA_MODEL):
    """지정한 Ollama 로컬 모델을 호출하고 공통 결과 형식으로 바꿉니다."""
    response = httpx.post(
        # 설정 URL 뒤에 슬래시가 있어도 경로 구분자가 중복되지 않게 정리합니다.
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            # 전체 응답을 한 번에 받으므로 스트림 조립 코드는 필요하지 않습니다.
            "stream": False,
            # 생성 길이를 제한해 이 모듈의 최소 구현에서 과도한 출력을 막습니다.
            "options": {"num_predict": 512},
        },
        # 네트워크 요청의 최대 대기 시간을 제한하고 시스템 프록시 환경 변수는 따르지 않습니다.
        timeout=TIMEOUT,
        trust_env=False,
    )
    # 4xx/5xx 상태를 정상 응답처럼 읽지 않고 예외 처리 경로로 보냅니다.
    response.raise_for_status()
    body = response.json()
    # Ollama 응답을 나머지 제공자와 같은 공통 필드로 맞춥니다.
    return {
        # Ollama generate 응답에서 생성한 본문을 가져옵니다.
        "text": body["response"],
        "model": model,
        # Ollama가 토큰 수를 제공하지 않는 경우에는 None으로 남깁니다.
        "usage": {
            "input_tokens": body.get("prompt_eval_count"),
            "output_tokens": body.get("eval_count"),
        },
        # 모델이 끝난 이유도 API가 제공하는 값이 있을 때 기록합니다.
        "finish_reason": body.get("done_reason"),
    }


def ensure_api_key(provider):
    """외부 제공자의 환경 변수 키가 없으면 대화형 CLI에서 숨김 입력으로 받습니다."""
    # 로컬 Ollama는 API 키가 필요 없고, 미지원 제공자는 dispatch 단계에서 오류 처리됩니다.
    key_name = API_KEY_ENV.get(provider)
    if key_name is None:
        return
    # 이미 환경 변수에 키가 있으면 입력을 생략해 자동 실행과 서비스 환경을 지원합니다.
    if os.getenv(key_name):
        return
    # 비대화형 실행에서는 키 입력을 기다릴 수 없으므로 환경 변수 설정을 안내합니다.
    if not sys.stdin.isatty():
        raise RuntimeError(f"비대화형 실행에는 {key_name} 환경 변수가 필요합니다.")
    provider_name = {"openai": "OpenAI"}[provider]
    api_key = getpass.getpass(f"{provider_name} API 키를 입력하세요: ").strip()
    if not api_key:
        raise ValueError(f"{provider_name} API 키가 비어 있습니다.")
    # SDK가 읽도록 현재 프로세스에만 설정하고, 파일이나 JSONL에는 기록하지 않습니다.
    os.environ[key_name] = api_key


def call_openai(prompt):
    """OpenAI Responses API를 호출하고 Ollama와 같은 결과 필드로 정규화합니다."""
    # SDK 초기화 전에 필수 인증 키가 있는지 확인해 원인을 분명하게 합니다.
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
    # 호출마다 클라이언트를 열고 닫으며, 요청 시간 제한과 재시도 정책을 고정합니다.
    with OpenAI(timeout=TIMEOUT, max_retries=0) as client:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=prompt,
            # 모델 출력 토큰 수를 제한하고 API 서버 저장 옵션을 끕니다.
            max_output_tokens=512,
            store=False,
        )
    # usage가 응답에 없을 수도 있으므로 필드 접근 시 None을 허용합니다.
    usage = response.usage
    return {
        "text": response.output_text,
        "model": OPENAI_MODEL,
        # OpenAI Responses 결과를 공통 실행 기록 필드에 맞춥니다.
        "usage": {
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
        },
        # Responses API의 상태를 공통 finish_reason 자리에 기록합니다.
        "finish_reason": response.status,
    }


def call_deepseek(prompt):
    """DeepSeek R1의 Ollama 로컬 모델을 호출합니다."""
    return call_ollama(prompt, DEEPSEEK_MODEL)


def call_kimi(prompt):
    """Kimi-VL Thinking의 Ollama 로컬 모델을 호출합니다."""
    return call_ollama(prompt, KIMI_MODEL)


def call_model(provider, prompt):
    """Ollama, OpenAI, DeepSeek, Kimi 중 하나를 호출하고 같은 dict 형식으로 반환합니다."""
    # perf_counter는 벽시계 변경 영향을 받지 않는 경과 시간 측정용 시계입니다.
    started = time.perf_counter()
    # 실패하더라도 결과 기록의 필드 구성이 유지되도록 기본값을 먼저 만듭니다.
    result = {
        "text": "",
        "model": None,
        "usage": {},
        "finish_reason": None,
        "error": None,
    }
    try:
        # 단일 모드는 모델 하나를 고르고 compare는 네 모델을 병렬로 호출합니다.
        if provider == "ollama":
            result.update(call_ollama(prompt))
        elif provider == "openai":
            result.update(call_openai(prompt))
        elif provider == "deepseek":
            result.update(call_deepseek(prompt))
        elif provider == "kimi":
            result.update(call_kimi(prompt))
        else:
            # 오타나 지원하지 않는 설정도 기록 가능한 호출 실패로 변환합니다.
            raise ValueError(
                "provider는 ollama, openai, deepseek, kimi 중 하나여야 합니다."
            )
    except Exception as error:  # noqa: BLE001 - 실패 정보를 실행 기록에 저장합니다.
        # 예외 메시지나 전체 traceback 대신 예외 클래스명만 저장합니다.
        result["error"] = type(error).__name__
    # 생성 길이 제한으로 잘린 응답은 본문이 있어도 성공으로 세지 않습니다.
    if result["error"] is None and result["finish_reason"] in TRUNCATED_REASONS:
        result["error"] = "TruncatedOutput"
    # 모델 호출 예외를 외부로 다시 던지지 않고 시간과 제공자 정보를 붙여 반환합니다.
    return {
        **result,
        "provider": provider,
        "latency_seconds": time.perf_counter() - started,
    }


def append_jsonl(path, record):
    """record 한 건을 UTF-8 JSONL 파일 끝에 추가합니다."""
    # 출력 폴더가 아직 없어도 첫 호출에서 생성되도록 상위 폴더를 만듭니다.
    path.parent.mkdir(parents=True, exist_ok=True)
    # append 모드라 이전 실행 결과는 보존되고 레코드 하나가 한 줄을 차지합니다.
    with path.open("a", encoding="utf-8") as stream:
        # 한국어를 그대로 남기고 줄바꿈 하나로 JSON 객체 경계를 구분합니다.
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def process_question(request, provider=PROVIDER):
    """요청 하나를 처리하고 응답 파일과 실행 기록 파일에 각각 저장합니다."""
    # Mapping 또는 Pydantic 요청을 하나의 dict 형태로 통일합니다.
    payload = payload_dict(request)
    # 질문 검증이 실패하면 이 지점에서 중단되어 모델 호출이나 기록 저장은 하지 않습니다.
    question = question_from(payload)
    # 분류 모델은 없으며, 요청에 라벨이 없을 때는 더미 라벨만 적용합니다.
    label = label_from(payload)
    # 두 파일에서 같은 처리를 서로 연결할 수 있도록 한 ID를 공유합니다.
    execution_id = uuid.uuid4().hex
    # 시작 시각은 모델 호출 직전에 UTC ISO 형식으로 기록합니다.
    started = datetime.now(UTC).isoformat()
    # 라벨 정책을 포함한 프롬프트를 만들고 선택된 모델 제공자를 한 번 호출합니다.
    result = call_model(provider, build_prompt(question, label))
    # request_id가 없으면 요청 id를 대체 식별자로 사용하고, 둘 다 없으면 None입니다.
    request_id = payload.get("request_id", payload.get("id"))

    # 이 파일에는 입력 질문과 사용자에게 반환할 모델 본문을 중심으로 저장합니다.
    response_record = {
        "execution_id": execution_id,
        "request_id": request_id,
        "question": question,
        "response": result["text"],
    }
    # 이 파일에는 실행 시간, 사용 모델, 토큰 수, 오류 여부 등 운영 메타데이터를 저장합니다.
    # 완료 시각은 모델 호출이 끝난 뒤 취득하므로 latency와 실행 구간이 대응합니다.
    execution_record = {
        "execution_id": execution_id,
        "request_id": request_id,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        **{
            # call_model이 반환한 메타데이터 중 파일에 남길 항목만 선택합니다.
            key: result[key]
            for key in (
                "provider",
                "model",
                "usage",
                "latency_seconds",
                "finish_reason",
                "error",
            )
        },
    }
    # 두 레코드는 같은 execution_id를 갖지만 각자의 목적 파일에 독립적으로 추가됩니다.
    append_jsonl(RESPONSE_PATH, response_record)
    append_jsonl(EXECUTION_PATH, execution_record)
    # 호출자에게도 저장된 두 레코드를 돌려줘 API/CLI 쪽에서 재사용할 수 있게 합니다.
    return {"response": response_record, "execution_record": execution_record}


def prepare_chain_input(value):
    """LangChain 입력을 표준 질문·라벨·프롬프트 dict로 전처리합니다."""
    # 문자열 입력은 text 필드 요청으로 감싸고, 객체 입력은 공통 변환기를 거칩니다.
    payload = {"text": value} if isinstance(value, str) else payload_dict(value)
    question = question_from(payload)
    # chain도 일반 호출과 같은 더미 라벨 기본값과 정책 검증을 사용합니다.
    label = label_from(payload)
    return {
        "question": question,
        "classification_label": label,
        # 여기서 만든 prompt를 다음 Runnable이 받아 모델 호출을 수행합니다.
        "prompt": build_prompt(question, label),
    }


def create_chain(provider=PROVIDER):
    """입력 정규화 Runnable과 모델 호출 Runnable을 LangChain 파이프로 연결합니다."""
    return RunnableLambda(prepare_chain_input) | RunnableLambda(
        # 전처리 결과는 보존하고 모델 응답 필드만 같은 dict에 합칩니다.
        lambda item: {**item, **call_model(provider, item["prompt"])}
    )


def create_comparison_chain():
    """한 번 전처리한 질문을 네 모델에 LangChain 병렬 Runnable로 보냅니다."""
    return RunnableLambda(prepare_chain_input) | RunnableParallel(
        # 공통 입력을 각 branch가 함께 받고, RunnableParallel이 모든 모델 호출을 동시에 실행합니다.
        question=RunnableLambda(lambda item: item["question"]),
        classification_label=RunnableLambda(lambda item: item["classification_label"]),
        ollama=RunnableLambda(lambda item: call_model("ollama", item["prompt"])),
        openai=RunnableLambda(lambda item: call_model("openai", item["prompt"])),
        deepseek=RunnableLambda(lambda item: call_model("deepseek", item["prompt"])),
        kimi=RunnableLambda(lambda item: call_model("kimi", item["prompt"])),
    )


def read_cases():
    """비교용 JSONL 입력을 읽거나 파일이 없으면 기본 샘플 목록을 반환합니다."""
    # 개발 입력 파일이 없는 환경에서도 compare의 입력 구조를 확인할 수 있게 합니다.
    if not INPUT_PATH.exists():
        return SAMPLE_CASES
    # 회사 자료와 같은 JSONL 읽기 규칙(BOM 허용, 빈 줄·잘못된 줄 제외)을 사용합니다.
    return read_jsonl(INPUT_PATH)


def run_comparison():
    """입력 사례마다 네 모델을 병렬 호출해 새 비교 JSONL 파일에 저장합니다."""
    ensure_api_key("openai")
    COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
    chain = create_comparison_chain()
    run_id = uuid.uuid4().hex
    run_started_at = datetime.now(UTC).isoformat()
    with COMPARISON_PATH.open("x", encoding="utf-8") as stream:
        for case in read_cases():
            results = chain.invoke(case)
            for provider in ("ollama", "openai", "deepseek", "kimi"):
                model_result = results[provider]
                record = {
                    "run_id": run_id,
                    "run_started_at": run_started_at,
                    "id": case.get("id"),
                    "question": results["question"],
                    "classification_label": results["classification_label"],
                    **{
                        key: model_result[key]
                        for key in (
                            "provider",
                            "model",
                            "text",
                            "usage",
                            "latency_seconds",
                            "finish_reason",
                            "error",
                        )
                    },
                }
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("저장 위치:", COMPARISON_PATH)


def main():
    """명령행에서 call, chain, compare 중 하나를 선택해 실행합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        # mode 생략 시 기본 call 모드를 사용하고, 허용된 세 값만 받습니다.
        "mode",
        choices=("call", "chain", "compare"),
        nargs="?",
        default="call",
    )
    mode = parser.parse_args().mode

    # 단일 call/chain 모드에서 Ollama 외 제공자를 선택하면 해당 키를 먼저 확보합니다.
    # compare는 run_comparison 내부에서 병렬 호출 직전에 키를 확보합니다.
    if mode != "compare":
        ensure_api_key(PROVIDER)

    if mode == "call":
        # 샘플 문의를 일반 처리 함수에 전달하고 반환값을 보기 좋은 JSON으로 출력합니다.
        print(json.dumps(process_question(SAMPLE_INPUT), ensure_ascii=False, indent=2))
    elif mode == "chain":
        # chain 예시는 인사 라벨을 요청 입력에 직접 넣어 Runnable 전체 흐름을 보여줍니다.
        result = create_chain().invoke(
            {
                "text": SAMPLE_INPUT["inquiries"],
                "classification_label": "human_resources",
            }
        )
        # LangChain 결과에는 질문, 라벨, 프롬프트, 모델 메타데이터가 포함됩니다.
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # choices가 세 가지로 제한되어 있으므로 남은 모드는 compare입니다.
        run_comparison()


# 다른 모듈에서 import할 때는 실행하지 않고, 이 파일을 직접 실행할 때만 CLI를 시작합니다.
if __name__ == "__main__":
    main()
