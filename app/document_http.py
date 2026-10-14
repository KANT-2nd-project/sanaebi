"""HTTP helpers for the managed-document API boundary."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_DOCUMENT_REQUEST_BYTES = 512 * 1024


def is_managed_document_path(path: str) -> bool:
    return path == "/documents" or path.startswith("/documents/")


def document_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": error},
        headers={"Cache-Control": "no-store"},
    )


def validation_error_details(errors: list[dict[str, Any]]) -> dict[str, Any]:
    """Return locations and error kinds without echoing submitted values."""
    return {
        "fields": [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "reason": error.get("type", "invalid"),
            }
            for error in errors
        ]
    }


class ManagedDocumentHttpMiddleware:
    """Limit request bytes and disable caching for every document API response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_managed_document_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        content_length = _content_length(scope)
        oversized = (
            content_length is not None and content_length > MAX_DOCUMENT_REQUEST_BYTES
        )
        chunks: list[bytes] = []
        body_size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if not oversized:
                body = message.get("body", b"")
                body_size += len(body)
                if body_size > MAX_DOCUMENT_REQUEST_BYTES:
                    oversized = True
                    chunks.clear()
                else:
                    chunks.append(body)
            if not message.get("more_body", False):
                break

        if oversized:
            await document_error_response(
                413, "body_too_large", "요청 본문이 허용 크기를 초과했습니다."
            )(scope, receive, send_no_store)
            return

        body = b"".join(chunks)
        sent_body = False

        async def replay_receive() -> Message:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send_no_store)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-length":
            try:
                length = int(value)
            except (TypeError, ValueError):
                return None
            return length if length >= 0 else None
    return None


async def handle_document_validation_error(request: Request, exc) -> JSONResponse:
    return document_error_response(
        422,
        "validation_error",
        "요청 형식이 올바르지 않습니다. 필수 항목과 입력값을 확인해주세요.",
        validation_error_details(exc.errors()),
    )
