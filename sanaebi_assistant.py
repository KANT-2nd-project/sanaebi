"""분류 라벨과 비교 응답을 받아 LangChain으로 답변합니다.

1) 입력 규약(fastapi_main.py의 AssistantRequest 등과 동일):

class AnswerResponse(BaseModel):
    ok: bool
    text: str
    reason: str = ""

class AssistantRequest(BaseModel):
    response: AnswerResponse
    classification_label: Literal["SEARCH_KNOWLEDGE", "UNSUPPORTED", "CLARIFY"]


2) 문서 스키마(ieum_works.jsonl):

{"title": "문서 제목", "document": "문서 내용"}


3) 출력 규약('초안'):

    반환 스키마 (provider 미지정 시 두 항목)::

        {
            "<provider>": {
                "model": str,
                "input": dict,
                "output": {"ok": bool, "text": str, "reason": str} | None,
                "timeout_seconds": float | None,
                "max_retries": int | None,
                "max_tokens": int,
                "max_input_chars": int,
                "elapsed_seconds": float,
                "success": bool,
                "error": str | None,
            }
        }

    ``max_tokens``는 Ollama의 ``num_predict`` 값입니다. Ollama에서 별도로
    설정하지 않은 타임아웃과 재시도 횟수는 ``None``입니다.
"""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import (
    RunnableBranch,
    RunnableLambda,
    RunnablePassthrough,
)
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

PROVIDER = os.getenv("PROVIDER", "ollama").casefold()

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
OLLAMA_STARTUP_TIMEOUT = float(os.getenv("OLLAMA_STARTUP_TIMEOUT_SECONDS", "30"))

OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
OLLAMA_TEMPERATURE = 0.1
OLLAMA_NUM_PREDICT = 512

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
TIMEOUT = float(os.getenv("GENERATION_TIMEOUT_SECONDS", "600"))
OPENAI_MAX_RETRIES = 0
OPENAI_MAX_TOKENS = 512
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "4000"))
DOCUMENTS_PATH = Path(
    os.getenv(
        "IEUM_WORKS_PATH", str(Path(__file__).resolve().parent / "ieum_works.jsonl")
    )
)
_OLLAMA_LOCK = threading.Lock()
_OLLAMA_PROCESS = None

SEARCH_KNOWLEDGE = "SEARCH_KNOWLEDGE"
UNSUPPORTED = "UNSUPPORTED"
CLARIFY = "CLARIFY"
CLASSIFICATION_LABELS = {SEARCH_KNOWLEDGE, UNSUPPORTED, CLARIFY}

# SAMPLE_INPUT = {
#     "response": {
#         "ok": True,
#         "text": "출장을 승인받으려면 어떤 정보를 제출해야 하나요?",
#         "reason": "비교 결과",
#     },
#     "classification_label": SEARCH_KNOWLEDGE,
# }

SAMPLE_INPUT = {
    "response": {
        "ok": True,
        "text": "KANT 회사의 총 인원은 몇명인가요",
        "reason": "비교 결과",
    },
    "classification_label": UNSUPPORTED,
}


CLASSIFICATION_INSTRUCTIONS = {
    SEARCH_KNOWLEDGE: "아래 문서 데이터에서 질문과 관련된 내용을 찾아 답하세요. 문서의 문구를 그대로 길게 복사하지 말고 질문에 맞게 요약하세요. 답변은 문서에 적힌 사실과 절차만 근거로 작성하고, 관련 문서의 제목을 함께 밝혀 주세요. 문서에 없는 회사 정책이나 절차는 추측하지 말고 확인되지 않는다고 알려 주세요.관련 규정이 여러 개면 함께 고려하고, 서로 다른 범위나 조건은 구분해서 설명하세요. 관련 문서의 제목을 답변에 표시하세요. 비교 사유는 분류 판단을 이해하기 위한 참고 정보입니다. 사용자 질문이나 문서 데이터와 충돌하면 문서 데이터와 분류별 지침을 우선하세요. 문서에서 답을 찾을 수 없으면 그 사실을 분명히 말하고, 빈 내용을 추론하거나 다른 회사 관행으로 보충하지 마세요.",
    UNSUPPORTED: "문서 근거 답변 대상이 아닙니다. 질문에 직접적이고 도움이 되게 답하세요. 질문의 핵심에 먼저 답하고, 필요한 조건이나 절차가 있으면 읽기 쉬운 순서로 설명하세요. 일반적인 답변은 가능하지만, 확인할 수 없는 회사 고유 정책이나 절차를 사실처럼 말하지 마세요. 답변은 질문에 직접 답하되, 확인되지 않은 이음웍스 내부 규정은 만들어 내지 마세요.",
    CLARIFY: "질문의 근거나 의도가 명확하지 않습니다. 내용을 추측해 답하지 말고, 답변에 필요한 핵심 맥락을 확인하는 짧고 구체적인 질문 하나를 하세요.",
}

ANSWER_PROMPT = PromptTemplate.from_template(
    """역할
당신은 이음웍스 사내 문의에 답하는 한국어 업무 도우미입니다.
입력된 분류 라벨과 답변 지침을 따르고, 최종 답변 텍스트만 작성하세요.

답변 원칙
- 간결하고 정중한 한국어를 사용하세요. 답변에 필요한 경우에만 글머리표를 사용하세요.
- 출력은 strict JSON 형식으로

 작성하세요. text와 reason은 문자열이어야 합니다. JSON 객체의 다른 항목은 포함하지 마세요.

<분류 라벨>
{classification_label}
</분류 라벨>

<분류별 답변 지침>
{instruction}
</분류별 답변 지침>

<사용자 질문>
{question}
</사용자 질문>

<문서 데이터: 각 항목은 제목과 내용으로 구성됨>
{document_data}
</문서 데이터>
"""
)


def normalize_text(value):
    """앞뒤·반복 공백을 정리하면서 문단 경계는 유지합니다."""
    if not isinstance(value, str):
        raise TypeError("text와 reason은 문자열이어야 합니다.")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\t\f\v ]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def payload_dict(value):
    """JSON 문자열, 매핑, 또는 Pydantic 객체를 dict로 정규화합니다."""
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Mapping):
        return dict(value)
    for name in ("model_dump", "dict"):
        dump = getattr(value, name, None)
        if callable(dump):
            payload = dump()
            if isinstance(payload, Mapping):
                return dict(payload)
    raise TypeError("입력은 JSON 객체 또는 Pydantic 모델이어야 합니다.")


def prepare_input(value):
    """비교 응답과 앞 단계 분류 라벨을 검증하고 질문을 정리합니다."""
    payload = payload_dict(value)
    response = payload_dict(payload.get("response"))
    label = payload.get("classification_label")
    if label not in CLASSIFICATION_LABELS:
        raise ValueError(
            f"classification_label은 {sorted(CLASSIFICATION_LABELS)} 중 하나여야 합니다."
        )

    ok = response.get("ok")
    if not isinstance(ok, bool):
        raise TypeError("response.ok는 true 또는 false여야 합니다.")

    reason = response.get("reason", "")
    if not isinstance(reason, str):
        raise TypeError("response.reason은 문자열이어야 합니다.")
    text = response.get("text", "")
    if not isinstance(text, str):
        raise TypeError("response.text는 문자열이어야 합니다.")

    if not ok:
        return {
            "ok": False,
            "text": normalize_text(text),
            "reason": normalize_text(reason),
        }

    question = normalize_text(text)
    if not question:
        raise ValueError("response.text에 질문을 입력해야 합니다.")
    if len(question) > MAX_INPUT_CHARS:
        raise ValueError(f"질문은 {MAX_INPUT_CHARS}자 이하여야 합니다.")

    return {
        "ok": True,
        "question": question,
        "source_reason": normalize_text(reason),
        "classification_label": label,
    }


def load_document_context(path=DOCUMENTS_PATH):
    """JSONL 문서 전체를 프롬프트 문맥으로 읽습니다. 검색은 수행하지 않습니다."""
    if not path.is_file():
        raise FileNotFoundError(f"문서 데이터 파일이 없습니다: {path}")

    entries = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, Mapping):
                raise TypeError(f"{line_number}번째 줄은 JSON 객체여야 합니다.")
            title = item.get("title")
            document = item.get("document")
            if not isinstance(title, str) or not isinstance(document, str):
                raise TypeError(
                    f"{line_number}번째 줄에는 문자열 title과 document가 필요합니다."
                )
            entries.append(
                f"제목: {normalize_text(title)}\n내용: {normalize_text(document)}"
            )

    if not entries:
        raise ValueError(f"문서 데이터가 비어 있습니다: {path}")
    return "\n\n".join(entries)


def ollama_is_ready():
    """Ollama API가 응답하는지 확인합니다."""
    try:
        with urlopen(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def ensure_ollama_server():
    """로컬 Ollama가 꺼져 있으면 백그라운드로 시작하고 준비될 때까지 기다립니다."""
    global _OLLAMA_PROCESS

    if ollama_is_ready():
        return

    with _OLLAMA_LOCK:
        if ollama_is_ready():
            return

        ollama_url = urlparse(OLLAMA_URL)
        if ollama_url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError(
                f"Ollama 서버에 연결할 수 없습니다: {OLLAMA_URL}. "
                "원격 서버는 자동으로 시작할 수 없습니다."
            )

        ollama_executable = shutil.which("ollama")
        if ollama_executable is None:
            raise RuntimeError(
                "Ollama가 PATH에서 검색되지 않습니다. Ollama를 설치한 뒤 다시 실행하세요."
            )

        hostname = ollama_url.hostname
        host = f"[{hostname}]" if ":" in hostname else hostname
        port = ollama_url.port or (443 if ollama_url.scheme == "https" else 80)
        process_env = os.environ.copy()
        process_env["OLLAMA_HOST"] = f"{host}:{port}"
        process_options = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": process_env,
        }
        if os.name == "nt":
            process_options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            process_options["start_new_session"] = True

        try:
            _OLLAMA_PROCESS = subprocess.Popen(
                [ollama_executable, "serve"], **process_options
            )
        except OSError as error:
            raise RuntimeError(
                f"ollama serve를 시작하지 못했습니다: {error}"
            ) from error

        deadline = time.monotonic() + OLLAMA_STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if ollama_is_ready():
                return
            exit_code = _OLLAMA_PROCESS.poll()
            if exit_code is not None:
                raise RuntimeError(
                    f"ollama serve 프로세스가 종료되었습니다 (종료 코드 {exit_code})."
                )
            time.sleep(0.5)

        raise TimeoutError(
            f"Ollama가 {OLLAMA_STARTUP_TIMEOUT:g}초 안에 준비되지 않았습니다. "
            "OLLAMA_STARTUP_TIMEOUT_SECONDS로 대기 시간을 늘릴 수 있습니다."
        )


def add_prompt_context(value, provider=PROVIDER):
    """분류 라벨에 맞는 지침과 프롬프트 문맥을 추가합니다."""
    document_context = (
        load_document_context()
        if value["classification_label"] == SEARCH_KNOWLEDGE
        else "사용하지 않음"
    )
    if provider == "ollama":
        ensure_ollama_server()
    return {
        **value,
        "instruction": CLASSIFICATION_INSTRUCTIONS[value["classification_label"]],
        "document_data": document_context,
    }


def create_chat_model(provider=PROVIDER):
    """LangChain의 Ollama 또는 OpenAI 채팅 모델을 만듭니다."""
    if provider == "ollama":
        return ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_URL,
            temperature=OLLAMA_TEMPERATURE,
            num_ctx=OLLAMA_NUM_CTX,
            num_predict=OLLAMA_NUM_PREDICT,
        )
    if provider == "openai":
        return ChatOpenAI(
            model=OPENAI_MODEL,
            timeout=TIMEOUT,
            max_retries=OPENAI_MAX_RETRIES,
            max_tokens=OPENAI_MAX_TOKENS,
        )
    raise ValueError("PROVIDER는 ollama 또는 openai여야 합니다.")


def create_chain(provider=PROVIDER):
    """두 입력값을 하나의 LangChain 문자열 프롬프트로 처리합니다."""
    model = create_chat_model(provider)
    output_parser = StrOutputParser() | RunnableLambda(normalize_text)

    answer_chain = (
        RunnableLambda(lambda value: add_prompt_context(value, provider))
        | RunnablePassthrough.assign(answer=ANSWER_PROMPT | model | output_parser)
        | RunnableLambda(
            lambda value: {
                "ok": True,
                "text": value["answer"],
                "reason": value["classification_label"],
            }
        )
    )

    return RunnableLambda(prepare_input) | RunnableBranch(
        (lambda value: not value["ok"], RunnableLambda(lambda value: value)),
        answer_chain,
    )


def get_execution_conditions(provider):
    """비교 출력에 표시할 공통 실행 설정만 반환합니다."""
    if provider == "ollama":
        return {
            "timeout_seconds": None,
            "max_retries": None,
            "max_tokens": OLLAMA_NUM_PREDICT,
            "max_input_chars": MAX_INPUT_CHARS,
        }
    return {
        "timeout_seconds": TIMEOUT,
        "max_retries": OPENAI_MAX_RETRIES,
        "max_tokens": OPENAI_MAX_TOKENS,
        "max_input_chars": MAX_INPUT_CHARS,
    }


def process_response(response, classification_label, provider=None):
    """두 모델의 비교 기록을 반환합니다."""
    request = {
        "response": payload_dict(response),
        "classification_label": classification_label,
    }
    prepare_input(request)

    models = {"ollama": OLLAMA_MODEL, "openai": OPENAI_MODEL}
    providers = tuple(models) if provider is None else (provider,)
    if any(name not in models for name in providers):
        raise ValueError("provider는 ollama 또는 openai여야 합니다.")

    results = {}
    for name in providers:
        started_at = time.perf_counter()
        answer = None
        error_message = None
        try:
            answer = create_chain(name).invoke(request)
        # 한 모델의 실패가 다른 모델의 결과를 막지 않도록 각각 기록합니다.
        except Exception as error:  # noqa: BLE001
            error_message = f"{type(error).__name__}: {error}"
        results[name] = {
            "model": models[name],
            "input": request,
            "output": answer,
            **get_execution_conditions(name),
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "success": error_message is None,
            "error": error_message,
        }
    return results


def read_input(path):
    """파일이나 표준 입력에서 두 값이 든 JSON 객체를 읽습니다."""
    if path is not None:
        return payload_dict(path.read_text(encoding="utf-8-sig"))
    if not sys.stdin.isatty():
        return payload_dict(sys.stdin.read())
    return SAMPLE_INPUT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", type=Path)
    request = read_input(parser.parse_args().input_json)
    api_key = getpass.getpass("OpenAI API 키 (입력 숨김): ").strip()
    if not api_key:
        parser.error("OpenAI API key cannot be empty.")
    os.environ["OPENAI_API_KEY"] = api_key

    result = process_response(
        request["response"],
        request["classification_label"],
    )
    result_json = json.dumps(result, ensure_ascii=False, indent=2)
    result_path = Path(__file__).resolve().with_name("result.json")
    result_path.write_text(f"{result_json}\n", encoding="utf-8")
    print(result_json)


if __name__ == "__main__":
    main()
