"""Framework-independent operations for managed documents."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.documents.repository import (
    DocumentRepository,
    DuplicateDocumentError,
    IdempotencyConflictError,
    RevisionConflictError,
)
from app.retrieval.sync import RetrievalWriterBusy, RetrievalWriterUnavailable


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
    retrieval_sync=None,
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
        retrieval_sync=retrieval_sync,
    )


def withdraw_document(
    repository: DocumentRepository,
    document_id: str,
    expected_version: int,
    idempotency_key: str | None,
    retrieval_sync=None,
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
        retrieval_sync=retrieval_sync,
    )


def _idempotent_write(
    repository: DocumentRepository,
    raw_key: str | None,
    method_path: str,
    payload: dict[str, Any],
    success_status: int,
    operation: Callable[[Any], dict[str, Any]],
    retrieval_sync=None,
) -> tuple[int, dict[str, Any]]:
    key = _validated_idempotency_key(raw_key)
    request_hash = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    try:
        lock = (
            retrieval_sync.writer_lock()
            if retrieval_sync is not None
            else nullcontext()
        )
        with lock:
            try:
                with repository.transaction() as connection:
                    replay = repository.lookup_idempotency(
                        connection, key, method_path, request_hash
                    )
                    if replay is not None:
                        result = replay
                    else:
                        response = operation(connection)
                        repository.store_idempotency(
                            connection,
                            key,
                            method_path,
                            request_hash,
                            success_status,
                            response,
                        )
                        result = success_status, response
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
                    "이 Idempotency-Key는 다른 요청에 사용되었거나 시연 초기화로 무효화되었습니다. 최신 문서를 확인해주세요.",
                ) from exc
            except RevisionConflictError as exc:
                raise _revision_conflict(exc.current_version) from exc

            try:
                if retrieval_sync is not None:
                    retrieval_sync.reconcile_current()
            except Exception as exc:
                raise _retrieval_sync_error(document_saved=True) from exc
            return result
    except RetrievalWriterBusy as exc:
        raise _retrieval_sync_error(document_saved=False, busy=True) from exc
    except RetrievalWriterUnavailable as exc:
        raise _retrieval_sync_error(document_saved=False) from exc


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


def _retrieval_sync_error(*, document_saved: bool, busy: bool = False):
    code = "retrieval_sync_busy" if busy else "retrieval_sync_failed"
    if busy:
        message = "검색 색인 작업이 진행 중이라 이번 요청을 처리하지 못했습니다. 잠시 후 같은 요청으로 다시 시도해주세요."
    elif document_saved:
        message = "문서 변경은 저장됐지만 검색 반영이 완료되지 않았습니다. 같은 요청을 다시 시도해주세요."
    else:
        message = "검색 반영 준비를 확인하지 못해 이번 요청의 문서 변경을 시작하지 않았습니다. 설정을 확인한 뒤 다시 시도해주세요."
    return DocumentServiceError(
        503,
        code,
        message,
        {"document_saved": document_saved, "retryable": True},
    )


def preview_maintenance(repository, action, source, retrieval_sync=None):
    import sqlite3

    from app.documents.maintenance import prepared_baseline, state_token

    try:
        lock = (
            retrieval_sync.writer_lock()
            if retrieval_sync is not None and action == "restore"
            else nullcontext()
        )
        with lock:
            if retrieval_sync is not None and action == "restore":
                try:
                    retrieval_sync.preflight_restore()
                except Exception as exc:
                    raise _retrieval_sync_error(document_saved=False) from exc
            with (
                prepared_baseline(repository, action, source) as (_, raw, count),
                repository.transaction(immediate=False) as connection,
            ):
                return {
                    "action": action,
                    "total_count": connection.execute(
                        "SELECT COUNT(*) FROM documents"
                    ).fetchone()[0],
                    "restored_count": count,
                    "expected_state": state_token(connection, action, raw),
                }
    except RetrievalWriterBusy as exc:
        raise _retrieval_sync_error(document_saved=False, busy=True) from exc
    except RetrievalWriterUnavailable as exc:
        raise _retrieval_sync_error(document_saved=False) from exc
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise DocumentServiceError(
            503,
            "maintenance_unavailable",
            "문서 전체 관리 정보를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.",
        ) from exc


def maintain_documents(
    repository, action, expected_state, key, source, retrieval_sync=None
):
    import sqlite3
    from datetime import UTC

    from app.documents.maintenance import (
        prepared_baseline,
        replacement_backup,
        state_token,
    )
    from app.documents.reset import ResetBusyError, _replace, reset_lock

    try:
        uuid.UUID(key or "")
    except (ValueError, TypeError) as exc:
        raise DocumentServiceError(
            422, "invalid_idempotency_key", "유효한 Idempotency-Key가 필요합니다."
        ) from exc
    payload_hash = hashlib.sha256(
        json.dumps([action, expected_state]).encode()
    ).hexdigest()
    try:
        lock = (
            retrieval_sync.writer_lock()
            if retrieval_sync is not None
            else nullcontext()
        )
        with lock, reset_lock(repository.path):
            with repository.transaction() as connection:
                replay = repository.lookup_idempotency(
                    connection,
                    key,
                    "POST /documents/maintenance",
                    payload_hash,
                )
            if replay is not None:
                result = replay[1]
                operation_replayed = True
            else:
                operation_replayed = False
                if retrieval_sync is not None and action == "restore":
                    try:
                        retrieval_sync.preflight_restore()
                    except Exception as exc:
                        raise _retrieval_sync_error(document_saved=False) from exc
                with (
                    prepared_baseline(repository, action, source) as (
                        seed,
                        raw,
                        count,
                    ),
                    repository.transaction() as connection,
                ):
                    if state_token(connection, action, raw) != expected_state:
                        raise DocumentServiceError(
                            409,
                            "maintenance_state_changed",
                            "문서 또는 기본 자료가 변경되었습니다. 현재 상태를 다시 확인해주세요.",
                        )
                    deleted = connection.execute(
                        "SELECT COUNT(*) FROM documents"
                    ).fetchone()[0]
                    with replacement_backup(repository, action, raw):
                        _replace(connection, seed)
                        result = {
                            "action": action,
                            "deleted_count": deleted,
                            "restored_count": count,
                            "completed_at": datetime.now(UTC).isoformat(),
                        }
                        repository.store_idempotency(
                            connection,
                            key,
                            "POST /documents/maintenance",
                            payload_hash,
                            200,
                            result,
                        )
                        connection.commit()
            if retrieval_sync is not None:
                try:
                    if action == "restore":
                        if operation_replayed:
                            retrieval_sync.preflight_restore()
                        retrieval_sync.restore_current()
                    else:
                        retrieval_sync.reconcile_current()
                except Exception as exc:
                    raise _retrieval_sync_error(document_saved=True) from exc
            return result
    except IdempotencyConflictError as exc:
        raise DocumentServiceError(
            409,
            "idempotency_conflict",
            "다른 요청에 사용된 키입니다. 상태를 다시 확인해주세요.",
        ) from exc
    except ResetBusyError as exc:
        raise DocumentServiceError(
            409,
            "maintenance_busy",
            "다른 문서 전체 관리 작업이 진행 중입니다. 잠시 후 다시 확인해주세요.",
        ) from exc
    except RetrievalWriterBusy as exc:
        raise _retrieval_sync_error(document_saved=False, busy=True) from exc
    except RetrievalWriterUnavailable as exc:
        raise _retrieval_sync_error(document_saved=False) from exc
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise DocumentServiceError(
            503,
            "maintenance_unavailable",
            "문서 전체 관리 결과를 확인할 수 없습니다. 같은 요청으로 다시 확인해주세요.",
        ) from exc
