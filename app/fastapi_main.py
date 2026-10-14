import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.answer_text import LLM_RESPONSE_ERROR, LLMResponseError
from app.document_http import (
    ManagedDocumentHttpMiddleware,
    document_error_response,
    handle_document_validation_error,
    is_managed_document_path,
)
from app.document_repository import DocumentRepository
from app.routers import (
    assistant,
    classification,
    documents,
    managed_documents,
    questions,
)
from app.schemas import AnswerResponse
from app.services.document_service import DocumentServiceError


def _document_database_path() -> Path:
    configured_path = os.environ.get("SANAEBI_DOCUMENT_DB")
    if configured_path:
        return Path(configured_path).expanduser()
    return Path(__file__).resolve().parent.parent / "var" / "documents.sqlite3"


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = DocumentRepository(_document_database_path())
    repository.initialize()
    application.state.document_repository = repository
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(ManagedDocumentHttpMiddleware)
app.include_router(questions.router)
app.include_router(documents.router)
app.include_router(managed_documents.router)
app.include_router(classification.router)
app.include_router(assistant.router)


@app.get("/")
def home():
    return {"message": "FastAPI 서버가 실행 중입니다."}


# 오류가 나면 handler가 오류를 찾고 오류 내용을 말해줌
@app.exception_handler(RequestValidationError)
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
@app.exception_handler(LLMResponseError)
async def handle_llm_response_error(
    request: Request, exc: LLMResponseError
) -> JSONResponse:
    response = AnswerResponse(ok=False, text="", reason=LLM_RESPONSE_ERROR)
    return JSONResponse(status_code=502, content=response.model_dump())


@app.exception_handler(DocumentServiceError)
async def handle_document_service_error(
    request: Request, exc: DocumentServiceError
) -> JSONResponse:
    if not is_managed_document_path(request.url.path):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": "Internal Server Error"},
        )
    return document_error_response(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(sqlite3.Error)
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


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if not is_managed_document_path(request.url.path):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return document_error_response(
        exc.status_code,
        "request_error",
        "요청을 처리할 수 없습니다.",
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    if is_managed_document_path(request.url.path):
        return document_error_response(
            500, "internal_error", "문서 요청을 처리하지 못했습니다."
        )
    return PlainTextResponse("Internal Server Error", status_code=500)
