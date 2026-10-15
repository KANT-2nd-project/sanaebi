import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from generation.__main__ import main
from generation.config import (
    GenerationConfig,
    GenerationOutputMode,
    GenerationProvider,
)
from generation.types import GenerationPrompt, ModelResponse


class GenerationCliTests(unittest.TestCase):
    def test_document_identity_tracks_loaded_content_and_order(self):
        path = self.root / "documents.jsonl"
        self.write_documents(path)
        first = json.loads(path.read_text(encoding="utf-8"))
        second = {**first, "document_id": "policy-2", "document": "다른 안내"}

        def record_for(rows, filename="documents.jsonl", compact=False):
            target = self.root / filename
            target.write_text(
                "\n".join(
                    json.dumps(
                        row,
                        ensure_ascii=compact,
                        separators=(",", ":") if compact else None,
                    )
                    for row in rows
                )
                + "\n",
                encoding="utf-8",
            )
            _, output = self.run_cli(self.argv(target))
            return json.loads(output)

        with patch("generation.__main__.build_model_call") as factory:
            factory.return_value = lambda prompt: ModelResponse('{"answer":"안내"}')
            baseline = record_for([first, second])
            equivalent = record_for([first, second], "copy.jsonl", compact=True)
            reversed_record = record_for([second, first])
            changed = record_for([{**first, "document": "수정된 안내"}, second])
            single = record_for([first])

        digest = baseline["documents_sha256"]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(digest, equivalent["documents_sha256"])
        for record in (reversed_record, changed, single):
            self.assertNotEqual(digest, record["documents_sha256"])
        self.assertEqual(baseline["document_count"], 2)
        self.assertEqual(single["document_count"], 1)

    def test_prompt_identity_uses_actual_messages_and_survives_call_failure(self):
        path = self.root / "documents.jsonl"
        self.write_documents(path)
        seen = []

        def model_call(prompt):
            seen.append(prompt)
            raise RuntimeError("provider failed")

        prompts = [
            GenerationPrompt("규칙 A", "문서 A와 질문 A"),
            GenerationPrompt("규칙 A", "문서 A와 질문 A"),
            GenerationPrompt("규칙 B", "문서 A와 질문 A"),
            GenerationPrompt("규칙 A", "문서 B와 질문 A"),
            GenerationPrompt("규칙 A", "문서 A와 질문 B"),
        ]
        records = []
        with patch("generation.__main__.build_model_call", return_value=model_call):
            for prompt in prompts:
                with patch("generation.service.build_prompt", return_value=prompt):
                    code, output = self.run_cli(self.argv(path))
                self.assertEqual(code, 1)
                records.append(json.loads(output))
        self.assertEqual(seen, prompts)
        digest = records[0]["prompt_sha256"]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(digest, records[1]["prompt_sha256"])
        for record in records[2:]:
            self.assertNotEqual(digest, record["prompt_sha256"])

    def test_client_creation_failure_precedes_run_record(self):
        path = self.root / "documents.jsonl"
        self.write_documents(path)
        output = StringIO()
        with (
            patch("sys.argv", self.argv(path)),
            patch(
                "generation.__main__.build_model_call",
                side_effect=RuntimeError("setup failed"),
            ),
            patch("generation.__main__.run_case") as runner,
            redirect_stdout(output),
            self.assertRaisesRegex(RuntimeError, "setup failed"),
        ):
            main()
        runner.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_truncated_response_exits_one_and_preserves_metadata(self):
        path = self.root / "documents.jsonl"
        self.write_documents(path)
        raw = '{"answer":"겉보기에는 완성된 답변"}'
        with patch("generation.__main__.build_model_call") as factory:
            factory.return_value = lambda prompt: ModelResponse(raw, 100, 512, "length")
            code, output = self.run_cli(self.argv(path))
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(output)["result"],
            {
                "status": "truncated",
                "answer": None,
                "raw_text": raw,
                "input_tokens": 100,
                "output_tokens": 512,
                "finish_reason": "length",
                "refusal": None,
            },
        )

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config_dir = self.root / "generation"
        self.config_dir.mkdir()
        patcher = patch(
            "generation.__main__.__file__", str(self.config_dir / "__main__.py")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def write_documents(path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "document_id": "policy-1",
                    "revision_number": 3,
                    "title": "연차 신청",
                    "document": "인사 포털에서 연차를 신청합니다.",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def argv(self, path: Path, timeout=120) -> list[str]:
        (self.config_dir / "models.json").write_text(
            json.dumps(
                {
                    "test-alias": {
                        "provider": "ollama",
                        "model_name": "test-model",
                        "timeout_seconds": timeout,
                        "context_window": 40960,
                        "max_output_tokens": 512,
                    }
                }
            )
        )
        (self.config_dir / "experiments.json").write_text(
            json.dumps(
                {
                    "test-experiment": {
                        "documents": str(path),
                        "models": ["test-alias"],
                    }
                }
            )
        )
        return [
            "generation",
            "--experiment",
            "test-experiment",
            "--question",
            "연차는 어디에서 신청하나요?",
            "--model",
            "test-alias",
        ]

    def run_cli(self, argv: list[str]) -> tuple[int, str]:
        output = StringIO()
        with (
            patch("sys.argv", argv),
            redirect_stdout(output),
            patch(
                "generation_evaluation.runner.perf_counter", side_effect=(10.0, 10.25)
            ),
        ):
            exit_code = main()
        record = json.loads(output.getvalue())
        self.assertEqual(record["case_id"], "manual")
        self.assertEqual(record["experiment"], "test-experiment")
        self.assertEqual(record["model_alias"], "test-alias")
        self.assertEqual(record["question"], "연차는 어디에서 신청하나요?")
        self.assertEqual(record["elapsed_seconds"], 0.25)
        settings = json.loads((self.config_dir / "models.json").read_text())[
            "test-alias"
        ]
        self.assertEqual(
            record["config"],
            {
                **settings,
                "context_window": settings.get("context_window"),
                "max_output_tokens": settings.get("max_output_tokens"),
                "reasoning_effort": settings.get("reasoning_effort"),
                "temperature": settings.get("temperature"),
                "output_mode": settings.get("output_mode", "prompt_json"),
            },
        )
        if record["result"] is not None:
            self.assertIsNone(record["error_type"])
        return exit_code, output.getvalue()

    def test_success_runs_real_generation_service_and_prints_result(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_documents(path)
            seen_prompts: list[GenerationPrompt] = []

            def fake_model_call(prompt: GenerationPrompt) -> ModelResponse:
                seen_prompts.append(prompt)
                return ModelResponse(
                    '{"answer":"인사 포털에서 신청합니다."}', 100, 20, "stop"
                )

            with patch("generation.__main__.build_model_call") as model_factory:
                model_factory.return_value = fake_model_call
                exit_code, output = self.run_cli(self.argv(path, timeout=12))

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(output)["result"],
            {
                "status": "completed",
                "answer": "인사 포털에서 신청합니다.",
                "raw_text": '{"answer":"인사 포털에서 신청합니다."}',
                "input_tokens": 100,
                "output_tokens": 20,
                "finish_reason": "stop",
                "refusal": None,
            },
        )
        self.assertEqual(len(seen_prompts), 1)
        self.assertIn("연차는 어디에서 신청하나요?", seen_prompts[0].user)
        self.assertIn("문서 ID: policy-1", seen_prompts[0].user)
        self.assertIn("개정: 3", seen_prompts[0].user)
        self.assertIn("인사 포털에서 연차를 신청합니다.", seen_prompts[0].user)
        model_factory.assert_called_once_with(
            GenerationConfig(GenerationProvider.OLLAMA, "test-model", 12.0, 40960, 512)
        )

    def test_parse_empty_and_timeout_results_exit_one(self):
        outcomes = (
            ("{invalid", "parse_error", "{invalid", None),
            ('{"answer":"  "}', "empty_answer", '{"answer":"  "}', None),
            (TimeoutError("timed out"), "timeout", None, None),
        )
        for model_outcome, expected_status, expected_raw, expected_answer in outcomes:
            with (
                self.subTest(status=expected_status),
                TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "documents.jsonl"
                self.write_documents(path)

                def fake_model_call(
                    _prompt: GenerationPrompt, outcome=model_outcome
                ) -> ModelResponse:
                    if isinstance(outcome, TimeoutError):
                        raise outcome
                    return ModelResponse(outcome)

                with patch("generation.__main__.build_model_call") as model_factory:
                    model_factory.return_value = fake_model_call
                    exit_code, output = self.run_cli(self.argv(path))

                self.assertEqual(exit_code, 1)
                self.assertEqual(
                    json.loads(output)["result"],
                    {
                        "status": expected_status,
                        "answer": expected_answer,
                        "raw_text": expected_raw,
                        "input_tokens": None,
                        "output_tokens": None,
                        "finish_reason": None,
                        "refusal": None,
                    },
                )
                model_factory.assert_called_once()

    def test_invalid_question_stops_before_model_factory(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_documents(path)
            argv = self.argv(path)
            question_index = argv.index("--question") + 1
            argv[question_index] = " \n "

            with (
                patch("sys.argv", argv),
                patch("generation.__main__.build_model_call") as model_factory,
                redirect_stdout(StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                main()

        self.assertEqual(raised.exception.code, 2)
        model_factory.assert_not_called()

    def test_invalid_document_stops_before_model_factory(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            path.write_text("\n", encoding="utf-8")

            with (
                patch("sys.argv", self.argv(path)),
                patch("generation.__main__.build_model_call") as model_factory,
                self.assertRaisesRegex(ValueError, "1번째 줄"),
            ):
                main()

        model_factory.assert_not_called()

    def test_invalid_model_configuration_stops_before_model_factory(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_documents(path)
            argv = self.argv(path, timeout=0)

            with (
                patch("sys.argv", argv),
                patch("generation.__main__.build_model_call") as model_factory,
                self.assertRaises(ValueError),
            ):
                main()

        model_factory.assert_not_called()

    def test_openai_options_are_loaded_from_model_alias(self):
        path = self.root / "documents.jsonl"
        self.write_documents(path)
        argv = self.argv(path)
        model_config_path = self.config_dir / "models.json"
        model_settings = {
            "provider": "openai",
            "model_name": "gpt-6-luna",
            "timeout_seconds": 30,
            "max_output_tokens": 1024,
            "reasoning_effort": "low",
            "output_mode": "strict_json_schema",
        }
        model_config_path.write_text(json.dumps({"test-alias": model_settings}))

        with patch("generation.__main__.build_model_call") as model_factory:
            model_factory.return_value = lambda _prompt: ModelResponse(
                '{"answer":"안내"}'
            )
            self.run_cli(argv)

        model_factory.assert_called_once_with(
            GenerationConfig(
                GenerationProvider.OPENAI,
                "gpt-6-luna",
                30,
                max_output_tokens=1024,
                reasoning_effort="low",
                output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA,
            )
        )

    def test_refusal_result_is_printed_and_exits_one(self):
        path = self.root / "documents.jsonl"
        self.write_documents(path)

        with patch("generation.__main__.build_model_call") as factory:
            factory.return_value = lambda _prompt: ModelResponse(
                raw_text="",
                refusal="요청을 처리할 수 없습니다.",
            )
            exit_code, output = self.run_cli(self.argv(path))

        self.assertEqual(exit_code, 1)
        result = json.loads(output)["result"]
        self.assertEqual(result["status"], "refusal")
        self.assertEqual(result["raw_text"], "")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["refusal"], "요청을 처리할 수 없습니다.")

    def test_model_execution_error_is_recorded_and_exits_one(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_documents(path)

            def fake_model_call(_prompt: GenerationPrompt) -> ModelResponse:
                raise RuntimeError("provider failed")

            with (
                patch("sys.argv", self.argv(path)),
                patch("generation.__main__.build_model_call") as model_factory,
            ):
                model_factory.return_value = fake_model_call
                code, output = self.run_cli(self.argv(path))

        self.assertEqual(code, 1)
        record = json.loads(output)
        self.assertIsNone(record["result"])
        self.assertEqual(record["error_type"], "RuntimeError")
        self.assertNotIn("provider failed", output)
        model_factory.assert_called_once()

    def test_help_exits_without_creating_model_call(self):
        output = StringIO()
        with (
            patch("sys.argv", ["generation", "--help"]),
            patch("generation.__main__.build_model_call") as model_factory,
            redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--experiment", output.getvalue())
        model_factory.assert_not_called()

    def test_unknown_names_and_unlisted_model_are_rejected(self):
        for mode in ("experiment", "model", "unlisted"):
            with self.subTest(mode=mode):
                argv = self.argv(Path("unused.jsonl"))
                if mode == "unlisted":
                    path = self.config_dir / "experiments.json"
                    data = json.loads(path.read_text())
                    data["test-experiment"]["models"] = []
                    path.write_text(json.dumps(data))
                else:
                    argv[argv.index(f"--{mode}") + 1] = "unknown"
                with (
                    patch("generation.__main__.build_model_call") as factory,
                    self.assertRaises(SystemExit) as caught,
                ):
                    self.run_cli(argv)
                self.assertEqual(caught.exception.code, 2)
                factory.assert_not_called()

    def test_relative_documents_resolve_from_project_root(self):
        path = self.root / "documents.jsonl"
        self.write_documents(path)
        argv = self.argv(Path("documents.jsonl"))
        with patch("generation.__main__.build_model_call") as factory:
            factory.return_value = lambda prompt: ModelResponse('{"answer":"안내"}')
            code, _ = self.run_cli(argv)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
