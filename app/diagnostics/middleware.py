"""Opt-in HTTP request/response capture around answer endpoints."""

import logging
import time
from datetime import datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .callback import TraceCallback, _error_record
from .context import _current_trace
from .sink import _body_record, trace_directory, write_trace

logger = logging.getLogger("app.diagnostics.trace")
TRACED_PATHS = frozenset({"/ask", "/assistant"})
TRACE_HEADER = b"x-trace-id"


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
