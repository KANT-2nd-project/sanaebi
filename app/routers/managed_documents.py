"""HTTP routes for the local managed-document workflow."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from app.document_repository import DocumentRepository
from app.document_schemas import (
    CreateDocumentRequest,
    DocumentCapabilitiesResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    PublishDocumentRequest,
    UpdateDocumentRequest,
    WithdrawDocumentRequest,
)
from app.services import document_service

router = APIRouter()


def _repository(request: Request) -> DocumentRepository:
    return request.app.state.document_repository


def _json_response(status_code: int, model, data: dict) -> JSONResponse:
    checked = model.model_validate(data)
    return JSONResponse(
        status_code=status_code, content=checked.model_dump(mode="json")
    )


@router.get("/documents/capabilities", response_model=DocumentCapabilitiesResponse)
def get_document_capabilities() -> DocumentCapabilitiesResponse:
    return DocumentCapabilitiesResponse()


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(
    request: Request,
    q: str = "",
    status: Literal["all", "draft", "published", "withdrawn"] = "all",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    result = document_service.list_documents(
        _repository(request), q=q, status=status, limit=limit, offset=offset
    )
    return _json_response(200, DocumentListResponse, result)


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(document_id: UUID, request: Request):
    detail = document_service.get_document(_repository(request), str(document_id))
    return _json_response(200, DocumentDetailResponse, detail)


@router.post(
    "/documents",
    response_model=DocumentDetailResponse,
    status_code=201,
)
def create_document(
    payload: CreateDocumentRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    status_code, detail = document_service.create_document(
        _repository(request), payload.model_dump(mode="json"), idempotency_key
    )
    return _json_response(status_code, DocumentDetailResponse, detail)


@router.patch("/documents/{document_id}", response_model=DocumentDetailResponse)
def update_document(
    document_id: UUID,
    payload: UpdateDocumentRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    status_code, detail = document_service.update_document(
        _repository(request),
        str(document_id),
        payload.model_dump(exclude_unset=True, mode="json"),
        idempotency_key,
    )
    return _json_response(status_code, DocumentDetailResponse, detail)


@router.post("/documents/{document_id}/publish", response_model=DocumentDetailResponse)
def publish_document(
    document_id: UUID,
    payload: PublishDocumentRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    status_code, detail = document_service.publish_document(
        _repository(request),
        str(document_id),
        payload.expected_version,
        str(payload.revision_id),
        idempotency_key,
    )
    return _json_response(status_code, DocumentDetailResponse, detail)


@router.post("/documents/{document_id}/withdraw", response_model=DocumentDetailResponse)
def withdraw_document(
    document_id: UUID,
    payload: WithdrawDocumentRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    status_code, detail = document_service.withdraw_document(
        _repository(request),
        str(document_id),
        payload.expected_version,
        idempotency_key,
    )
    return _json_response(status_code, DocumentDetailResponse, detail)
