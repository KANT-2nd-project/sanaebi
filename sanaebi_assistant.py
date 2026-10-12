"""문의 요청을 모델에 전달하고 결과와 실행 메타데이터를 JSONL로 저장합니다.

기본 흐름은 요청 객체 변환 → 질문과 라벨 확인 → 프롬프트 생성 → 모델 호출 →
응답 및 실행 기록 저장입니다. 라벨은 요청에서 받는 값이며, 이 모듈은 분류하지
않습니다. `call`, LangChain 기반 `chain`, 두 제공자를 병렬 호출하는 `compare` 모드를
명령행에서 선택할 수 있습니다.
"""

# 표준 라이브러리: CLI 인자, 숨김 키 입력, JSONL 직렬화, 환경 변수, 경과 시간과 ID
# 생성, 요청 매핑, UTC 시각, 저장소 내 파일 경로, 터미널 확인을 처리합니다.
import argparse
import getpass
import json
import os
import sys
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

# 외부 라이브러리: Ollama HTTP 호출, OpenAI 호출, LangChain Runnable 구성에 사용합니다.
import httpx
from langchain_core.runnables import RunnableLambda, RunnableParallel
from openai import OpenAI

# 이 파일이 있는 저장소 루트를 기준으로 데이터 파일의 경로를 계산합니다.
ROOT = Path(__file__).resolve().parent
# 모든 문의 관련 결과를 learner 구분 없이 공통 폴더에 저장합니다.
INQUIRY_DIR = ROOT / "artifacts" / "step_by_step" / "inquiries"
# 일반 호출의 응답 본문과 실행 메타데이터를 각각 별도 JSONL 파일에 누적합니다.
RESPONSE_PATH = INQUIRY_DIR / "responses.jsonl"
EXECUTION_PATH = INQUIRY_DIR / "execution_records.jsonl"
# 비교 입력 파일이 없으면 아래 SAMPLE_CASES를 대신 사용합니다.
INPUT_PATH = ROOT / "steps" / "examples" / "inquiries_development.jsonl"
# compare 모드 결과는 비교 실행 전용 하위 경로에 한 번 기록합니다.
COMPARISON_PATH = INQUIRY_DIR / "comparisons" / "development01" / "results.jsonl"

# 모델 제공자와 접속 주소, 모델 이름은 환경 변수로 바꿀 수 있습니다.

# PROVIDER가 지정되지 않으면 기본 호출은 로컬 Ollama를 사용합니다.
PROVIDER = os.getenv("PROVIDER", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
# 연결 제한 시간은 초 단위이며, 질문의 길이는 문자 수로 제한합니다.
TIMEOUT = float(os.getenv("GENERATION_TIMEOUT_SECONDS", "120"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "4000"))
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


def build_prompt(question, label):
    """확인된 질문과 라벨 정책으로 모델 입력 문자열을 만듭니다."""
    # 임의 라벨로 정책 키 조회가 실패하거나 정책 없이 호출되는 것을 방지합니다.
    if label not in POLICIES:
        raise ValueError(f"알 수 없는 classification_label: {label}")
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


def call_ollama(prompt):
    """Ollama의 비스트리밍 generate API를 호출하고 공통 결과 형식으로 바꿉니다."""
    response = httpx.post(
        # 설정 URL 뒤에 슬래시가 있어도 경로 구분자가 중복되지 않게 정리합니다.
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        json={
            "model": OLLAMA_MODEL,
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
    # 두 제공자의 서로 다른 응답 모양을 아래 공통 필드로 맞춥니다.
    return {
        # Ollama generate 응답에서 생성한 본문을 가져옵니다.
        "text": body["response"],
        "model": OLLAMA_MODEL,
        # Ollama가 토큰 수를 제공하지 않는 경우에는 None으로 남깁니다.
        "usage": {
            "input_tokens": body.get("prompt_eval_count"),
            "output_tokens": body.get("eval_count"),
        },
        # 모델이 끝난 이유도 API가 제공하는 값이 있을 때 기록합니다.
        "finish_reason": body.get("done_reason"),
    }


def ensure_openai_api_key():
    """환경 변수 키가 없으면 대화형 CLI에서 숨김 입력으로 키를 한 번 받습니다."""
    # 이미 설정된 키를 우선 사용해 자동 실행과 서버 환경 설정을 그대로 지원합니다.
    if os.getenv("OPENAI_API_KEY"):
        return
    # 비대화형 실행에서는 키 입력을 기다릴 수 없으므로 환경 변수 설정을 안내합니다.
    if not sys.stdin.isatty():
        raise RuntimeError("비대화형 실행에는 OPENAI_API_KEY 환경 변수가 필요합니다.")
    # getpass는 입력 문자를 터미널에 표시하지 않아 화면이나 터미널 기록에 노출되지 않습니다.
    api_key = getpass.getpass("OpenAI API 키를 입력하세요: ").strip()
    if not api_key:
        raise ValueError("OpenAI API 키가 비어 있습니다.")
    # OpenAI SDK가 기본 환경 변수에서 읽도록 현재 프로세스에만 설정합니다.
    # 파일이나 JSONL 기록에는 저장하지 않습니다.
    os.environ["OPENAI_API_KEY"] = api_key


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
        # 두 제공자 간 결과 기록 구조를 동일하게 맞춥니다.
        "usage": {
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
        },
        # Responses API의 상태를 공통 finish_reason 자리에 기록합니다.
        "finish_reason": response.status,
    }


def call_model(provider, prompt):
    """제공자에 맞는 모델 함수를 호출하고 성공과 실패를 같은 dict로 반환합니다."""
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
        # 선택된 제공자만 호출합니다. compare 모드는 이 함수를 제공자별로 각각 호출합니다.
        if provider == "ollama":
            result.update(call_ollama(prompt))
        elif provider == "openai":
            result.update(call_openai(prompt))
        else:
            # 오타나 지원하지 않는 설정도 기록 가능한 호출 실패로 변환합니다.
            raise ValueError("provider는 ollama 또는 openai여야 합니다.")
    except Exception as error:  # noqa: BLE001 - 실패 정보를 실행 기록에 저장합니다.
        # 예외 메시지나 전체 traceback 대신 예외 클래스명만 저장합니다.
        result["error"] = type(error).__name__
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
    label = payload.get("classification_label", DUMMY_LABEL)
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
    label = payload.get("classification_label", DUMMY_LABEL)
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
    """한 번 전처리한 질문을 Ollama와 OpenAI에 LangChain 병렬 Runnable로 보냅니다."""
    return RunnableLambda(prepare_chain_input) | RunnableParallel(
        # 공통 입력을 각 branch가 함께 받고, RunnableParallel이 branch를 동시에 실행합니다.
        question=RunnableLambda(lambda item: item["question"]),
        classification_label=RunnableLambda(lambda item: item["classification_label"]),
        ollama=RunnableLambda(lambda item: call_model("ollama", item["prompt"])),
        openai=RunnableLambda(lambda item: call_model("openai", item["prompt"])),
    )


def read_cases():
    """비교용 JSONL 입력을 읽거나 파일이 없으면 기본 샘플 목록을 반환합니다."""
    # 개발 입력 파일이 없는 환경에서도 compare의 입력 구조를 확인할 수 있게 합니다.
    if not INPUT_PATH.exists():
        return SAMPLE_CASES
    # UTF-8 BOM을 허용하고 빈 줄은 건너뛰며 나머지는 각각 JSON 객체로 읽습니다.
    return [
        json.loads(line)
        for line in INPUT_PATH.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def run_comparison():
    """입력 사례마다 Ollama와 OpenAI를 병렬 호출해 비교 JSONL을 새로 작성합니다."""
    # 기존 결과를 덮어쓰지 않도록, 결과가 있으면 실행을 시작하기 전에 중단합니다.
    if COMPARISON_PATH.exists():
        raise FileExistsError(f"비교 결과가 이미 있습니다: {COMPARISON_PATH}")
    # 비교 체인에는 OpenAI branch가 포함되므로 병렬 실행 전에 키를 확보합니다.
    ensure_openai_api_key()
    # 입력 파일이나 샘플 사례가 생기기 전에 결과 폴더를 미리 준비합니다.
    COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 두 모델 branch를 가진 병렬 체인을 한 번 만들고 모든 사례에 재사용합니다.
    chain = create_comparison_chain()
    # 결과 파일은 신규 생성 모드로 열어 기존 파일을 이어 쓰지 않습니다.
    with COMPARISON_PATH.open("w", encoding="utf-8") as stream:
        # 한 입력 사례는 한 번의 invoke에서 두 제공자 branch에 동시에 전달됩니다.
        for case in read_cases():
            # invoke는 전처리한 뒤 두 모델 호출이 모두 끝날 때까지 기다립니다.
            results = chain.invoke(case)
            # 출력 순서는 Ollama 다음 OpenAI로 고정해 비교 파일의 재현성을 유지합니다.
            for provider in ("ollama", "openai"):
                model_result = results[provider]
                # 비교에 필요한 질문과 제공자 결과만 골라 JSONL 레코드로 만듭니다.
                record = {
                    "id": case.get("id"),
                    "question": results["question"],
                    "classification_label": results["classification_label"],
                    **{
                        # finish_reason 등 비교 화면에 필요하지 않은 필드는 이 파일에서 생략합니다.
                        key: model_result[key]
                        for key in (
                            "provider",
                            "model",
                            "text",
                            "usage",
                            "latency_seconds",
                            "error",
                        )
                    },
                }
                # 사례-제공자 조합별로 한 줄씩 즉시 씁니다.
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    # 사용자가 저장 위치를 바로 확인할 수 있도록 최종 경로를 출력합니다.
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

    # 단일 call/chain 모드의 기본 제공자가 OpenAI일 때 키를 먼저 확보합니다.
    # compare는 run_comparison 내부에서 병렬 호출 직전에 키를 확보합니다.
    if mode != "compare" and PROVIDER == "openai":
        ensure_openai_api_key()

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
