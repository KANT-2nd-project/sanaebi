import sqlite3

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.answering.output import LLM_RESPONSE_ERROR, LLMResponseError
from app.classification.predictor import (
    ClassificationInferenceError,
    ClassificationUnavailable,
)
from app.documents.context import DocumentStorageError
from app.documents.http import (
    document_error_response,
    handle_document_validation_error,
    is_managed_document_path,
)
from app.documents.service import DocumentServiceError
from app.schemas import AnswerResponse


# 오류가 나면 handler가 오류를 찾고 오류 내용을 말해줌
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if is_managed_document_path(request.url.path):
        return await handle_document_validation_error(request, exc)
    response = AnswerResponse(
        ok=False,
        text="",
        reason="요청 형식이 올바르지 않습니다. 필수 항목과 입력값을 확인해주세요.",
    )
    return JSONResponse(status_code=422, content=response.model_dump())


# 작성일: 2026-10-14
# 작성자: yu
# 기능: LLM 응답에 쓸 text가 없으면 원문 대신 안내 문구로 502 반환
async def handle_llm_response_error(
    request: Request, exc: LLMResponseError
) -> JSONResponse:
    response = AnswerResponse(ok=False, text="", reason=LLM_RESPONSE_ERROR)
    return JSONResponse(status_code=502, content=response.model_dump())


async def handle_document_service_error(
    request: Request, exc: DocumentServiceError
) -> JSONResponse:
    if not is_managed_document_path(request.url.path):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": "Internal Server Error"},
        )
    return document_error_response(exc.status_code, exc.code, exc.message, exc.details)


async def handle_document_storage_error(
    request: Request, exc: sqlite3.Error
) -> JSONResponse:
    if not is_managed_document_path(request.url.path):
        return PlainTextResponse("Internal Server Error", status_code=500)
    return document_error_response(
        503,
        "storage_unavailable",
        "문서 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
    )


async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if not is_managed_document_path(request.url.path):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return document_error_response(
        exc.status_code,
        "request_error",
        "요청을 처리할 수 없습니다.",
    )


async def handle_unexpected_error(request: Request, exc: Exception):
    if is_managed_document_path(request.url.path):
        return document_error_response(
            500, "internal_error", "문서 요청을 처리하지 못했습니다."
        )
    return PlainTextResponse("Internal Server Error", status_code=500)


async def handle_knowledge_storage_error(request: Request, exc: DocumentStorageError):
    return JSONResponse(
        status_code=503,
        content=AnswerResponse(
            ok=False, text="", reason="문서 저장소를 사용할 수 없습니다."
        ).model_dump(),
        headers={"Cache-Control": "no-store"},
    )


async def handle_classification_error(request: Request, exc: Exception):
    return JSONResponse(
        status_code=503,
        content=AnswerResponse(
            ok=False, text="", reason="분류 모델을 사용할 수 없습니다."
        ).model_dump(),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(LLMResponseError, handle_llm_response_error)
    app.add_exception_handler(DocumentServiceError, handle_document_service_error)
    app.add_exception_handler(sqlite3.Error, handle_document_storage_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
    app.add_exception_handler(DocumentStorageError, handle_knowledge_storage_error)
    app.add_exception_handler(ClassificationUnavailable, handle_classification_error)
    app.add_exception_handler(ClassificationInferenceError, handle_classification_error)
