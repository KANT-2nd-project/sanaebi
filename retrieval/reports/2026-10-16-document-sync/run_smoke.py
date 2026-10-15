"""Exercise document-to-RAG synchronization with local Tiny and temporary SQLite.

No model download or generation API call is made. The selected local encoder is
used both to prepare the disposable baseline bundle and to index the test
document. Every SQLite database is created below a temporary directory and
removed when the process exits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timed(action):
    started = time.perf_counter()
    result = action()
    return result, round((time.perf_counter() - started) * 1000, 2)


def _assert_status(response, expected, phase):
    if response.status_code != expected:
        raise AssertionError(
            f"{phase}: expected HTTP {expected}, received {response.status_code}: "
            f"{response.text[:1200]}"
        )


class _SearchClassifier:
    def predict(self, _question):
        return "SEARCH_KNOWLEDGE"


class _CapturingAnswerer:
    def __init__(self):
        self.calls = []

    def answer_retrieved(self, question, context):
        evidence = tuple(context.evidence)
        self.calls.append(
            {
                "question": question,
                "evidence": evidence,
                "snapshot_fingerprint": context.snapshot_fingerprint,
            }
        )
        return "\n".join(item.text for item in evidence)

    async def aclose(self):
        return None


def run(embedding_path: Path, source_path: Path, output_path: Path):
    embedding_path = embedding_path.expanduser().resolve()
    source_path = source_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if not (embedding_path / "retrieval-model.json").is_file():
        raise FileNotFoundError(embedding_path / "retrieval-model.json")

    from app.retrieval.baseline import prepare_baseline
    from app.retrieval.config import MODEL_ID, MODEL_REVISION, SPEC_ID
    from app.retrieval.embedding import TinyEmbedder

    report = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "started_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "git_head": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "git_worktree_clean": not bool(
            subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "implementation_files_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in (
                "app/fastapi_main.py",
                "app/documents/router.py",
                "app/documents/service.py",
                "app/retrieval/sync.py",
                "scripts/index_documents.py",
            )
            if (ROOT / relative).is_file()
        },
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_affinity_count": len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else os.cpu_count(),
        "embedding": {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "spec_id": SPEC_ID,
            "local_files_only": True,
            "hub_offline": True,
        },
        "source": {
            "repo_relative_path": str(source_path.relative_to(ROOT))
            if source_path.is_relative_to(ROOT)
            else "operator-supplied local file",
            "sha256": _sha256(source_path),
        },
        "isolation": {
            "document_database": "temporary SQLite; removed after the run",
            "retrieval_database": "temporary SQLite; removed after the run",
            "baseline_bundle": "temporary SQLite; removed after the run",
            "real_generation_calls": 0,
        },
        "phases": {},
        "checks": {},
    }

    temporary_root = None
    with tempfile.TemporaryDirectory(prefix="sanaebi-document-sync-") as raw_temp:
        temporary_root = Path(raw_temp)
        temporary = temporary_root
        database_path = temporary / "documents.sqlite3"
        retrieval_root = temporary / "retrieval"
        baseline_root = temporary / "baseline"
        baseline_embedder = TinyEmbedder(embedding_path)
        baseline_counts = {"calls": 0, "vectors": 0}
        original_baseline_encode = baseline_embedder.encode_documents

        def count_baseline_encode(texts):
            baseline_counts["calls"] += 1
            baseline_counts["vectors"] += len(texts)
            return original_baseline_encode(texts)

        baseline_embedder.encode_documents = count_baseline_encode
        _, baseline_ms = _timed(lambda: baseline_embedder.warmup())
        baseline_path, prepare_ms = _timed(
            lambda: prepare_baseline(source_path, baseline_root, baseline_embedder)
        )
        report["phases"]["baseline_bundle_preparation"] = {
            "warmup_ms": baseline_ms,
            "elapsed_ms": prepare_ms,
            "document_encode_calls": baseline_counts["calls"],
            "document_vectors_encoded": baseline_counts["vectors"],
            "bundle_created": baseline_path.is_file(),
        }

        environment = {
            "SANAEBI_DOCUMENT_DB": str(database_path),
            "SANAEBI_RETRIEVAL_MODE": "rag",
            "SANAEBI_RETRIEVAL_ROOT": str(retrieval_root),
            "SANAEBI_RETRIEVAL_BASELINE": str(baseline_path),
            "SANAEBI_RETRIEVAL_SOURCE": str(source_path),
            "SANAEBI_EMBEDDING_PATH": str(embedding_path),
            "SANAEBI_ROUTING_MODE": "gate",
            "SANAEBI_ANSWER_PROVIDER": "openai",
            "SANAEBI_PUBLIC_DEMO": "0",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        with patch.dict(os.environ, environment):
            from fastapi.testclient import TestClient

            from app.fastapi_main import app

            with TestClient(app, raise_server_exceptions=False) as client:
                app.state.classifier = _SearchClassifier()
                answerer = _CapturingAnswerer()
                app.state.answerer = answerer
                retriever = app.state.retriever
                embedder = retriever.embedder
                calls = {
                    "attempts": 0,
                    "vectors": 0,
                    "fail_next": False,
                    "last_encode_completed_at": None,
                }
                call_lock = threading.Lock()
                original_encode = embedder.encode_documents

                def count_sync_encode(texts):
                    with call_lock:
                        calls["attempts"] += 1
                        calls["vectors"] += len(texts)
                        fail = calls["fail_next"]
                        calls["fail_next"] = False
                    if fail:
                        raise RuntimeError("injected one-shot embedding failure")
                    result = original_encode(texts)
                    with call_lock:
                        calls["last_encode_completed_at"] = time.perf_counter()
                    return result

                embedder.encode_documents = count_sync_encode

                title = "RAG 문서 변경 반영 시연"
                code_a = "SYNC-SMOKE-724-A"
                code_b = "SYNC-SMOKE-941-B"
                body_a = (
                    f"로컬 RAG 동기화 시연을 위한 확인 코드입니다. 확인 코드는 {code_a}입니다. "
                    "게시 요청 성공 응답 직후 검색에서 찾을 수 있어야 합니다."
                )
                body_b = (
                    f"수정된 로컬 RAG 동기화 시연을 위한 새 확인 코드입니다. "
                    f"새 확인 코드는 {code_b}입니다. 이전 확인 코드는 폐기되었습니다."
                )
                question_a = "로컬 RAG 동기화 시연의 확인 코드는 무엇인가요?"
                question_b = "수정된 로컬 RAG 동기화 시연의 새 확인 코드는 무엇인가요?"
                calls_before_draft = dict(calls)
                create_key = str(uuid.uuid4())
                created, elapsed = _timed(
                    lambda: client.post(
                        "/documents",
                        headers={"Idempotency-Key": create_key},
                        json={"title": title, "body": body_a},
                    )
                )
                _assert_status(created, 201, "create draft")
                detail = created.json()
                document_id = detail["id"]
                draft_encode_calls = calls["attempts"] - calls_before_draft["attempts"]
                report["phases"]["create_draft"] = {
                    "http_status": created.status_code,
                    "elapsed_ms": elapsed,
                    "document_encode_calls": draft_encode_calls,
                }
                assert draft_encode_calls == 0, "draft save must not embed"

                publish_payload = {
                    "expected_version": detail["record_version"],
                    "revision_id": detail["draft"]["id"],
                }
                publish_key = str(uuid.uuid4())
                with call_lock:
                    calls["fail_next"] = True
                before_failed_publish = dict(calls)
                failed_publish, failure_ms = _timed(
                    lambda: client.post(
                        f"/documents/{document_id}/publish",
                        headers={"Idempotency-Key": publish_key},
                        json=publish_payload,
                    )
                )
                _assert_status(failed_publish, 503, "injected publish failure")
                failed_payload = failed_publish.json()
                after_failed = client.get(f"/documents/{document_id}")
                _assert_status(after_failed, 200, "read committed publish")
                after_failed_detail = after_failed.json()
                committed_after_failure = (
                    after_failed_detail["published"]["id"] == detail["draft"]["id"]
                )
                assert committed_after_failure, (
                    "publish DB commit must survive index failure"
                )
                report["phases"]["publish_failure"] = {
                    "http_status": failed_publish.status_code,
                    "error_code": failed_payload.get("error", {}).get("code"),
                    "elapsed_ms": failure_ms,
                    "document_encode_calls": calls["attempts"]
                    - before_failed_publish["attempts"],
                    "document_vectors_attempted": calls["vectors"]
                    - before_failed_publish["vectors"],
                    "published_revision_preserved": committed_after_failure,
                    "public_error_details": failed_payload.get("error", {}).get(
                        "details"
                    ),
                }
                assert committed_after_failure

                before_retry = dict(calls)
                retry_response, retry_ms = _timed(
                    lambda: client.post(
                        f"/documents/{document_id}/publish",
                        headers={"Idempotency-Key": publish_key},
                        json=publish_payload,
                    )
                )
                _assert_status(retry_response, 200, "same-key publish retry")
                retry_response_completed_at = time.perf_counter()
                retry_waited_for_embedding = (
                    calls["last_encode_completed_at"] is not None
                    and calls["last_encode_completed_at"] <= retry_response_completed_at
                )
                after_retry_detail = client.get(f"/documents/{document_id}").json()
                with app.state.document_repository.transaction(
                    immediate=False
                ) as connection:
                    revision_count = connection.execute(
                        "SELECT COUNT(*) FROM document_revisions WHERE document_id=?",
                        (document_id,),
                    ).fetchone()[0]
                assert after_retry_detail["published"]["id"] == detail["draft"]["id"]
                assert revision_count == 1, "retry must not add a duplicate revision"
                assert retry_waited_for_embedding
                report["phases"]["publish_retry"] = {
                    "http_status": retry_response.status_code,
                    "elapsed_ms": retry_ms,
                    "document_encode_calls": calls["attempts"]
                    - before_retry["attempts"],
                    "document_vectors_attempted": calls["vectors"]
                    - before_retry["vectors"],
                    "revision_count": revision_count,
                    "same_published_revision": after_retry_detail["published"]["id"]
                    == detail["draft"]["id"],
                    "embedding_completed_before_success_response": retry_waited_for_embedding,
                }

                def ask(question):
                    return client.post("/ask", json={"question": question})

                searched, first_search_ms = _timed(lambda: ask(question_a))
                _assert_status(searched, 200, "immediate search after publish retry")
                first_evidence = answerer.calls[-1]["evidence"]
                first_hit = any(code_a in item.text for item in first_evidence)
                assert first_hit, (
                    "published content must be searchable before response completion"
                )
                report["phases"]["search_after_publish"] = {
                    "http_status": searched.status_code,
                    "elapsed_ms": first_search_ms,
                    "expected_code_found": first_hit,
                    "selected_evidence_count": len(first_evidence),
                    "top_score": first_evidence[0].score,
                    "fake_generator_calls": len(answerer.calls),
                }

                current = client.get(f"/documents/{document_id}").json()
                before_edit = dict(calls)
                edited, edit_ms = _timed(
                    lambda: client.patch(
                        f"/documents/{document_id}",
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        json={
                            "expected_version": current["record_version"],
                            "body": body_b,
                        },
                    )
                )
                _assert_status(edited, 200, "draft edit")
                report["phases"]["edit_draft"] = {
                    "http_status": edited.status_code,
                    "elapsed_ms": edit_ms,
                    "document_encode_calls": calls["attempts"]
                    - before_edit["attempts"],
                }
                assert calls["attempts"] == before_edit["attempts"]
                edit_draft_encode_calls = calls["attempts"] - before_edit["attempts"]

                edited_detail = edited.json()
                publish_update_payload = {
                    "expected_version": edited_detail["record_version"],
                    "revision_id": edited_detail["draft"]["id"],
                }
                before_republish = dict(calls)
                republished, republish_ms = _timed(
                    lambda: client.post(
                        f"/documents/{document_id}/publish",
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        json=publish_update_payload,
                    )
                )
                _assert_status(republished, 200, "republish updated draft")
                republish_encode_calls = (
                    calls["attempts"] - before_republish["attempts"]
                )
                republish_response_completed_at = time.perf_counter()
                republish_waited_for_embedding = (
                    republish_encode_calls > 0
                    and calls["last_encode_completed_at"] is not None
                    and calls["last_encode_completed_at"]
                    <= republish_response_completed_at
                )
                assert republish_waited_for_embedding
                updated_search, updated_search_ms = _timed(lambda: ask(question_b))
                _assert_status(updated_search, 200, "immediate search after republish")
                updated_evidence = answerer.calls[-1]["evidence"]
                updated_hit = any(code_b in item.text for item in updated_evidence)
                stale_hit = any(code_a in item.text for item in updated_evidence)
                assert updated_hit and not stale_hit, (
                    "search must return current published revision only"
                )
                report["phases"]["republish_update"] = {
                    "http_status": republished.status_code,
                    "elapsed_ms": republish_ms,
                    "document_encode_calls": republish_encode_calls,
                    "embedding_completed_before_success_response": republish_waited_for_embedding,
                    "immediate_search_elapsed_ms": updated_search_ms,
                    "new_code_found": updated_hit,
                    "old_code_excluded": not stale_hit,
                    "selected_evidence_count": len(updated_evidence),
                }

                current = client.get(f"/documents/{document_id}").json()
                before_withdraw = dict(calls)
                answer_calls_before_withdraw = len(answerer.calls)
                withdrawn, withdraw_ms = _timed(
                    lambda: client.post(
                        f"/documents/{document_id}/withdraw",
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        json={"expected_version": current["record_version"]},
                    )
                )
                _assert_status(withdrawn, 200, "withdraw")
                withdrawn_ask, withdrawn_ask_ms = _timed(lambda: ask(question_b))
                _assert_status(withdrawn_ask, 200, "ask after withdraw")
                withdraw_no_hit = len(answerer.calls) == answer_calls_before_withdraw
                assert calls["attempts"] == before_withdraw["attempts"]
                assert withdraw_no_hit, (
                    "withdrawn evidence must not reach the fake generator"
                )
                report["phases"]["withdraw"] = {
                    "http_status": withdrawn.status_code,
                    "elapsed_ms": withdraw_ms,
                    "document_encode_calls": calls["attempts"]
                    - before_withdraw["attempts"],
                    "immediate_ask_elapsed_ms": withdrawn_ask_ms,
                    "withdrawn_code_excluded": withdraw_no_hit,
                    "fake_generator_calls": len(answerer.calls),
                }

                preview_clear = client.get(
                    "/documents/maintenance-preview", params={"action": "clear"}
                )
                _assert_status(preview_clear, 200, "clear preview")
                before_clear = dict(calls)
                cleared, clear_ms = _timed(
                    lambda: client.post(
                        "/documents/maintenance",
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        json={
                            "action": "clear",
                            "expected_state": preview_clear.json()["expected_state"],
                        },
                    )
                )
                _assert_status(cleared, 200, "clear all documents")
                assert calls["attempts"] == before_clear["attempts"]
                empty_snapshot = app.state.document_provider.snapshot()
                empty_status = retriever.status(empty_snapshot)
                assert empty_status["ready"] and empty_status["expected"] == 0
                report["phases"]["clear"] = {
                    "http_status": cleared.status_code,
                    "elapsed_ms": clear_ms,
                    "document_encode_calls": calls["attempts"]
                    - before_clear["attempts"],
                    "search_status": empty_status,
                }

                preview_restore = client.get(
                    "/documents/maintenance-preview", params={"action": "restore"}
                )
                _assert_status(preview_restore, 200, "restore preview")
                before_restore = dict(calls)
                restored, restore_ms = _timed(
                    lambda: client.post(
                        "/documents/maintenance",
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        json={
                            "action": "restore",
                            "expected_state": preview_restore.json()["expected_state"],
                        },
                    )
                )
                _assert_status(restored, 200, "restore baseline documents and vectors")
                after_restore_snapshot = app.state.document_provider.snapshot()
                after_restore_status = retriever.status(after_restore_snapshot)
                assert calls["attempts"] == before_restore["attempts"], (
                    "baseline restore must reuse vectors without document inference"
                )
                assert after_restore_status["ready"]
                restore_query = "유급 단기 병가의 연간 최대 일수는 며칠인가요?"
                restored_search, restored_search_ms = _timed(lambda: ask(restore_query))
                _assert_status(
                    restored_search, 200, "search immediately after baseline restore"
                )
                restored_evidence = answerer.calls[-1]["evidence"]
                assert restored_evidence, (
                    "restored baseline must be immediately searchable"
                )
                report["phases"]["baseline_restore"] = {
                    "http_status": restored.status_code,
                    "elapsed_ms": restore_ms,
                    "document_encode_calls": calls["attempts"]
                    - before_restore["attempts"],
                    "document_vectors_attempted": calls["vectors"]
                    - before_restore["vectors"],
                    "search_status": after_restore_status,
                    "immediate_search_elapsed_ms": restored_search_ms,
                    "query": restore_query,
                    "selected_titles": list(
                        dict.fromkeys(item.title for item in restored_evidence)
                    ),
                    "selected_evidence_count": len(restored_evidence),
                    "top_score": restored_evidence[0].score,
                    "fake_generator_calls": len(answerer.calls),
                }

                report["checks"] = {
                    "draft_saves_skip_document_embedding": draft_encode_calls == 0
                    and edit_draft_encode_calls == 0,
                    "failed_publish_preserves_document_and_returns_503": committed_after_failure
                    and failed_publish.status_code == 503,
                    "same_key_retry_recovers_without_duplicate_revision": retry_response.status_code
                    == 200
                    and revision_count == 1,
                    "publish_success_is_searchable_immediately": first_hit
                    and retry_waited_for_embedding,
                    "republish_replaces_stale_search_evidence": updated_hit
                    and not stale_hit,
                    "withdraw_excludes_old_vectors": withdraw_no_hit,
                    "clear_leaves_empty_search_ready": empty_status["ready"]
                    and empty_status["expected"] == 0,
                    "baseline_restore_uses_zero_document_embeddings": calls["attempts"]
                    == before_restore["attempts"],
                    "baseline_is_searchable_immediately": bool(restored_evidence),
                    "fake_generator_only": report["isolation"]["real_generation_calls"]
                    == 0,
                }
                if not all(report["checks"].values()):
                    failed = [
                        name for name, passed in report["checks"].items() if not passed
                    ]
                    raise AssertionError(f"smoke checks failed: {failed}")

    report["final"] = {
        "temporary_workspace_removed": temporary_root is not None
        and not temporary_root.exists(),
        "production_access": False,
        "real_llm_calls": 0,
    }
    assert report["final"]["temporary_workspace_removed"]
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["finished_at_kst"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "evidence": str(output_path),
                "checks": report["checks"],
            },
            ensure_ascii=False,
        )
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedding-path", type=Path, required=True)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data/company-knowledge/documents.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "evidence/actual-tiny-smoke.json",
    )
    args = parser.parse_args()
    run(args.embedding_path, args.source, args.output)


if __name__ == "__main__":
    main()
