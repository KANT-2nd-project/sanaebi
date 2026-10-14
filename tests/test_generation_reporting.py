import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from generation.config import GenerationConfig, GenerationProvider
from generation.types import GenerationResult, GenerationStatus
from generation_evaluation.reporting import (
    config_from_dict,
    read_runs_jsonl,
    result_from_dict,
    run_from_dict,
    run_to_dict,
    save_runs_jsonl,
)
from generation_evaluation.types import GenerationRun


class GenerationReportingTests(unittest.TestCase):
    def test_truncated_record_survives_jsonl_round_trip(self):
        run = GenerationRun(
            "cut",
            self.config,
            GenerationResult(
                GenerationStatus.TRUNCATED, "partial", None, 100, 512, "length"
            ),
            2,
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            save_runs_jsonl(path, [run])
            restored = run_from_dict(read_runs_jsonl(path)[0])
        self.assertEqual(restored, run)

    def test_response_metadata_round_trip_and_legacy_defaults(self):
        result = GenerationResult(
            GenerationStatus.PARSE_ERROR, "bad", None, 20, 0, "length"
        )
        run = GenerationRun("case", self.config, result, 0.5)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            save_runs_jsonl(path, [run])
            data = read_runs_jsonl(path)[0]
        self.assertEqual(run_from_dict(data), run)
        for field in ("input_tokens", "output_tokens", "finish_reason"):
            del data["result"][field]
        restored = run_from_dict(data).result
        self.assertEqual(
            (restored.input_tokens, restored.output_tokens, restored.finish_reason),
            (None, None, None),
        )

    def test_result_restore_rejects_invalid_metadata(self):
        valid = {"status": "parse_error", "raw_text": "bad", "answer": None}
        for field in ("input_tokens", "output_tokens"):
            for value in (True, "1", 1.5):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(TypeError),
                ):
                    result_from_dict({**valid, field: value})
            with self.assertRaises(ValueError):
                result_from_dict({**valid, field: -1})
        with self.assertRaises(TypeError):
            result_from_dict({**valid, "finish_reason": 1})

    def test_token_settings_survive_round_trip_and_old_records_load(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "model", 30, 40960, 512)
        run = GenerationRun("case", config, None, 0.25, "Error")
        data = run_to_dict(run)
        self.assertEqual(run_from_dict(data), run)
        del data["config"]["context_window"]
        del data["config"]["max_output_tokens"]
        restored = run_from_dict(data)
        self.assertIsNone(restored.config.context_window)
        self.assertIsNone(restored.config.max_output_tokens)

    def test_runs_restore_through_jsonl(self):
        runs = [
            GenerationRun(
                "완료",
                self.config,
                GenerationResult(
                    GenerationStatus.COMPLETED, ' {"answer":"답"}\n', "답"
                ),
                0,
            ),
            GenerationRun(
                "timeout",
                self.config,
                GenerationResult(GenerationStatus.TIMEOUT, None, None),
                30.5,
            ),
            GenerationRun("error", self.config, None, 0.25, "ConnectError"),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            save_runs_jsonl(path, runs)
            rows = read_runs_jsonl(path)
            originals = json.loads(json.dumps(rows))
            self.assertEqual([run_from_dict(row) for row in rows], runs)
            self.assertEqual(rows, originals)

    def test_run_restore_requires_every_field(self):
        data = run_to_dict(GenerationRun("case", self.config, None, 0, "Error"))
        for field in data:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                run_from_dict(
                    {key: value for key, value in data.items() if key != field}
                )

    def test_run_restore_rejects_invalid_types(self):
        for data in (None, [], "", 1, False):
            with self.subTest(data=data), self.assertRaises(TypeError):
                run_from_dict(data)
        valid = run_to_dict(GenerationRun("case", self.config, None, 0, "Error"))
        for field, values in {
            "case_id": (None, 1, False),
            "config": (None, [], ""),
            "result": ([], "", False),
            "elapsed_seconds": (None, "1", True, False),
            "error_type": (1, False, []),
        }.items():
            for value in values:
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(TypeError, field),
                ):
                    run_from_dict({**valid, field: value})

    def test_run_restore_applies_domain_validation(self):
        valid = run_to_dict(GenerationRun("case", self.config, None, 0, "Error"))
        invalid_updates = [
            {"elapsed_seconds": value} for value in (-1, float("inf"), float("nan"))
        ] + [
            {"error_type": None},
            {"error_type": " "},
            {"result": {"status": "timeout", "raw_text": None, "answer": None}},
            {
                "result": {"status": "completed", "raw_text": "raw", "answer": None},
                "error_type": None,
            },
            {
                "config": {
                    "provider": "unknown",
                    "model_name": "model",
                    "timeout_seconds": 1,
                }
            },
        ]
        for update in invalid_updates:
            with self.subTest(update=update), self.assertRaises(ValueError):
                run_from_dict({**valid, **update})

    def test_result_restore_rejects_inconsistent_content(self):
        for data in (
            {"status": "completed", "raw_text": "raw", "answer": None},
            {"status": "timeout", "raw_text": "raw", "answer": None},
            {"status": "parse_error", "raw_text": None, "answer": None},
            {"status": "empty_answer", "raw_text": "raw", "answer": "답"},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                result_from_dict(data)

    def test_result_restore_preserves_each_status_and_text(self):
        results = [
            GenerationResult(
                GenerationStatus.COMPLETED, ' {"answer":"안내"}\n', "안내"
            ),
            GenerationResult(GenerationStatus.TIMEOUT, None, None),
            GenerationResult(GenerationStatus.PARSE_ERROR, "bad JSON", None),
            GenerationResult(GenerationStatus.EMPTY_ANSWER, '{"answer":""}', None),
        ]
        for result in results:
            with self.subTest(status=result.status):
                run = GenerationRun("case", self.config, result, 0.25)
                data = run_to_dict(run)["result"]
                original = data.copy()
                restored = result_from_dict(data)
                self.assertEqual(restored, result)
                self.assertIs(restored.status, result.status)
                self.assertEqual(data, original)

    def test_result_restore_distinguishes_null_from_missing_fields(self):
        self.assertIsNone(result_from_dict(None))
        valid = {"status": "timeout", "raw_text": None, "answer": None}
        for field in valid:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                result_from_dict(
                    {key: value for key, value in valid.items() if key != field}
                )

    def test_result_restore_rejects_invalid_types(self):
        for data in ([], "", 0, False):
            with self.subTest(data=data), self.assertRaises(TypeError):
                result_from_dict(data)
        valid = {"status": "timeout", "raw_text": None, "answer": None}
        for field, values in {
            "status": (None, 1, True, []),
            "raw_text": (1, False, [], {}),
            "answer": (1, False, [], {}),
        }.items():
            for value in values:
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(TypeError, field),
                ):
                    result_from_dict({**valid, field: value})

    def test_result_restore_rejects_unknown_status(self):
        for status in ("unknown", "", "COMPLETED"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                result_from_dict({"status": status, "raw_text": None, "answer": None})

    def test_config_restore_accepts_both_providers_and_numeric_timeouts(self):
        for provider in GenerationProvider:
            for timeout in (30, 0.25):
                with self.subTest(provider=provider, timeout=timeout):
                    data = {
                        "provider": provider.value,
                        "model_name": "example-model",
                        "timeout_seconds": timeout,
                    }
                    self.assertEqual(
                        config_from_dict(data),
                        GenerationConfig(provider, "example-model", timeout),
                    )
                    self.assertEqual(data["provider"], provider.value)

    def test_config_restore_rejects_missing_or_invalid_fields(self):
        valid = {"provider": "ollama", "model_name": "example", "timeout_seconds": 30}
        invalid_values = {
            "provider": ((None, TypeError), (1, TypeError), ("unknown", ValueError)),
            "model_name": (
                (None, TypeError),
                (1, TypeError),
                ("", ValueError),
                (" \n", ValueError),
            ),
            "timeout_seconds": (
                (None, TypeError),
                ("30", TypeError),
                (True, TypeError),
                (False, TypeError),
                (0, ValueError),
                (-1, ValueError),
                (float("inf"), ValueError),
                (float("-inf"), ValueError),
                (float("nan"), ValueError),
            ),
        }
        for field, values in invalid_values.items():
            missing = {key: value for key, value in valid.items() if key != field}
            with self.subTest(missing=field), self.assertRaises(TypeError):
                config_from_dict(missing)
            for value, expected_error in values:
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(expected_error),
                ):
                    config_from_dict({**valid, field: value})

    def test_read_saved_runs_preserves_order_and_content(self):
        runs = [
            GenerationRun(
                "first",
                self.config,
                GenerationResult(
                    GenerationStatus.COMPLETED, ' {"answer":"안내"}\n', "안내"
                ),
                0.25,
            ),
            GenerationRun("second", self.config, None, 0.5, "ConnectError"),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            save_runs_jsonl(path, runs)
            self.assertEqual(read_runs_jsonl(path), [run_to_dict(run) for run in runs])

    def test_read_empty_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            self.assertEqual(read_runs_jsonl(path), [])

    def test_read_rejects_invalid_json_and_blank_lines(self):
        for line in ("bad", "", "  "):
            with self.subTest(line=line), TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.jsonl"
                path.write_text("{}\n" + line + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "2번째 줄의 JSON") as caught:
                    read_runs_jsonl(path)
                self.assertIsInstance(caught.exception.__cause__, json.JSONDecodeError)
                self.assertIn(caught.exception.__cause__.msg, str(caught.exception))

    def test_read_rejects_non_objects_with_file_line_number(self):
        for line in ("[]", "123", "null", '"text"', "true"):
            with self.subTest(line=line), TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.jsonl"
                path.write_text("{}\n" + line + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "2번째 줄"):
                    read_runs_jsonl(path)

    def test_serialization_failure_does_not_create_file_or_parent(self):
        run = GenerationRun("error", self.config, None, 0.25, "ConnectError")
        error = ValueError("serialization failed")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "new-directory" / "runs.jsonl"
            with (
                patch(
                    "generation_evaluation.reporting.json.dumps",
                    side_effect=['{"case_id":"first"}', error],
                ),
                self.assertRaises(ValueError) as caught,
            ):
                save_runs_jsonl(path, [run, run])
            self.assertIs(caught.exception, error)
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

    def test_jsonl_round_trip_and_parent_creation(self):
        raw = ' \n{"answer":"안내"}\n'
        runs = [
            GenerationRun(
                "first",
                self.config,
                GenerationResult(GenerationStatus.COMPLETED, raw, "안내"),
                0.25,
            ),
            GenerationRun("second", self.config, None, 0.5, "ConnectError"),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "runs.jsonl"
            save_runs_jsonl(path, runs)
            content = path.read_text(encoding="utf-8")
        self.assertTrue(content.endswith("\n"))
        self.assertIn("안내", content)
        lines = content.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            [json.loads(line) for line in lines], [run_to_dict(r) for r in runs]
        )

    def test_empty_runs_create_empty_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "empty.jsonl"
            save_runs_jsonl(path, [])
            self.assertEqual(path.read_bytes(), b"")

    def test_existing_file_is_preserved(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            original = b"existing experiment\n"
            path.write_bytes(original)
            with self.assertRaises(FileExistsError):
                save_runs_jsonl(path, [])
            self.assertEqual(path.read_bytes(), original)

    def setUp(self):
        self.config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)

    def test_completed_run_preserves_all_fields_and_raw_text(self):
        raw = ' \n{"answer": " 안내입니다. "}\n'
        result = GenerationResult(GenerationStatus.COMPLETED, raw, "안내입니다.")
        run = GenerationRun("case-001", self.config, result, 0.25)
        data = run_to_dict(run)
        self.assertEqual(
            data,
            {
                "case_id": "case-001",
                "config": {
                    "provider": "ollama",
                    "model_name": "test-model",
                    "timeout_seconds": 30.0,
                    "context_window": None,
                    "max_output_tokens": None,
                },
                "result": {
                    "status": "completed",
                    "raw_text": raw,
                    "answer": "안내입니다.",
                    "input_tokens": None,
                    "output_tokens": None,
                    "finish_reason": None,
                },
                "elapsed_seconds": 0.25,
                "error_type": None,
            },
        )
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)

    def test_timeout_keeps_result_while_execution_error_has_no_result(self):
        timeout = GenerationRun(
            "timeout",
            self.config,
            GenerationResult(GenerationStatus.TIMEOUT, None, None),
            30.0,
        )
        error = GenerationRun("error", self.config, None, 0.1, "ConnectError")
        self.assertEqual(
            run_to_dict(timeout)["result"],
            {
                "status": "timeout",
                "raw_text": None,
                "answer": None,
                "input_tokens": None,
                "output_tokens": None,
                "finish_reason": None,
            },
        )
        error_data = run_to_dict(error)
        self.assertIsNone(error_data["result"])
        self.assertEqual(error_data["error_type"], "ConnectError")
        self.assertIsNone(json.loads(json.dumps(error_data))["result"])

    def test_returned_dict_does_not_mutate_original_record(self):
        run = GenerationRun(
            "case",
            self.config,
            GenerationResult(GenerationStatus.PARSE_ERROR, "bad", None),
            0.0,
        )
        data = run_to_dict(run)
        data["config"]["model_name"] = "changed"
        data["result"]["raw_text"] = "changed"
        self.assertEqual(run.config.model_name, "test-model")
        self.assertEqual(run.result.raw_text, "bad")
