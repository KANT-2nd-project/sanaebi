"""Legacy registration contract, now backed by managed SQLite drafts."""

import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.documents.repository import DuplicateDocumentError
from app.schemas import AnswerResponse, DocumentRequest

router = APIRouter()


@router.post(
    "/regist-docs",
    response_model=AnswerResponse,
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        409: {"model": AnswerResponse, "description": "중복 문서"},
        503: {"model": AnswerResponse, "description": "저장소 오류"},
    },
)
def register_document(request: DocumentRequest, http_request: Request):
    body = request.doc.strip()
    fields = {
        "title": next(line.strip() for line in body.splitlines() if line.strip())[:200],
        "body": body,
        "source_label": "레거시 등록 API",
    }
    repository = http_request.app.state.document_repository
    try:
        with repository.transaction() as con:
            repository.create_in_transaction(con, fields)
    except (DuplicateDocumentError, sqlite3.Error) as exc:
        duplicate = isinstance(exc, DuplicateDocumentError)
        return JSONResponse(
            status_code=409 if duplicate else 503,
            content=AnswerResponse(
                ok=False,
                text="",
                reason="같은 문서가 이미 등록되어 있습니다."
                if duplicate
                else "문서 저장소를 사용할 수 없습니다.",
            ).model_dump(),
        )
    return AnswerResponse(ok=True, text="문서가 등록되었습니다.")
