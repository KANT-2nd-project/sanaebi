"""Managed document API contracts use an isolated SQLite database."""

import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.document_http import ManagedDocumentHttpMiddleware
from app.document_repository import DocumentRepository
from app.fastapi_main import app


class ManagedDocumentsApiTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db_path = Path(directory) / "documents.sqlite3"
        self.enterContext(
            patch.dict("os.environ", {"SANAEBI_DOCUMENT_DB": str(self.db_path)})
        )
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))

    def create(self, *, title="휴가 안내", body="휴가 신청 절차", **metadata):
        return self.client.post(
            "/documents",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"title": title, "body": body, **metadata},
        )

    def test_create_and_list_keep_document_body_out_of_summaries(self):
        response = self.client.post(
            "/documents",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"title": "휴가 안내", "body": "첫 줄\n둘째 줄"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        detail = response.json()
        self.assertEqual(detail["draft"]["body"], "첫 줄\n둘째 줄")
        self.assertEqual(detail["published"], None)
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(response.headers["cache-control"], "no-store")

        listing = self.client.get("/documents")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()["total"], 1)
        summary = listing.json()["items"][0]
        self.assertEqual(summary["id"], detail["id"])
        self.assertNotIn("body", summary["draft"])
        self.assertEqual(listing.headers["cache-control"], "no-store")

    def test_idempotency_replays_create_and_rejects_changed_request(self):
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        payload = {"title": "휴가 안내", "body": "휴가 신청 절차"}

        first = self.client.post("/documents", headers=headers, json=payload)
        replay = self.client.post("/documents", headers=headers, json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(self.client.get("/documents").json()["total"], 1)

        changed = self.client.post(
            "/documents",
            headers=headers,
            json={"title": "휴가 안내", "body": "변경한 요청"},
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(changed.headers["cache-control"], "no-store")

    def test_concurrent_identical_create_requests_store_one_document(self):
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        payload = {"title": "동시 등록", "body": "한 번만 저장"}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self.client.post, "/documents", headers=headers, json=payload
                )
                for _ in range(2)
            ]
            responses = [future.result(timeout=10) for future in futures]

        self.assertEqual([response.status_code for response in responses], [201, 201])
        self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(self.client.get("/documents").json()["total"], 1)

    def test_write_requires_uuid_key_and_rejects_unknown_fields(self):
        missing_key = self.client.post(
            "/documents", json={"title": "제목", "body": "본문"}
        )
        self.assertEqual(missing_key.status_code, 400)
        self.assertEqual(missing_key.json()["error"]["code"], "invalid_idempotency_key")

        invalid_payload = self.client.post(
            "/documents",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"title": "제목", "body": "본문", "secret": "do not echo"},
        )
        self.assertEqual(invalid_payload.status_code, 422)
        self.assertEqual(invalid_payload.json()["error"]["code"], "validation_error")
        self.assertNotIn("do not echo", invalid_payload.text)
        self.assertEqual(invalid_payload.headers["cache-control"], "no-store")

    def test_compare_and_swap_preserves_the_newer_edit(self):
        created = self.create().json()
        document_id = created["id"]
        first_edit = self.client.patch(
            f"/documents/{document_id}",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 1, "title": "휴가 안내 개정"},
        )
        self.assertEqual(first_edit.status_code, 200, first_edit.text)
        self.assertEqual(first_edit.json()["record_version"], 2)

        stale_edit = self.client.patch(
            f"/documents/{document_id}",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 1, "body": "오래된 탭의 내용"},
        )
        self.assertEqual(stale_edit.status_code, 409)
        self.assertEqual(stale_edit.json()["error"]["code"], "revision_conflict")
        current = self.client.get(f"/documents/{document_id}").json()
        self.assertEqual(current["record_version"], 2)
        self.assertEqual(current["draft"]["title"], "휴가 안내 개정")
        self.assertEqual(current["draft"]["revision_number"], 2)

    def test_noop_edit_does_not_create_revision_or_advance_version(self):
        created = self.create().json()
        response = self.client.patch(
            f"/documents/{created['id']}",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 1, "title": created["draft"]["title"]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["record_version"], 1)
        self.assertEqual(response.json()["draft"]["revision_number"], 1)

    def test_edit_keeps_published_revision_and_withdraw_removes_snapshot(self):
        created = self.create().json()
        document_id = created["id"]
        published = self.client.post(
            f"/documents/{document_id}/publish",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 1, "revision_id": created["draft"]["id"]},
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["eligibility"], "eligible")

        edit = self.client.patch(
            f"/documents/{document_id}",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 2, "body": "개정 초안"},
        )
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(edit.json()["draft"]["body"], "개정 초안")
        self.assertEqual(edit.json()["published"]["body"], "휴가 신청 절차")

        repository = DocumentRepository(self.db_path)
        snapshot = repository.published_snapshot()
        self.assertEqual([item["id"] for item in snapshot], [document_id])
        self.assertEqual(snapshot[0]["draft"]["body"], "개정 초안")
        self.assertEqual(snapshot[0]["published"]["body"], "휴가 신청 절차")

        withdrawn = self.client.post(
            f"/documents/{document_id}/withdraw",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 3},
        )
        self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
        self.assertEqual(withdrawn.json()["status"], "withdrawn")
        self.assertEqual(repository.published_snapshot(), [])

    def test_future_document_is_scheduled_until_its_seoul_effective_date(self):
        effective = datetime.now(ZoneInfo("Asia/Seoul")).date() + timedelta(days=1)
        created = self.create(effective_from=effective.isoformat()).json()
        document_id = created["id"]
        published = self.client.post(
            f"/documents/{document_id}/publish",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 1, "revision_id": created["draft"]["id"]},
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["eligibility"], "scheduled")

        repository = DocumentRepository(self.db_path)
        self.assertEqual(
            repository.published_snapshot(today=effective - timedelta(days=1)), []
        )
        self.assertEqual(
            len(repository.published_snapshot(today=effective)),
            1,
        )

    def test_future_revision_cannot_replace_an_effective_publication(self):
        created = self.create().json()
        document_id = created["id"]
        published = self.client.post(
            f"/documents/{document_id}/publish",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 1, "revision_id": created["draft"]["id"]},
        )
        self.assertEqual(published.status_code, 200)

        effective = datetime.now(ZoneInfo("Asia/Seoul")).date() + timedelta(days=1)
        future_draft = self.client.patch(
            f"/documents/{document_id}",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"expected_version": 2, "effective_from": effective.isoformat()},
        )
        self.assertEqual(future_draft.status_code, 200, future_draft.text)

        rejected = self.client.post(
            f"/documents/{document_id}/publish",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "expected_version": 3,
                "revision_id": future_draft.json()["draft"]["id"],
            },
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            rejected.json()["error"]["code"], "future_revision_not_supported"
        )
        current = self.client.get(f"/documents/{document_id}").json()
        self.assertEqual(current["published"]["id"], created["draft"]["id"])
        self.assertEqual(current["record_version"], 3)

    def test_request_body_limit_allows_50000_hangul_chars_and_rejects_oversize(self):
        maximum_body = "가" * 50_000
        accepted = self.create(body=maximum_body)
        self.assertEqual(accepted.status_code, 201, accepted.text[:200])
        self.assertEqual(len(accepted.json()["draft"]["body"]), 50_000)

        rejected = self.create(title="큰 본문", body="x" * (512 * 1024))
        self.assertEqual(rejected.status_code, 413)
        self.assertEqual(rejected.json()["error"]["code"], "body_too_large")
        self.assertEqual(rejected.headers["cache-control"], "no-store")


class ManagedDocumentBodyLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_content_length_is_drained_before_413(self):
        messages = [
            {"type": "http.request", "body": b"x" * 300_000, "more_body": True},
            {"type": "http.request", "body": b"x" * 230_000, "more_body": False},
        ]
        received = 0
        downstream_called = False
        sent = []

        async def receive():
            nonlocal received
            received += 1
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        async def downstream(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True

        middleware = ManagedDocumentHttpMiddleware(downstream)
        scope = {
            "type": "http",
            "path": "/documents",
            "headers": [(b"content-length", b"530000")],
        }
        await middleware(scope, receive, send)

        self.assertEqual(received, 2)
        self.assertFalse(downstream_called)
        response_start = next(
            message for message in sent if message["type"] == "http.response.start"
        )
        self.assertEqual(response_start["status"], 413)
        self.assertIn((b"cache-control", b"no-store"), response_start["headers"])

    async def test_oversized_chunked_body_is_drained_before_413(self):
        messages = [
            {"type": "http.request", "body": b"x" * 300_000, "more_body": True},
            {"type": "http.request", "body": b"x" * 230_000, "more_body": False},
        ]
        received = 0
        downstream_called = False
        sent = []

        async def receive():
            nonlocal received
            received += 1
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        async def downstream(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True

        middleware = ManagedDocumentHttpMiddleware(downstream)
        scope = {"type": "http", "path": "/documents", "headers": []}
        await middleware(scope, receive, send)

        self.assertEqual(received, 2)
        self.assertFalse(downstream_called)
        response_start = next(
            message for message in sent if message["type"] == "http.response.start"
        )
        self.assertEqual(response_start["status"], 413)


if __name__ == "__main__":
    unittest.main()
