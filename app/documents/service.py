"""Framework-independent operations for managed documents."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.documents.repository import (
    DocumentRepository,
    DuplicateDocumentError,
    IdempotencyConflictError,
    RevisionConflictError,
)


class DocumentServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def get_document(repository: DocumentRepository, document_id: str) -> dict[str, Any]:
    detail = repository.get(document_id)
    if detail is None:
        raise _not_found()
    return detail


def list_documents(
    repository: DocumentRepository,
    q: str = "",
    status: str = "all",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return repository.list(q=q, status=status, limit=limit, offset=offset)


def create_document(
    repository: DocumentRepository,
    fields: dict[str, Any],
    idempotency_key: str | None,
) -> tuple[int, dict[str, Any]]:
    normalized = _normalize_request_fields(fields)
    return _idempotent_write(
        repository,
        idempotency_key,
        "POST /documents",
        normalized,
        201,
        lambda connection: repository.create_in_transaction(connection, normalized),
    )


def update_document(
    repository: DocumentRepository,
    document_id: str,
    fields: dict[str, Any],
    idempotency_key: str | None,
) -> tuple[int, dict[str, Any]]:
    expected_version = fields.get("expected_version")
    changes = {key: value for key, value in fields.items() if key != "expected_version"}
    payload = {"expected_version": expected_version, **changes}

    def update(connection):
        current = repository.get_in_transaction(connection, document_id)
        if current is None:
            raise _not_found()
        _check_version(current, expected_version)
        if not changes:
            return current

        revision = current["draft"]
        merged = {
            "title": revision["title"],
            "body": revision["body"],
            "source_label": revision["source_label"],
            "source_url": revision["source_url"],
            "owner_department": revision["owner_department"],
            "effective_from": revision["effective_from"],
        }
        merged.update(changes)
        if _normalize_request_fields(merged) == {
            key: revision[key]
            for key in (
                "title",
                "body",
                "source_label",
                "source_url",
                "owner_department",
                "effective_from",
            )
        }:
            return current
        try:
            return repository.update_draft_in_transaction(
                connection, document_id, expected_version, merged
            )
        except RevisionConflictError as exc:
            raise _revision_conflict(exc.current_version) from exc

    return _idempotent_write(
        repository,
        idempotency_key,
        f"PATCH /documents/{document_id}",
        payload,
        200,
        update,
    )


def publish_document(
    repository: DocumentRepository,
    document_id: str,
    expected_version: int,
    revision_id: str,
    idempotency_key: str | None,
) -> tuple[int, dict[str, Any]]:
    payload = {"expected_version": expected_version, "revision_id": revision_id}

    def publish(connection):
        current = repository.get_in_transaction(connection, document_id)
        if current is None:
            raise _not_found()
        _check_version(current, expected_version)
        if current["draft"]["id"] != revision_id:
            raise _revision_conflict(current["record_version"])

        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        effective_from = current["draft"]["effective_from"]
        has_effective_published = (
            current["published"] is not None
            and not current["withdrawn"]
            and current["eligibility"] == "eligible"
        )
        if (
            has_effective_published
            and effective_from is not None
            and date.fromisoformat(effective_from) > today
        ):
            raise DocumentServiceError(
                409,
                "future_revision_not_supported",
                "기존 게시본이 적용 중입니다. 새 시행일에는 수동으로 다시 게시해야 합니다.",
                {"record_version": current["record_version"]},
            )
        try:
            return repository.publish_in_transaction(
                connection, document_id, expected_version, revision_id
            )
        except RevisionConflictError as exc:
            raise _revision_conflict(exc.current_version) from exc

    return _idempotent_write(
        repository,
        idempotency_key,
        f"POST /documents/{document_id}/publish",
        payload,
        200,
        publish,
    )


def withdraw_document(
    repository: DocumentRepository,
    document_id: str,
    expected_version: int,
    idempotency_key: str | None,
) -> tuple[int, dict[str, Any]]:
    payload = {"expected_version": expected_version}

    def withdraw(connection):
        current = repository.get_in_transaction(connection, document_id)
        if current is None:
            raise _not_found()
        _check_version(current, expected_version)
        if current["withdrawn"]:
            return current
        try:
            return repository.withdraw_in_transaction(
                connection, document_id, expected_version
            )
        except RevisionConflictError as exc:
            raise _revision_conflict(exc.current_version) from exc

    return _idempotent_write(
        repository,
        idempotency_key,
        f"POST /documents/{document_id}/withdraw",
        payload,
        200,
        withdraw,
    )


def _idempotent_write(
    repository: DocumentRepository,
    raw_key: str | None,
    method_path: str,
    payload: dict[str, Any],
    success_status: int,
    operation: Callable[[Any], dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    key = _validated_idempotency_key(raw_key)
    request_hash = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    try:
        with repository.transaction() as connection:
            replay = repository.lookup_idempotency(
                connection, key, method_path, request_hash
            )
            if replay is not None:
                return replay
            result = operation(connection)
            repository.store_idempotency(
                connection,
                key,
                method_path,
                request_hash,
                success_status,
                result,
            )
            return success_status, result
    except DuplicateDocumentError as exc:
        raise DocumentServiceError(
            409,
            "duplicate_document",
            "같은 제목과 본문을 가진 문서가 이미 있습니다.",
            {"id": exc.existing_id},
        ) from exc
    except IdempotencyConflictError as exc:
        raise DocumentServiceError(
            409,
            "idempotency_conflict",
            "이 Idempotency-Key는 다른 요청에 이미 사용되었습니다.",
        ) from exc
    except RevisionConflictError as exc:
        raise _revision_conflict(exc.current_version) from exc


def _normalize_request_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result = {
        "title": fields["title"],
        "body": fields["body"],
        "source_label": fields.get("source_label") or "",
        "source_url": fields.get("source_url") or None,
        "owner_department": fields.get("owner_department") or None,
        "effective_from": fields.get("effective_from"),
    }
    effective_from = result["effective_from"]
    if isinstance(effective_from, date):
        result["effective_from"] = effective_from.isoformat()
    return result


def _validated_idempotency_key(raw_key: str | None) -> str:
    try:
        return str(uuid.UUID(raw_key))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DocumentServiceError(
            400,
            "invalid_idempotency_key",
            "모든 문서 쓰기 요청에는 UUID 형식의 Idempotency-Key가 필요합니다.",
        ) from exc


def _check_version(current: dict[str, Any], expected_version: int) -> None:
    if current["record_version"] != expected_version:
        raise _revision_conflict(current["record_version"])


def _not_found() -> DocumentServiceError:
    return DocumentServiceError(404, "document_not_found", "문서를 찾을 수 없습니다.")


def _revision_conflict(current_version: int | None) -> DocumentServiceError:
    details = (
        {"record_version": current_version} if current_version is not None else None
    )
    return DocumentServiceError(
        409,
        "revision_conflict",
        "문서가 변경되었습니다. 최신 내용을 다시 확인해주세요.",
        details,
    )
