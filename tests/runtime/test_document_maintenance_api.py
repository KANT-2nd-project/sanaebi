import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.fastapi_main import app


class MaintenanceApiTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                "os.environ", {"SANAEBI_DOCUMENT_DB": str(root / "docs.sqlite3")}
            )
        )
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))

    def test_api_contract_clear_restore_and_replay(self):
        for action in ("restore", "clear"):
            preview = self.client.get(
                "/documents/maintenance-preview", params={"action": action}
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.headers["cache-control"], "no-store")
            payload = {
                "action": action,
                "expected_state": preview.json()["expected_state"],
            }
            headers = {"Idempotency-Key": str(uuid.uuid4())}
            first = self.client.post(
                "/documents/maintenance", json=payload, headers=headers
            )
            self.assertEqual(first.status_code, 200, first.text)
            replay = self.client.post(
                "/documents/maintenance", json=payload, headers=headers
            )
            self.assertEqual(first.json(), replay.json())
            self.assertEqual(first.headers["cache-control"], "no-store")
            self.assertNotIn("backup", first.text)
        self.assertEqual(self.client.get("/documents").json()["total"], 0)

    def test_invalid_action_key_and_client_path(self):
        self.assertEqual(
            self.client.get(
                "/documents/maintenance-preview?action=unknown"
            ).status_code,
            422,
        )
        payload = {"action": "clear", "expected_state": "a" * 64}
        self.assertEqual(
            self.client.post("/documents/maintenance", json=payload).status_code, 422
        )
        self.assertEqual(
            self.client.post(
                "/documents/maintenance",
                json={**payload, "source": "/tmp/private"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ).status_code,
            422,
        )
