"""Safety contracts for the paired full/RAG answer evaluation runner."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from generation.types import ModelResponse
from generation_evaluation.budget import BudgetExceeded
from retrieval.experiments import answers


class FakeManagedClient:
    def __init__(self, *, unknown_usage=False, error=None, raw_text=None):
        self.calls = []
        self.unknown_usage = unknown_usage
        self.error = error
        self.raw_text = raw_text or '{"answer":"확인된 답변입니다."}'
        self.closed = False

    def __call__(self, prompt):
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return ModelResponse(
            raw_text=self.raw_text,
            input_tokens=None if self.unknown_usage else 20,
            output_tokens=5,
            finish_reason="stop",
        )

    async def aclose(self):
        self.closed = True


class AnswerEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "evaluation"
        self.artifacts.mkdir()
        self.model = self.root / "tiny"
        self.model.mkdir()
        (self.model / "retrieval-model.json").write_text(
            json.dumps(answers.MODEL_MANIFEST), encoding="utf-8"
        )
        self.env_file = self.root / ".env"
        self.env_file.write_text("OPENAI_API_KEY=test-only\n", encoding="utf-8")
        frozen_dir = self.root / "frozen"
        frozen_dir.mkdir()
        for filename in ("cases.json", "rubric.md", "freeze.json", "pricing.json"):
            (frozen_dir / filename).write_bytes(
                (answers.DEFAULT_CASES.parent / filename).read_bytes()
            )
        self.cases_path = frozen_dir / "cases.json"
        self.case_id = json.loads(self.cases_path.read_text(encoding="utf-8"))["cases"][
            0
        ]["case_id"]
        self.client = FakeManagedClient()
        self._write_prepared()

    def _write_prepared(self):
        from app.documents.context import (
            DocumentContext,
            DocumentContextSnapshot,
        )
        from generation.documents import render_document
        from generation.profiles import build_profile_prompt

        document = DocumentContext(
            document_id="db-doc-1",
            knowledge_id="ieum-001",
            revision_id="revision-1",
            revision=1,
            title="휴가 안내",
            body="직원은 포털에서 신청합니다.",
            source_reference="document:ieum-001",
            content_hash="body-hash",
            metadata={},
        )
        snapshot = DocumentContextSnapshot((document,))
        full_documents = [
            render_document(
                document.knowledge_id,
                document.title,
                document.body,
                document.revision,
            )
        ]
        rag_documents = ["[현재 게시 문서의 발췌 근거]\n" + full_documents[0]]
        context = {
            "snapshot_fingerprint": snapshot.fingerprint,
            "spec_id": "test-spec",
            "candidate_count": 1,
            "selected_count": 1,
            "observed_at": "2026-10-15T00:00:00+00:00",
            "candidate_chunk_ids": ["chunk-1"],
            "search_config_id": "test-search",
            "evidence": [
                {
                    "knowledge_id": "ieum-001",
                    "document_id": "db-doc-1",
                    "revision_id": "revision-1",
                    "revision": 1,
                    "title": "휴가 안내",
                    "text": "직원은 포털에서 신청합니다.",
                    "source_reference": "document:ieum-001",
                    "spans": [{"start": 0, "end": 17, "kind": "body"}],
                    "chunk_ids": ["chunk-1"],
                    "score": 0.9,
                    "rank": 1,
                    "expanded_chunk_ids": [],
                }
            ],
        }
        self._write_json(
            "snapshot.json",
            {
                "snapshot_fingerprint": snapshot.fingerprint,
                "documents": [
                    {
                        "document_id": document.document_id,
                        "knowledge_id": document.knowledge_id,
                        "revision_id": document.revision_id,
                        "revision": document.revision,
                        "title": document.title,
                        "body": document.body,
                        "source_reference": document.source_reference,
                        "content_hash": document.content_hash,
                        "metadata": {},
                    }
                ],
            },
        )
        frozen_cases = json.loads(self.cases_path.read_text(encoding="utf-8"))["cases"]
        cases = []
        blind_map = {}
        for frozen_case in frozen_cases:
            case_id = frozen_case["case_id"]
            full_prompt = build_profile_prompt(
                frozen_case["question"], full_documents, "examples_answer_scope_v5"
            )
            rag_prompt = build_profile_prompt(
                frozen_case["question"], rag_documents, "examples_answer_scope_v5"
            )
            cases.append(
                {
                    **frozen_case,
                    "variants": {
                        "A": {
                            "prompt": {
                                "system": full_prompt.system,
                                "user": full_prompt.user,
                            },
                            "prompt_sha256": answers._prompt_sha(full_prompt),
                            "rendered_documents": full_documents,
                            "retrieved_context": None,
                        },
                        "B": {
                            "prompt": {
                                "system": rag_prompt.system,
                                "user": rag_prompt.user,
                            },
                            "prompt_sha256": answers._prompt_sha(rag_prompt),
                            "rendered_documents": rag_documents,
                            "retrieved_context": context,
                        },
                    },
                }
            )
            blind_map[case_id] = {"A": "full", "B": "rag"}
        self._write_json(
            "inputs.json",
            {"schema_version": answers.ARTIFACT_SCHEMA_VERSION, "cases": cases},
        )
        self._write_json("private/blind-map.json", blind_map)
        files = answers.code_manifest(answers.ROOT)
        source_raw, _ = answers.read_source(answers.DEFAULT_SOURCE)
        source_sha = answers.sha256(source_raw)
        frozen_source_hashes = answers._frozen_source_hashes(self.cases_path)
        self._write_json(
            "manifest.json",
            {
                "schema_version": answers.ARTIFACT_SCHEMA_VERSION,
                "status": "prepared",
                "code_files": files,
                "cases_sha256": answers.sha256_file(self.cases_path),
                "frozen_source_files_sha256": frozen_source_hashes,
                "prepared_files_sha256": {
                    relative: answers.sha256_file(self.artifacts / relative)
                    for relative in (
                        "inputs.json",
                        "snapshot.json",
                        "private/blind-map.json",
                    )
                },
                "source": {
                    "source_sha256": source_sha,
                    "snapshot_fingerprint": snapshot.fingerprint,
                    "snapshot_sha256": answers.sha256_file(
                        self.artifacts / "snapshot.json"
                    ),
                },
                "runtime": {
                    "provider": "openai",
                    "model_name": "gpt-6-luna",
                    "prompt_profile": "examples_answer_scope_v5",
                    "reasoning_effort": "xhigh",
                    "max_output_tokens": 16384,
                    "output_mode": "prompt_json",
                    "api_calls_planned": 40,
                    "max_api_calls": 40,
                    "max_cost_usd": 5.0,
                    "api_calls_made": 0,
                },
            },
        )

    def _write_json(self, relative, value):
        path = self.artifacts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _execute(self):
        return answers.execute_prepared(
            self.artifacts,
            self.cases_path,
            self.model,
            self.env_file,
            root=answers.ROOT,
            provider_factory=lambda config: self.client,
        )

    def test_pair_budget_rejection_calls_neither_variant(self):
        with patch.object(answers, "reserve_cost", return_value=3.0):
            summary = self._execute()

        self.assertEqual(self.client.calls, [])
        self.assertEqual(summary["status"], "stopped_budget")
        pair = json.loads((self.artifacts / f"pairs/{self.case_id}.json").read_text())
        self.assertEqual(pair["status"], "budget_blocked_before_calls")
        self.assertEqual(pair["variants"]["A"]["status"], "not_called")
        self.assertEqual(pair["variants"]["B"]["status"], "budget_blocked")

    def test_duplicate_execution_is_rejected_before_provider_use(self):
        marker = self.artifacts / answers.EXECUTION_STARTED
        marker.write_text('{"status":"running"}\n', encoding="utf-8")

        with self.assertRaises(answers.AnswerEvaluationError):
            self._execute()

        self.assertEqual(self.client.calls, [])

    def test_unknown_cost_preserves_response_and_stops_without_retry(self):
        self.client = FakeManagedClient(unknown_usage=True)

        summary = self._execute()

        self.assertEqual(summary["status"], "stopped_unknown_cost")
        self.assertEqual(len(self.client.calls), 1)
        record = json.loads(
            (self.artifacts / f"responses/{self.case_id}-A.json").read_text()
        )
        self.assertEqual(
            record["provider_response"]["raw_text"], '{"answer":"확인된 답변입니다."}'
        )
        self.assertIsNone(record["actual_cost_usd"])
        self.assertEqual(record["status"], "unknown_cost")
        self.assertNotIn("mode", record)
        with self.assertRaises(answers.AnswerEvaluationError):
            self._execute()
        self.assertEqual(len(self.client.calls), 1)

    def test_frozen_optional_correctness_checks_are_retained(self):
        source_raw, source_rows = answers.read_source(answers.DEFAULT_SOURCE)
        validated = answers._validate_cases(
            json.loads(self.cases_path.read_text(encoding="utf-8")),
            answers.sha256(source_raw),
            source_rows,
        )

        source_case = next(
            case
            for case in json.loads(self.cases_path.read_text(encoding="utf-8"))["cases"]
            if "optional_correctness_checks" in case
        )
        validated_case = next(
            case for case in validated if case["case_id"] == source_case["case_id"]
        )
        self.assertEqual(
            validated_case["optional_correctness_checks"],
            source_case["optional_correctness_checks"],
        )

    def test_provider_failure_is_saved_safely_without_retry(self):
        self.client = FakeManagedClient(error=RuntimeError("secret provider details"))

        summary = self._execute()

        self.assertEqual(summary["status"], "stopped_provider_error")
        self.assertEqual(len(self.client.calls), 1)
        record = json.loads(
            (self.artifacts / f"responses/{self.case_id}-A.json").read_text()
        )
        self.assertEqual(record["status"], "provider_error")
        self.assertEqual(record["error_type"], "RuntimeError")
        self.assertNotIn("secret provider details", json.dumps(record))
        self.assertNotIn("mode", record)

    def test_generation_parse_failure_keeps_raw_response_and_known_cost(self):
        self.client = FakeManagedClient(raw_text="not valid JSON")

        summary = self._execute()

        self.assertEqual(summary["status"], "stopped_generation_error")
        self.assertEqual(len(self.client.calls), 1)
        record = json.loads(
            (self.artifacts / f"responses/{self.case_id}-A.json").read_text()
        )
        self.assertEqual(record["status"], "generation_error")
        self.assertEqual(record["generation_error_type"], "LLMResponseError")
        self.assertEqual(record["provider_response"]["raw_text"], "not valid JSON")
        self.assertIsNotNone(record["actual_cost_usd"])
        self.assertEqual(record["cost_status"], "estimated_from_usage")

    def test_ledger_keeps_five_dollar_and_forty_call_caps(self):
        ledger = answers.ledger_at(self.artifacts)
        self.assertEqual(ledger.total_dollars, 5.0)
        self.assertEqual(ledger.dev_dollars, 5.0)
        self.assertEqual(ledger.max_calls, 40)
        for index in range(40):
            ledger.reserve(f"existing-{index}", "final", 0)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve("call-41", "final", 0)
        self.assertEqual(len(ledger.snapshot()["reservations"]), 40)

    def test_cli_returns_nonzero_for_stopped_execution(self):
        output = io.StringIO()
        args = [
            "--execute",
            "--cases",
            str(self.cases_path),
            "--model",
            str(self.model),
            "--artifact-root",
            str(self.artifacts),
            "--env-file",
            str(self.env_file),
        ]
        with (
            patch.object(
                answers,
                "execute_prepared",
                return_value={"status": "stopped_provider_error"},
            ),
            redirect_stdout(output),
        ):
            exit_code = answers.main(args)

        self.assertEqual(exit_code, 2)
        self.assertIn('"status": "stopped_provider_error"', output.getvalue())

    def test_prepared_input_drift_is_rejected_before_execution_marker(self):
        for relative in (
            "inputs.json",
            "snapshot.json",
            "private/blind-map.json",
        ):
            with self.subTest(relative=relative):
                path = self.artifacts / relative
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaises(answers.AnswerEvaluationError):
                    self._execute()
                self.assertFalse((self.artifacts / answers.EXECUTION_STARTED).exists())
                self.assertEqual(self.client.calls, [])
                path.write_bytes(original)

    def test_frozen_cases_or_review_pack_drift_is_rejected_before_execution_marker(
        self,
    ):
        for relative in ("cases.json", "rubric.md", "freeze.json", "pricing.json"):
            with self.subTest(relative=relative):
                path = self.cases_path.parent / relative
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaises(answers.AnswerEvaluationError):
                    self._execute()
                self.assertFalse((self.artifacts / answers.EXECUTION_STARTED).exists())
                self.assertEqual(self.client.calls, [])
                path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
