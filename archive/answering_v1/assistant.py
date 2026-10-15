"""과거 독립 실행·평가 재현용 비활성 레거시 LangChain 실행기.

현재 서버 /ask와 /assistant는 app.answering.adapter의 최종 generation 경로를
사용하며 이 모듈을 import하지 않습니다. 아래 provider별 출력은 과거 계약입니다.

1) 입력 규약(fastapi_main.py의 AssistantRequest 등과 동일):

class AnswerResponse(BaseModel):
    ok: bool
    text: str
    reason: str = ""

class AssistantRequest(BaseModel):
    response: AnswerResponse
    classification_label: ClassificationLabel  # contracts.classification


2) 기본 문서 파일(data/company-knowledge/documents.jsonl):

{"document_id": "고정 문서 ID", "title": "문서 제목", "document": "문서 내용"}

실행기는 문서 ID를 근거 추적에 사용하지 않고 제목과 본문을 답변 문맥에 넣습니다.


3) provider별 결과 규약:

    반환 스키마 (provider 미지정 시 두 항목)::

        {
            "<provider>": {
                "model": str,
                "inquiry": str,
                "answer": str,
                "document": str,
                "note(LLM)": str,
                "timeout_seconds": float,
                "max_retries": int,
                "max_tokens": int,
                "max_input_chars": int,
                "elapsed_seconds": float,
                "success": bool,
                "error": str | None,
            }
        }

    ``max_tokens``는 Ollama의 ``num_predict`` 값입니다. 두 모델을 같은 조건으로
    비교하도록 타임아웃, 재시도 횟수, 최대 출력은 같은 값을 씁니다. Ollama
    클라이언트는 재시도하지 않으므로 재시도 횟수는 0입니다. OpenAI 모델은
    temperature 기본값만 받으므로 OpenAI의 ``temperature``는 ``None``입니다.
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

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import (
    RunnableBranch,
    RunnableLambda,
    RunnablePassthrough,
)
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.settings import PROJECT_ROOT, get_documents_path
from contracts.classification import (
    CLARIFY,
    LABELS,
    SEARCH_KNOWLEDGE,
    UNSUPPORTED,
)

PROVIDER = os.getenv("PROVIDER", "ollama").casefold()

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
OLLAMA_STARTUP_TIMEOUT = float(os.getenv("OLLAMA_STARTUP_TIMEOUT_SECONDS", "30"))

# 전체 문서 입력은 모델 tokenizer와 본문에 따라 이 한도를 넘을 수 있습니다.
# 2026-10-14 SQLite 71건 smoke는 66,652토큰으로 400을 반환했습니다. 본문을 자르지 않습니다.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "40960"))
OLLAMA_TEMPERATURE = 0.2
OLLAMA_NUM_PREDICT = 512

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
OPENAI_MAX_TOKENS = 512

# 로컬·상용 모델을 같은 조건으로 비교하도록 두 모델에 같은 값을 씁니다.
# OpenAI 모델(gpt-6-luna)은 temperature 기본값(1)만 받아 temperature는 Ollama에만 줍니다.
TIMEOUT = float(os.getenv("GENERATION_TIMEOUT_SECONDS", "600"))
MAX_RETRIES = 0
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "4000"))
DOCUMENTS_PATH = get_documents_path()
_OLLAMA_LOCK = threading.Lock()
_OLLAMA_PROCESS = None

CLASSIFICATION_LABELS = frozenset(LABELS)


class AssistantResponse(BaseModel):
    answer: str = Field(description="최종 답변 텍스트")
    referenced_documents: list[str] = Field(
        description="참고한 문서 제목 목록. 참고한 문서가 없으면 빈 리스트"
    )
    note: str = Field(description="답변을 뒷받침하는 근거 요약")


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
입력된 분류 라벨과 답변 지침을 따르고, 제공된 AssistantResponse 구조에 맞춰 답변하세요.

답변 원칙
- 간결하고 정중한 한국어를 사용하세요. 답변에 필요한 경우에만 글머리표를 사용하세요.
- answer에는 사용자에게 보여 줄 답변만 작성하세요.
- referenced_documents에는 참고한 문서 제목을 정확히 기록하세요. 참고한 문서가 없으면 빈 리스트를 반환하세요.
- note에는 답변을 뒷받침하는 확인 가능한 문서 근거를 짧게 요약하세요.
- 단계별 내부 추론은 쓰지 말고, 확인 가능한 근거만 요약하세요.

<분류 라벨>
{classification_label}
</분류 라벨>

<분류별 답변 지침>
{instruction}
</분류별 답변 지침>

<사용자 질문>
{question}
</사용자 질문>

<비교 사유>
{source_reason}
</비교 사유>

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


def snapshot_context(snapshot):
    return "\n\n".join(
        f"제목: {normalize_text(doc.title)}\n내용: {normalize_text(doc.body)}"
        for doc in snapshot.documents
    )


def load_document_context(path=None):
    """기본 SQLite 게시본 또는 명시적인 평가 JSONL을 읽습니다."""
    if path is None:
        from app.documents.context import DocumentContextProvider

        return snapshot_context(DocumentContextProvider().snapshot())
    path = Path(path)
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


def add_prompt_context(
    value, provider=PROVIDER, documents_path=None, document_snapshot=None
):
    """분류 라벨에 맞는 지침과 프롬프트 문맥을 추가합니다."""
    if value["classification_label"] == SEARCH_KNOWLEDGE:
        document_context = (
            snapshot_context(document_snapshot)
            if document_snapshot is not None
            else load_document_context(documents_path)
            if documents_path is not None
            else load_document_context()
        )
    else:
        document_context = "사용하지 않음"
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
            client_kwargs={"timeout": TIMEOUT},
        )
    if provider == "openai":
        return ChatOpenAI(
            model=OPENAI_MODEL,
            timeout=TIMEOUT,
            max_retries=MAX_RETRIES,
            max_tokens=OPENAI_MAX_TOKENS,
        )
    raise ValueError("PROVIDER는 ollama 또는 openai여야 합니다.")


def create_chain(
    provider=PROVIDER,
    documents_path=None,
    *,
    document_snapshot=None,
):
    """질문과 문서 문맥을 구조화된 LangChain 답변으로 변환합니다."""
    if documents_path is not None and document_snapshot is not None:
        raise ValueError("Use either documents_path or document_snapshot")
    model = create_chat_model(provider)

    structured_chain = ANSWER_PROMPT | model.with_structured_output(AssistantResponse)

    def format_answer(value):
        response = value["structured_response"]
        document_titles = "\n".join(response.referenced_documents)
        return {
            "inquiry": value["question"],
            "answer": normalize_text(response.answer),
            "document": normalize_text(document_titles),
            "note(LLM)": normalize_text(response.note),
        }

    def format_failed_input(value):
        return {
            "inquiry": value["text"],
            "answer": "",
            "document": "",
            "note(LLM)": "",
        }

    answer_chain = (
        RunnableLambda(
            lambda value: add_prompt_context(
                value, provider, documents_path, document_snapshot
            )
        )
        | RunnablePassthrough.assign(structured_response=structured_chain)
        | RunnableLambda(format_answer)
    )

    return RunnableLambda(prepare_input) | RunnableBranch(
        (lambda value: not value["ok"], RunnableLambda(format_failed_input)),
        answer_chain,
    )


def get_execution_conditions(provider):
    """비교 출력에 표시할 공통 실행 설정만 반환합니다."""
    return {
        "timeout_seconds": TIMEOUT,
        "max_retries": MAX_RETRIES,
        "max_tokens": OLLAMA_NUM_PREDICT if provider == "ollama" else OPENAI_MAX_TOKENS,
        "max_input_chars": MAX_INPUT_CHARS,
    }


def process_response(
    response, classification_label, provider=None, *, document_snapshot=None
):
    """두 모델의 비교 기록을 반환합니다."""
    request = {
        "response": payload_dict(response),
        "classification_label": classification_label,
    }
    prepared_request = prepare_input(request)
    input_text = prepared_request.get("question", prepared_request.get("text", ""))

    models = {"ollama": OLLAMA_MODEL, "openai": OPENAI_MODEL}
    providers = tuple(models) if provider is None else (provider,)
    if any(name not in models for name in providers):
        raise ValueError("provider는 ollama 또는 openai여야 합니다.")

    from app.documents.context import (
        NO_DOCUMENTS_MESSAGE,
        DocumentContextProvider,
    )

    if (
        prepared_request.get("ok")
        and classification_label == SEARCH_KNOWLEDGE
        and document_snapshot is None
    ):
        document_snapshot = DocumentContextProvider().snapshot()
    no_documents = (
        classification_label == SEARCH_KNOWLEDGE
        and document_snapshot is not None
        and not document_snapshot.documents
    )
    from langchain_core.callbacks import BaseCallbackHandler

    class InvocationTracker(BaseCallbackHandler):
        called = False

        def on_chat_model_start(self, *args, **kwargs):
            self.called = True

        def on_llm_start(self, *args, **kwargs):
            self.called = True

    results = {}
    for name in providers:
        started_at = time.perf_counter()
        answer = None
        error_message = None
        tracker = InvocationTracker()

        try:
            if not prepared_request.get("ok") or no_documents:
                answer = {
                    "inquiry": input_text,
                    "answer": NO_DOCUMENTS_MESSAGE if no_documents else "",
                    "document": "",
                    "note(LLM)": "",
                }
            else:
                answer = create_chain(name, document_snapshot=document_snapshot).invoke(
                    request, config={"callbacks": [tracker]}
                )
        # 한 모델의 실패가 다른 모델의 결과를 막지 않도록 각각 기록합니다.
        except Exception as error:  # noqa: BLE001
            error_message = f"{type(error).__name__}: {error}"
            answer = {
                "inquiry": input_text,
                "answer": "",
                "document": "",
                "note(LLM)": "",
            }
        results[name] = {
            "model": models[name],
            **answer,
            **get_execution_conditions(name),
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "model_called": tracker.called,
            "success": error_message is None and prepared_request.get("ok", False),
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
    result_path = PROJECT_ROOT / "result.json"
    result_path.write_text(f"{result_json}\n", encoding="utf-8")
    print(result_json)


if __name__ == "__main__":
    main()
