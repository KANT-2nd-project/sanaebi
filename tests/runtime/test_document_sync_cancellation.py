"""Cancelled HTTP callers must not release a still-running document writer."""

import asyncio
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx

from app.fastapi_main import app
from app.retrieval.repository import IndexRepository
from app.retrieval.sync import DocumentIndexSynchronizer


class DocumentSyncCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_publish_keeps_writer_until_sync_and_replay_is_safe(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                "os.environ",
                {
                    "SANAEBI_DOCUMENT_DB": str(root / "documents.sqlite3"),
                    "SANAEBI_RETRIEVAL_MODE": "full",
                    "SANAEBI_PUBLIC_DEMO": "0",
                },
            )
        )
        started, release = threading.Event(), threading.Event()

        class SlowRetrieval:
            calls = 0

            def reconcile(self, snapshot):
                self.calls += 1
                if self.calls == 1:
                    started.set()
                    if not release.wait(5):
                        raise RuntimeError("test release missing")
                return {"ready": True}

        async with app.router.lifespan_context(app):
            app.state.retrieval_mode = "rag"
            app.state.retrieval_sync = DocumentIndexSynchronizer(
                repository=IndexRepository(root / "index"),
                retrieval_service=SlowRetrieval(),
                document_provider=app.state.document_provider,
                baseline_path=None,
                source_path=root / "unused.jsonl",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:

                async def create(title):
                    response = await client.post(
                        "/documents",
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        json={"title": title, "body": "격리된 취소 검증 문서"},
                    )
                    self.assertEqual(response.status_code, 201, response.text)
                    return response.json()

                first, second = await create("first"), await create("second")
                key = str(uuid.uuid4())
                body = {
                    "expected_version": first["record_version"],
                    "revision_id": first["draft"]["id"],
                }
                task = asyncio.create_task(
                    client.post(
                        f"/documents/{first['id']}/publish",
                        headers={"Idempotency-Key": key},
                        json=body,
                    )
                )
                following = None
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    following = asyncio.create_task(
                        client.post(
                            f"/documents/{second['id']}/publish",
                            headers={"Idempotency-Key": str(uuid.uuid4())},
                            json={
                                "expected_version": second["record_version"],
                                "revision_id": second["draft"]["id"],
                            },
                        )
                    )
                    await asyncio.sleep(0.1)
                    self.assertFalse(following.done())
                    current = app.state.document_repository.get(second["id"])
                    self.assertIsNone(current["published"])
                finally:
                    release.set()
                    if following is not None:
                        result = await asyncio.wait_for(following, 3)
                        self.assertEqual(result.status_code, 200, result.text)
                    if not task.done():
                        await task
                replay = await client.post(
                    f"/documents/{first['id']}/publish",
                    headers={"Idempotency-Key": key},
                    json=body,
                )
                self.assertEqual(replay.status_code, 200, replay.text)
                current = app.state.document_repository.get(first["id"])
                self.assertEqual(current["record_version"], 2)
                self.assertEqual(current["published"]["id"], first["draft"]["id"])
