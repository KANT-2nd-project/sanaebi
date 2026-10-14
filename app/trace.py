"""LLM 답변 요청의 단계별 기록(trace)을 JSONL 파일에 남긴다.

TRACE_DIR 환경변수가 있을 때만 /ask·/assistant 요청 1건을 JSONL 1줄로 기록한다.
기록 파일은 TRACE_DIR/YYYY-MM-DD.jsonl이고, 한 줄에 요청 본문, 단계별 행(steps), 최종 응답을 담는다.

steps는 단계 1개 = 1행이다. 맨 앞은 분류 행(라벨, 출처: /ask는 분류기, /assistant는 요청 값)이고,
이어서 LangChain 단계가 모델마다 실행기 전체, 입력 정리, 경로 선택, 문서 문맥 추가, 프롬프트 만들기,
모델 호출, 출력 해석, 출력 정리 순으로 붙는다. 각 행은 model(ollama/openai), stage, status(ok/error),
seconds(걸린 시간), input, output, error를 갖는다. 모델 호출 행에는 실제 모델명, 종료 사유,
입력·출력 토큰이 더 붙는다. LangChain 내부에서 다른 단계를 감싸기만 하는 실행은 뺀다.
한 요청의 모든 행은 같은 trace_id를 갖고, 두 모델을 차례로 부르면 root_run_id가 둘로 나뉜다.

기록만 하고 요청·응답 본문과 실행기 동작은 바꾸지 않는다. 기록할 때는 응답 헤더 X-Trace-Id로
trace_id를 알려 준다. 기록에 실패해도 요청은 그대로 처리한다.
라우터·서비스·실행기 코드를 고치지 않도록 LangChain 전역 콜백 훅으로 단계를 받는다.

긴 문자열(문서 문맥, 프롬프트 등)은 TRACE_MAX_CHARS(기본 2000자)까지만 남기고 전체 길이와
sha256을 함께 적는다. TRACE_FULL_PROMPT=1이면 모델 프롬프트만 자르지 않고 전부 남긴다.
"""

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

TRACED_PATHS = frozenset({"/ask", "/assistant"})
TRACE_HEADER = b"x-trace-id"
DEFAULT_MAX_CHARS = 2000

_write_lock = threading.Lock()


def trace_directory() -> Path | None:
    """기록 폴더. TRACE_DIR이 비어 있으면 기록하지 않는다."""
    configured = os.environ.get("TRACE_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


def _max_chars() -> int:
    try:
        return max(int(os.environ.get("TRACE_MAX_CHARS", DEFAULT_MAX_CHARS)), 0)
    except ValueError:
        return DEFAULT_MAX_CHARS


def _full_prompt() -> bool:
    return os.environ.get("TRACE_FULL_PROMPT", "").strip() == "1"


def clip_text(text: str, limit: int | None = None) -> str | dict:
    """긴 문자열은 앞부분과 전체 길이·sha256만 남긴다."""
    limit = _max_chars() if limit is None else limit
    if len(text) <= limit:
        return text
    return {
        "head": text[:limit],
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def to_record(value: Any, limit: int | None = None) -> Any:
    """콜백 값을 JSON으로 쓸 수 있는 형태로 바꾼다. 모르는 객체는 문자열로 남긴다."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return clip_text(value, limit)
    if isinstance(value, dict):
        return {str(key): to_record(item, limit) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_record(item, limit) for item in value]
    for name in ("model_dump", "dict"):
        dump = getattr(value, name, None)
        if callable(dump):
            try:
                return to_record(dump(), limit)
            except Exception:  # noqa: BLE001
                break
    return clip_text(repr(value), limit)


def _error_record(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


# LangChain 실행 이름(RunnableLambda 등)을 사람이 읽는 단계 이름으로 바꾼다.
# 실행기(sanaebi_assistant.create_chain) 구조: prepare_input → RunnableBranch →
# 문서 문맥 lambda → RunnableAssign(프롬프트 | 모델 | 출력 해석) → format_answer
ROOT_STAGE = "실행기 전체"
MODEL_STAGE = "모델 호출"
_NAMED_STAGES = {
    "prepare_input": "입력 정리",
    "RunnableBranch": "경로 선택",
    "format_answer": "출력 정리",
    "format_failed_input": "입력 오류 응답",
}


def stage_of(name: str | None, tags, parent_stage: str | None) -> tuple[str, bool]:
    """(단계 이름, 감싸기만 하는 실행인지)를 돌려준다. 모르는 실행은 원래 이름을 쓴다."""
    name = name or ""
    if parent_stage is None:
        return ROOT_STAGE, False
    if name in _NAMED_STAGES:
        return _NAMED_STAGES[name], False
    if name.endswith("PromptTemplate"):
        return "프롬프트 만들기", False
    if name.startswith("RunnableAssign"):
        return "구조화 답변", True
    if parent_stage == "경로 선택":
        if any(str(tag).startswith("condition:") for tag in tags or ()):
            return "경로 조건", True
        return "답변 체인", True
    if parent_stage == "답변 체인" and name == "RunnableLambda":
        return "문서 문맥 추가", False
    if name.startswith(("RunnableSequence", "RunnableParallel")):
        return parent_stage, True
    if parent_stage == "구조화 답변":
        return "출력 해석", False
    return name or "알 수 없음", False


class TraceCallback(BaseCallbackHandler):
    """요청 1건 동안 LangChain 단계를 이름 붙은 행(시작·끝을 합친 1행)으로 모은다."""

    run_inline = True

    def __init__(self):
        self.trace_id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.perf_counter() - self.started

    def _start(
        self, run_id, parent_run_id, *, name, tags=None, model_call=False, **fields
    ):
        run_id = str(run_id)
        parent_run_id = str(parent_run_id) if parent_run_id else None
        with self._lock:
            parent = self._runs.get(parent_run_id)
            if model_call:
                stage, wrapper = MODEL_STAGE, False
            else:
                parent_stage = parent["stage"] if parent else None
                if parent is None and parent_run_id:
                    parent_stage = "알 수 없음"
                stage, wrapper = stage_of(name, tags, parent_stage)
            # 부모가 없는 실행이 체인 실행 1번(모델 1개)의 시작이고, 자식은 그 시작을 물려받는다
            root_run_id = parent["root_run_id"] if parent else (parent_run_id or run_id)
            self._runs[run_id] = {
                "stage": stage,
                "wrapper": wrapper,
                "status": "running",
                "started": self._now(),
                "fields": fields,
                "name": name,
                "root_run_id": root_run_id,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
            }

    def _finish(self, run_id, status: str, **fields):
        with self._lock:
            run = self._runs.get(str(run_id))
            if run is None:
                return
            run["status"] = status
            run["seconds"] = round(self._now() - run["started"], 3)
            run["fields"].update(fields)

    def on_chain_start(
        self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs
    ):
        name = kwargs.get("name") or (serialized or {}).get("name")
        self._start(
            run_id,
            parent_run_id,
            name=name,
            tags=kwargs.get("tags"),
            input=to_record(inputs),
        )

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "ok", output=to_record(outputs))

    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "error", error=_error_record(error))

    def on_chat_model_start(
        self, serialized, messages, *, run_id, parent_run_id=None, **kwargs
    ):
        metadata = kwargs.get("metadata") or {}
        prompt = "\n".join(str(message.content) for message in messages[0])
        self._start(
            run_id,
            parent_run_id,
            name=kwargs.get("name") or (serialized or {}).get("name"),
            model_call=True,
            input=prompt if _full_prompt() else clip_text(prompt),
            provider=metadata.get("ls_provider"),
            model_name=metadata.get("ls_model_name"),
            prompt_chars=len(prompt),
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        generation = response.generations[0][0] if response.generations else None
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}
        self._finish(
            run_id,
            "ok",
            output=to_record(getattr(generation, "text", None)),
            served_model=metadata.get("model_name") or metadata.get("model"),
            # Ollama는 done_reason, OpenAI는 finish_reason으로 끝난 이유를 준다
            finish_reason=metadata.get("done_reason") or metadata.get("finish_reason"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            tool_calls=to_record(getattr(message, "tool_calls", None) or []),
        )

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "error", error=_error_record(error))

    def stage_rows(self) -> list[dict]:
        """기록할 단계 행. 감싸기만 하는 실행은 빼되, 안쪽에 오류가 안 남은 오류는 남긴다."""
        with self._lock:
            runs = list(self._runs.values())
        providers: dict[str, str] = {}
        failed_inside: set[str] = set()
        for run in runs:
            if run["stage"] == MODEL_STAGE and run["fields"].get("provider"):
                providers.setdefault(run["root_run_id"], run["fields"]["provider"])
            if run["status"] == "error":
                parent = run["parent_run_id"]
                while parent and parent not in failed_inside:
                    failed_inside.add(parent)
                    parent = self._runs.get(parent, {}).get("parent_run_id")

        rows = []
        for run in runs:
            if run["wrapper"] and (
                run["status"] != "error" or run["run_id"] in failed_inside
            ):
                continue
            fields = dict(run["fields"])
            rows.append(
                {
                    "trace_id": self.trace_id,
                    "seq": len(rows) + 1,
                    "model": providers.get(run["root_run_id"]),
                    "stage": run["stage"],
                    "status": run["status"],
                    "at_seconds": round(run["started"], 3),
                    "seconds": run.get("seconds"),
                    "input": fields.pop("input", None),
                    "output": fields.pop("output", None),
                    "error": fields.pop("error", None),
                    **fields,
                    "name": run["name"],
                    "root_run_id": run["root_run_id"],
                    "run_id": run["run_id"],
                    "parent_run_id": run["parent_run_id"],
                }
            )
        return rows

    def record_rows(self, path: str, request: Any, status: int | None) -> list[dict]:
        """기록할 steps: 맨 앞 분류 행 + LangChain 단계 행."""
        rows = self.stage_rows()
        roots = [row for row in rows if row["parent_run_id"] is None]
        label = None
        if roots and isinstance(roots[0]["input"], dict):
            label = roots[0]["input"].get("classification_label")
        stopped = not roots and (status or 0) >= 400
        classification = {
            "trace_id": self.trace_id,
            "seq": None,
            "model": None,
            "stage": "분류",
            "status": "error" if stopped else "ok",
            "at_seconds": 0.0,
            # 분류기는 LangChain 밖이라 첫 체인 실행이 시작될 때까지를 분류 시간으로 본다
            "seconds": roots[0]["at_seconds"] if roots else None,
            "input": _question_text(request),
            "output": label,
            "error": f"LangChain 전에 멈춤 (HTTP {status})" if stopped else None,
            "source": "분류기" if path == "/ask" else "요청 값",
        }
        return _numbered([classification, *rows])


def _numbered(rows: list[dict]) -> list[dict]:
    for seq, row in enumerate(rows, start=1):
        row["seq"] = seq
    return rows


def _question_text(request: Any) -> Any:
    """/ask는 question, /assistant는 response.text에 질문이 있다."""
    if not isinstance(request, dict):
        return None
    if "question" in request:
        return request["question"]
    response = request.get("response")
    return response.get("text") if isinstance(response, dict) else None


_current_trace: ContextVar[TraceCallback | None] = ContextVar(
    "sanaebi_trace", default=None
)
# 요청마다 _current_trace에 넣은 콜백을 이 문맥의 모든 LangChain 실행에 붙인다.
register_configure_hook(_current_trace, inheritable=True)


def _body_record(chunks: list[bytes]) -> Any:
    body = b"".join(chunks).decode("utf-8", errors="replace")
    if not body:
        return None
    try:
        return to_record(json.loads(body))
    except json.JSONDecodeError:
        return clip_text(body)


def write_trace(directory: Path, record: dict) -> Path:
    """기록 1건을 날짜별 JSONL 파일 끝에 추가한다."""
    path = directory / f"{datetime.now().astimezone():%Y-%m-%d}.jsonl"
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _write_lock:
        directory.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n")
    return path


class TraceMiddleware:
    """TRACE_DIR이 있으면 답변 요청 1건을 JSONL 1줄로 기록한다. 응답은 바꾸지 않는다."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        directory = trace_directory()
        if (
            scope["type"] != "http"
            or directory is None
            or scope["path"] not in TRACED_PATHS
        ):
            await self.app(scope, receive, send)
            return

        callback = TraceCallback()
        request_chunks: list[bytes] = []
        response_chunks: list[bytes] = []
        status: list[int] = []

        async def receive_and_record() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                request_chunks.append(message.get("body", b""))
            return message

        async def send_and_record(message: Message) -> None:
            if message["type"] == "http.response.start":
                status.append(message["status"])
                # 이상한 답을 본 사람이 기록 줄을 찾을 수 있게 trace_id를 헤더로 알려 준다
                message["headers"] = [
                    *message.get("headers", []),
                    (TRACE_HEADER, callback.trace_id.encode("ascii")),
                ]
            elif message["type"] == "http.response.body":
                response_chunks.append(message.get("body", b""))
            await send(message)

        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        token = _current_trace.set(callback)
        error = None
        try:
            await self.app(scope, receive_and_record, send_and_record)
        except Exception as exc:
            error = _error_record(exc)
            raise
        finally:
            _current_trace.reset(token)
            request = _body_record(request_chunks)
            # 처리되지 않은 예외는 바깥의 ServerErrorMiddleware가 500으로 응답한다
            status_code = status[0] if status else (500 if error else None)
            record = {
                "trace_id": callback.trace_id,
                "started_at": started_at,
                "elapsed_seconds": round(time.perf_counter() - callback.started, 3),
                "method": scope.get("method"),
                "path": scope["path"],
                "request": request,
                "status": status_code,
                "response": _body_record(response_chunks),
                "error": error,
                "steps": callback.record_rows(scope["path"], request, status_code),
            }
            try:
                write_trace(directory, record)
            # 기록 실패가 답변 요청을 막지 않도록 경고만 남긴다.
            except Exception:
                logger.warning(
                    "디버깅 기록을 쓰지 못했습니다: %s", directory, exc_info=True
                )
