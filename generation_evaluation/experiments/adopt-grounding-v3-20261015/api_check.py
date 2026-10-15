"""Replay the recorded API experiment; private snapshot is never committed."""

import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock, patch

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app import fastapi_main
from app.dependencies import get_classifier
from generation.presets import load_runtime_settings
from generation.providers import build_managed_model_call, to_messages
from generation_evaluation.budget import actual_cost, reserve_cost

parser = argparse.ArgumentParser(
    description="Two real-generation HTTP checks against a private snapshot copy"
)
parser.add_argument("--env-file", type=Path, required=True)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
load_dotenv(args.env_file)
root = Path.cwd()
spec = importlib.util.spec_from_file_location(
    "experiment",
    root / "generation_evaluation/experiments/answer-grounding-20261015/run.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
output = args.output
ledger = module.ledger_at(output)
settings = load_runtime_settings(root)
assert settings.prompt_profile == "examples_answer_scope_v3"
real = build_managed_model_call(settings.config)
records = []


class Budgeted:
    def __call__(self, prompt):
        rid = f"api-{len(records) + 1}"
        ledger.reserve(
            rid,
            "final",
            reserve_cost(to_messages(prompt), settings.config.max_output_tokens),
        )
        started = perf_counter()
        response = real(prompt)
        cost = actual_cost(
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
            {},
        )
        ledger.settle(rid, cost)
        records.append(
            {
                "request_id": rid,
                "profile": settings.prompt_profile,
                "config": asdict(settings.config),
                "prompt_sha256": hashlib.sha256(
                    json.dumps(
                        asdict(prompt), ensure_ascii=False, sort_keys=True
                    ).encode()
                ).hexdigest(),
                "response": asdict(response),
                "seconds": perf_counter() - started,
                "estimated_dollars": cost,
            }
        )
        return response

    async def aclose(self):
        await real.aclose()


with (
    tempfile.TemporaryDirectory() as temp,
    patch.dict(
        os.environ,
        {
            "SANAEBI_DOCUMENT_DB": str(Path(temp) / "documents.sqlite3"),
            "TRACE_DIR": "",
            "SANAEBI_ANSWER_PROVIDER": "openai",
        },
    ),
    patch("app.answering.adapter.build_managed_model_call", return_value=Budgeted()),
):
    classifier = Mock()
    classifier.predict.return_value = "SEARCH_KNOWLEDGE"
    fastapi_main.app.dependency_overrides[get_classifier] = lambda: classifier
    try:
        with TestClient(fastapi_main.app) as client:
            snapshot = json.loads((args.snapshot).read_text())
            for doc in snapshot:
                created = client.post(
                    "/documents",
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    json={"title": doc["title"], "body": doc["document"]},
                )
                assert created.status_code == 201, created.text
                d = created.json()
                published = client.post(
                    f"/documents/{d['id']}/publish",
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    json={
                        "expected_version": d["record_version"],
                        "revision_id": d["draft"]["id"],
                    },
                )
                assert published.status_code == 200, published.text
            for route, q in [
                ("/ask", "배포 실패했을 때 행동"),
                ("/assistant", "배포 실패 시 실행할 롤백 명령어는?"),
            ]:
                body = (
                    {"question": q}
                    if route == "/ask"
                    else {
                        "response": {"ok": True, "text": q, "reason": ""},
                        "classification_label": "SEARCH_KNOWLEDGE",
                    }
                )
                r = client.post(route, json=body)
                record = records[-1]
                record.update(
                    route=route,
                    question=q,
                    http_status=r.status_code,
                    http_response=r.json(),
                    document_count=len(snapshot),
                    snapshot_file_sha256=hashlib.sha256(
                        (args.snapshot).read_bytes()
                    ).hexdigest(),
                    classification="fake SEARCH_KNOWLEDGE; real generation and SQLite",
                )
                with (output / f"{record['request_id']}.json").open("x") as saved:
                    saved.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                print(route, r.status_code, r.json(), flush=True)
    finally:
        fastapi_main.app.dependency_overrides.clear()
