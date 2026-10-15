import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage

from generation_evaluation.selection import (
    append_record,
    completed_keys,
    format_check,
    read_records,
)


class SelectionTests(unittest.TestCase):
    def test_format_requires_only_answer_and_nonempty_text(self):
        self.assertTrue(format_check('{"answer":"네."}'))
        for raw in [
            '```json\n{"answer":"네"}\n```',
            '{"answer":" "}',
            '{"answer":3}',
            '{"answer":"네","extra":1}',
            "[]",
            None,
        ]:
            self.assertFalse(format_check(raw))

    def test_records_roundtrip_and_duplicate_resume_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            self.assertEqual(read_records(path), [])
            row = {"case_id": "case1", "repeat": 1, "answer": "안내"}
            append_record(path, row)
            self.assertEqual(read_records(path), [row])
            self.assertEqual(completed_keys([row]), {("case1", 1)})
            with self.assertRaises(ValueError):
                completed_keys([row, row])


class SelectionRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        code_hash_patch = patch(
            "generation_evaluation.selection.Path.read_bytes",
            return_value=b"stable test code snapshot",
        )
        code_hash_patch.start()
        self.addCleanup(code_hash_patch.stop)
        self.args = self._write_inputs(strategy="single", provider="ollama")

    def _write_inputs(self, strategy, provider):
        candidate = {
            "profile": "baseline",
            "strategy": strategy,
            "seed": 42,
            "config": {
                "provider": provider,
                "model_name": "qwen-test",
                "context_window": 4096,
                "max_output_tokens": 128,
                "timeout_seconds": 180,
                "temperature": 0,
            },
        }
        candidates_path = self.root / "candidates.json"
        candidates_path.write_text(
            json.dumps({"candidate-a": candidate}), encoding="utf-8"
        )
        cases_path = self.root / "cases.json"
        cases_path.write_text(
            json.dumps(
                [{"case_id": "case-1", "question": "어디에서 확인하나요?"}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        documents_path = self.root / "documents.jsonl"
        documents_path.write_text(
            json.dumps(
                {
                    "document_id": "DOC-1",
                    "title": "테스트 문서",
                    "document": "직원은 포털에서 상태를 조회할 수 있습니다.",
                    "revision_number": 1,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return Namespace(
            candidates=candidates_path,
            candidate="candidate-a",
            cases=cases_path,
            documents=documents_path,
            phase="dev",
            repeats=1,
            start_repeat=1,
            ledger=self.root / "ledger.json",
            output=self.root / "run",
        )

    @staticmethod
    def _response(raw_text):
        return AIMessage(
            content=raw_text,
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 8,
                "total_tokens": 18,
            },
            response_metadata={"done_reason": "stop"},
        )

    def _mock_ollama(self, raw_text='{"answer":"포털에서 확인하세요."}'):
        model = Mock()
        model.invoke.return_value = self._response(raw_text)
        return model

    def _read_jsonl(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_completed_case_is_skipped_on_resume(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            self.assertEqual(run(self.args), 0)

        model.invoke.assert_called_once()
        self.assertEqual(len(self._read_jsonl(self.args.output / "runs.jsonl")), 1)

    def test_resume_rejects_replacement_ledger_after_completed_run(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            self.args.ledger = self.root / "fresh-ledger.json"
            with self.assertRaisesRegex(ValueError, "ledger identity"):
                run(self.args)

        model.invoke.assert_called_once()

    def test_resume_accepts_copied_ledger_with_preserved_identity_and_history(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            source_ledger = json.loads(self.args.ledger.read_text(encoding="utf-8"))
            copied_ledger_path = self.root / "copied-ledger.json"
            copied_ledger_path.write_text(
                self.args.ledger.read_text(encoding="utf-8"), encoding="utf-8"
            )
            self.args.ledger = copied_ledger_path

            self.assertEqual(run(self.args), 0)

        copied_ledger = json.loads(copied_ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(copied_ledger, source_ledger)
        model.invoke.assert_called_once()

    def test_resume_rejects_ledger_missing_completed_call_reservation(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            ledger = json.loads(self.args.ledger.read_text(encoding="utf-8"))
            ledger["reservations"].clear()
            self.args.ledger.write_text(json.dumps(ledger), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prior reservations"):
                run(self.args)

        model.invoke.assert_called_once()

    def test_legacy_manifest_migrates_with_complete_reservation_history(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            manifest_path = self.args.output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("ledger_identity")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            ledger = json.loads(self.args.ledger.read_text(encoding="utf-8"))
            ledger.pop("ledger_identity")
            self.args.ledger.write_text(json.dumps(ledger), encoding="utf-8")

            self.assertEqual(run(self.args), 0)

        migrated_manifest = json.loads(
            (self.args.output / "manifest.json").read_text(encoding="utf-8")
        )
        migrated_ledger = json.loads(self.args.ledger.read_text(encoding="utf-8"))
        self.assertTrue(migrated_manifest["ledger_identity"])
        self.assertEqual(
            migrated_manifest["ledger_identity"], migrated_ledger["ledger_identity"]
        )
        self.assertEqual(len(migrated_ledger["reservations"]), 1)
        model.invoke.assert_called_once()

    def test_legacy_manifest_rejects_fresh_ledger_without_reservation_history(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            manifest_path = self.args.output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("ledger_identity")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.args.ledger = self.root / "fresh-ledger.json"

            with self.assertRaisesRegex(ValueError, "prior reservations"):
                run(self.args)

        model.invoke.assert_called_once()

    def test_existing_records_without_manifest_are_rejected(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            (self.args.output / "manifest.json").unlink()
            with self.assertRaisesRegex(ValueError, "manifest is missing"):
                run(self.args)

        model.invoke.assert_called_once()

    def test_uncertain_started_event_is_rejected_before_provider_call(self):
        from generation_evaluation.selection import run

        self.args.output.mkdir()
        (self.args.output / "events.jsonl").write_text(
            json.dumps({"case_id": "case-1", "repeat": 1, "started_at": 1}) + "\n",
            encoding="utf-8",
        )
        with (
            patch("generation_evaluation.selection.ChatOllama") as provider,
            self.assertRaisesRegex(ValueError, "manual reconciliation"),
        ):
            run(self.args)
        provider.assert_not_called()

    def test_manifest_change_is_rejected_before_provider_call(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with patch("generation_evaluation.selection.ChatOllama", return_value=model):
            with redirect_stdout(StringIO()):
                self.assertEqual(run(self.args), 0)
            cases = json.loads(self.args.cases.read_text(encoding="utf-8"))
            cases[0]["question"] = "다른 질문입니다."
            self.args.cases.write_text(
                json.dumps(cases, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "manifest differs"):
                run(self.args)

        model.invoke.assert_called_once()

    def test_resume_rejects_changed_budget_limits_before_provider_call(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            self.args.total_dollars = 4.0
            with self.assertRaisesRegex(ValueError, "다른 한도"):
                run(self.args)

        model.invoke.assert_called_once()

    def test_legacy_manifest_without_budget_limits_resumes_only_with_defaults(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            manifest_path = self.args.output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("budget_limits")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual(run(self.args), 0)

        migrated_manifest = json.loads(
            (self.args.output / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            migrated_manifest["budget_limits"],
            {
                "total_dollars": 5.0,
                "dev_dollars": 3.0,
                "total_seconds": 7200.0,
                "dev_seconds": 4200.0,
            },
        )
        model.invoke.assert_called_once()

    def test_legacy_manifest_without_budget_limits_rejects_custom_limits(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            manifest_path = self.args.output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("budget_limits")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.args.total_dollars = 4.0

            with self.assertRaisesRegex(ValueError, "다른 한도"):
                run(self.args)

        model.invoke.assert_called_once()

    def test_new_output_cannot_change_limits_for_the_same_ledger(self):
        from generation_evaluation.selection import run

        model = self._mock_ollama()
        with (
            patch(
                "generation_evaluation.selection.ChatOllama", return_value=model
            ) as provider,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            changed = Namespace(**vars(self.args))
            changed.output = self.root / "new-output"
            changed.total_dollars = 4.0
            with self.assertRaisesRegex(ValueError, "다른 한도"):
                run(changed)

        self.assertEqual(provider.call_count, 1)
        model.invoke.assert_called_once()
        self.assertFalse((self.root / "new-output").exists())

    def test_new_output_cannot_omit_custom_limits_and_fall_back_to_defaults(self):
        from generation_evaluation.selection import run

        self.args.total_dollars = 3.0
        self.args.dev_dollars = 1.2
        model = self._mock_ollama()
        with (
            patch(
                "generation_evaluation.selection.ChatOllama", return_value=model
            ) as provider,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)
            defaulted = Namespace(**vars(self.args))
            defaulted.output = self.root / "new-output-defaults"
            del defaulted.total_dollars
            del defaulted.dev_dollars
            with self.assertRaisesRegex(ValueError, "다른 한도"):
                run(defaulted)

        self.assertEqual(provider.call_count, 1)
        model.invoke.assert_called_once()
        self.assertFalse((self.root / "new-output-defaults").exists())

    def test_custom_cost_cap_stops_before_openai_provider_call(self):
        from generation_evaluation.selection import run

        self.args = self._write_inputs(strategy="single", provider="openai")
        self.args.total_dollars = 0.001
        self.args.dev_dollars = 0.001
        with (
            patch("generation_evaluation.selection.reserve_cost", return_value=0.01),
            patch("generation_evaluation.selection.build_openai_model") as provider,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 2)

        provider.assert_not_called()
        self.assertEqual(len(self._read_jsonl(self.args.output / "runs.jsonl")), 1)
        ledger = json.loads(self.args.ledger.read_text(encoding="utf-8"))
        self.assertEqual(ledger["reservations"], {})

    def test_invalid_budget_limits_fail_before_creating_run_files(self):
        from generation_evaluation.selection import run

        self.args.total_dollars = -1
        with self.assertRaisesRegex(ValueError, "total_dollars"):
            run(self.args)

        self.assertFalse(self.args.output.exists())
        self.assertFalse(self.args.ledger.exists())

    def test_provider_failure_is_persisted_without_exception_message(self):
        from generation_evaluation.selection import run

        secret = "PRIVATE_PROVIDER_DETAIL_SHOULD_NOT_BE_SAVED"
        model = Mock()
        model.invoke.side_effect = RuntimeError(secret)
        with (
            patch("generation_evaluation.selection.ChatOllama", return_value=model),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 0)

        records = self._read_jsonl(self.args.output / "runs.jsonl")
        self.assertEqual(records[0]["error_type"], "RuntimeError")
        self.assertEqual(records[0]["calls"][0]["error_type"], "RuntimeError")
        persisted = "\n".join(
            path.read_text(encoding="utf-8")
            for path in self.root.rglob("*")
            if path.is_file()
        )
        self.assertNotIn(secret, persisted)

    def test_second_stage_budget_failure_keeps_first_call_accounting(self):
        from generation_evaluation.selection import run

        self.args = self._write_inputs(strategy="evidence_first", provider="openai")
        evidence = json.dumps(
            {
                "evidence": [
                    {
                        "document_id": "DOC-1",
                        "quote": "직원은 포털에서 상태를 조회할 수 있습니다.",
                        "scope": "직원",
                        "conditions": "없음",
                    }
                ],
                "missing": [],
            },
            ensure_ascii=False,
        )
        model = Mock()
        model.invoke.return_value = self._response(evidence)
        with (
            patch(
                "generation_evaluation.selection.build_openai_model", return_value=model
            ),
            patch(
                "generation_evaluation.selection.reserve_cost",
                side_effect=[2.5, 1.0],
            ),
            patch("generation_evaluation.selection.actual_cost", return_value=None),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run(self.args), 2)

        records = self._read_jsonl(self.args.output / "runs.jsonl")
        self.assertEqual(records[0]["error_type"], "BudgetExceeded")
        self.assertEqual(len(records[0]["calls"]), 1)
        self.assertEqual(records[0]["calls"][0]["raw_text"], evidence)
        ledger = json.loads(self.args.ledger.read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["reservations"]), 1)
        reservation = next(iter(ledger["reservations"].values()))
        self.assertEqual(reservation["status"], "settled")
        self.assertEqual(reservation["charged_dollars"], 2.5)
        model.invoke.assert_called_once()
