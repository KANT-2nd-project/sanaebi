"""Opt-in JSONL trace for /ask and /assistant.

TRACE_DIR is unset by default. When enabled, the existing trace format keeps the
request/response and LangChain callback details. Treat those files as sensitive:
they can contain user text and clipped prompt/model output. TRACE_FULL_PROMPT=1
stores the whole prompt instead of the default clipped preview.

The current generation adapter also records the actual classification label and
a separate, content-free generation result row. That row only accepts an
allowlist of model/profile, snapshot/prompt hashes, outcome, duration, usage,
and exception type. It never stores prompt, question, document, answer, key, or
exception-message fields. LangChain callback rows still capture the model stop
reason and remain separate from this final generation status.

Each request remains one JSONL line with one trace_id, and response headers
include X-Trace-Id. A trace write failure never changes the answer response.
Long callback strings are clipped to TRACE_MAX_CHARS (default 2000 characters)
with their total length and SHA-256 hash.
"""

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Mapping
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
GENERATION_STAGE = "생성 판정"

# 새 생성 어댑터가 추가하는 요약 정보의 키만 허용한다. 질문, 프롬프트,
# 문서 본문, 답변 원문, 예외 메시지는 이 레코드에 들어가지 않는다.
_GENERATION_FIELDS = frozenset(
    {
        "model",
        "profile",
        "snapshot_fingerprint",
        "prompt_sha256",
        "prompt_roles_sha256",
        "config",
        "status",
        "seconds",
        "input_tokens",
        "output_tokens",
        "error_type",
    }
)
_GENERATION_ALIASES = {
    "model_name": "model",
    "prompt_profile": "profile",
    "snapshot_sha256": "snapshot_fingerprint",
    "generation_status": "status",
    "elapsed_seconds": "seconds",
    "generation_seconds": "seconds",
}
_ROUTING_FIELDS = frozenset(
    {
        "routing_mode",
        "label_source",
        "classification_status",
        "classification_elapsed_seconds",
        "processing_path",
        "generation_attempted",
    }
)
_ROUTING_MODES = frozenset({"gate", "shadow"})
_LABEL_SOURCES = frozenset({"model", "client"})
_CLASSIFICATION_STATUSES = frozenset(
    {
        "running",
        "ok",
        "provided",
        "not_run",
        "unavailable",
        "inference_error",
        "unexpected_error",
        "invalid_label",
    }
)
_PROCESSING_PATHS = frozenset(
    {
        "classification",
        "classification_failed",
        "classification_error_shadow",
        "upstream_failure",
        "invalid_label",
        "clarify",
        "unsupported",
        "document_lookup",
        "empty_documents",
        "generation",
    }
)

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
        self._classification_label: str | None = None
        self._classification_seconds: float | None = None
        self._generation: dict[str, Any] | None = None
        self._routing: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.perf_counter() - self.started

    def record_classification(self, label: str) -> None:
        """실제 분류 라벨과 분류 완료 시점만 보관한다."""
        with self._lock:
            self._classification_label = str(label)
            self._classification_seconds = round(self._now(), 3)

    def record_generation(self, fields: Mapping[str, Any]) -> None:
        """모델 호출 결과와 구분되는 안전한 생성 판정 메타데이터를 보관한다."""
        safe: dict[str, Any] = {}
        for key, value in fields.items():
            normalized_key = _GENERATION_ALIASES.get(key, key)
            if normalized_key not in _GENERATION_FIELDS:
                continue
            if normalized_key == "config":
                if not isinstance(value, dict):
                    continue
                allowed = {
                    "provider",
                    "model_name",
                    "timeout_seconds",
                    "context_window",
                    "max_output_tokens",
                    "reasoning_effort",
                    "temperature",
                    "output_mode",
                }
                value = {
                    k: v
                    for k, v in value.items()
                    if k in allowed and (v is None or isinstance(v, str | int | float))
                }
            elif normalized_key == "error_type":
                # 호출자는 예외 객체가 아닌 형식 이름만 전달해야 한다.
                if isinstance(value, type) and issubclass(value, BaseException):
                    value = value.__name__
                elif isinstance(value, BaseException):
                    value = type(value).__name__
                elif value is not None and not isinstance(value, str):
                    continue
            elif normalized_key in {"seconds", "input_tokens", "output_tokens"}:
                if value is not None and not isinstance(value, int | float):
                    continue
            elif value is not None and not isinstance(value, str):
                enum_value = getattr(value, "value", None)
                if isinstance(enum_value, str):
                    value = enum_value
                else:
                    continue
            safe[normalized_key] = value

        with self._lock:
            self._generation = safe

    def record_routing(self, fields: Mapping[str, Any]) -> None:
        """Record allowlisted routing state without request or exception text."""
        safe: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in _ROUTING_FIELDS:
                continue
            if key == "routing_mode" and value not in _ROUTING_MODES:
                continue
            if key == "label_source" and value not in _LABEL_SOURCES:
                continue
            if key == "classification_status" and value not in _CLASSIFICATION_STATUSES:
                continue
            if key == "classification_elapsed_seconds":
                if value is not None and not isinstance(value, int | float):
                    continue
                if value is not None:
                    value = round(max(float(value), 0.0), 3)
            if key == "processing_path" and value not in _PROCESSING_PATHS:
                continue
            if key == "generation_attempted" and not isinstance(value, bool):
                continue
            safe[key] = value
        with self._lock:
            self._routing.update(safe)

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
        with self._lock:
            label = self._classification_label
            classification_seconds = self._classification_seconds
            generation = (
                dict(self._generation) if self._generation is not None else None
            )
            routing = dict(self._routing)
        if label is None and roots and isinstance(roots[0]["input"], dict):
            label = roots[0]["input"].get("classification_label")
        stopped = label is None and not roots and (status or 0) >= 400
        classification_status = routing.get("classification_status")
        classification_step_status = (
            "skipped"
            if classification_status == "not_run"
            else "error"
            if classification_status
            in {"unavailable", "inference_error", "unexpected_error", "invalid_label"}
            else "error"
            if stopped
            else "ok"
        )
        classification = {
            "trace_id": self.trace_id,
            "seq": None,
            "model": None,
            "stage": "분류",
            "status": classification_step_status,
            "at_seconds": 0.0,
            # 새 경로는 분류기가 직접 완료 시점을 기록한다. 과거 체인에서는
            # 첫 체인 시작 시점을 분류 시간의 근사치로 사용한다.
            "seconds": (
                classification_seconds
                if classification_seconds is not None
                else roots[0]["at_seconds"]
                if roots
                else None
            ),
            "input": _question_text(request),
            "output": label,
            "error": f"LangChain 전에 멈춤 (HTTP {status})" if stopped else None,
            "source": (
                "분류기"
                if routing.get("label_source", "model" if path == "/ask" else "client")
                == "model"
                else "요청 값"
            ),
            **routing,
        }
        result_rows = [classification, *rows]
        if generation is not None:
            seconds = generation.get("seconds")
            result_rows.append(
                {
                    "trace_id": self.trace_id,
                    "seq": None,
                    "model": generation.get("model"),
                    "stage": GENERATION_STAGE,
                    # 이는 on_llm_end의 finish_reason과 별개인 검증 결과다.
                    "status": generation.get("status", "unknown"),
                    "at_seconds": (
                        round(max(self._now() - seconds, 0), 3)
                        if isinstance(seconds, int | float)
                        else None
                    ),
                    "seconds": seconds,
                    "input": None,
                    "output": None,
                    "error": None,
                    **generation,
                }
            )
        return _numbered(result_rows)


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


def record_classification(label: str) -> None:
    """현재 HTTP 요청의 trace에 실제 분류 라벨을 기록한다.

    TRACE_DIR이 꺼져 있거나 요청 trace 문맥 밖이면 아무 일도 하지 않는다.
    """
    callback = _current_trace.get()
    if callback is not None:
        try:
            callback.record_classification(label)
        except Exception:  # noqa: BLE001 - diagnostic failure must not alter responses
            logger.warning("분류 trace 메타데이터 기록 실패")


def record_generation(fields: Mapping[str, Any]) -> None:
    """현재 요청 trace에 허용된 생성 메타데이터만 기록한다."""
    callback = _current_trace.get()
    if callback is not None:
        try:
            callback.record_generation(fields)
        except Exception:  # noqa: BLE001 - omit exception text from safe logs
            logger.warning("생성 trace 메타데이터 기록 실패")


def record_routing(fields: Mapping[str, Any]) -> None:
    """Record safe routing state for the current request trace, if enabled."""
    callback = _current_trace.get()
    if callback is not None:
        try:
            callback.record_routing(fields)
        except Exception:  # noqa: BLE001 - diagnostics must not alter responses
            logger.warning("라우팅 trace 메타데이터 기록 실패")


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
