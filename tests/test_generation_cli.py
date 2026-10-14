import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from generation.__main__ import main
from generation.config import GenerationConfig, GenerationProvider
from generation.types import GenerationPrompt


class GenerationCliTests(unittest.TestCase):
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

    @staticmethod
    def argv(path: Path, *extra: str) -> list[str]:
        return [
            "generation",
            "--documents",
            str(path),
            "--question",
            "연차는 어디에서 신청하나요?",
            "--provider",
            "ollama",
            "--model",
            "test-model",
            *extra,
        ]

    def run_cli(self, argv: list[str]) -> tuple[int, str]:
        output = StringIO()
        with patch("sys.argv", argv), redirect_stdout(output):
            exit_code = main()
        return exit_code, output.getvalue()

    def test_success_runs_real_generation_service_and_prints_result(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_documents(path)
            seen_prompts: list[GenerationPrompt] = []

            def fake_model_call(prompt: GenerationPrompt) -> str:
                seen_prompts.append(prompt)
                return '{"answer":"인사 포털에서 신청합니다."}'

            with patch("generation.__main__.build_model_call") as model_factory:
                model_factory.return_value = fake_model_call
                exit_code, output = self.run_cli(self.argv(path, "--timeout", "12"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(output),
            {
                "status": "completed",
                "answer": "인사 포털에서 신청합니다.",
                "raw_text": '{"answer":"인사 포털에서 신청합니다."}',
            },
        )
        self.assertEqual(len(seen_prompts), 1)
        self.assertIn("연차는 어디에서 신청하나요?", seen_prompts[0].user)
        self.assertIn("문서 ID: policy-1", seen_prompts[0].user)
        self.assertIn("개정: 3", seen_prompts[0].user)
        self.assertIn("인사 포털에서 연차를 신청합니다.", seen_prompts[0].user)
        model_factory.assert_called_once_with(
            GenerationConfig(GenerationProvider.OLLAMA, "test-model", 12.0)
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
                ) -> str:
                    if isinstance(outcome, TimeoutError):
                        raise outcome
                    return outcome

                with patch("generation.__main__.build_model_call") as model_factory:
                    model_factory.return_value = fake_model_call
                    exit_code, output = self.run_cli(self.argv(path))

                self.assertEqual(exit_code, 1)
                self.assertEqual(
                    json.loads(output),
                    {
                        "status": expected_status,
                        "answer": expected_answer,
                        "raw_text": expected_raw,
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
            argv = self.argv(path, "--timeout", "0")

            with (
                patch("sys.argv", argv),
                patch("generation.__main__.build_model_call") as model_factory,
                self.assertRaises(ValueError),
            ):
                main()

        model_factory.assert_not_called()

    def test_unexpected_model_error_propagates(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            self.write_documents(path)

            def fake_model_call(_prompt: GenerationPrompt) -> str:
                raise RuntimeError("provider failed")

            with (
                patch("sys.argv", self.argv(path)),
                patch("generation.__main__.build_model_call") as model_factory,
            ):
                model_factory.return_value = fake_model_call
                with self.assertRaisesRegex(RuntimeError, "provider failed"):
                    main()

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
        self.assertIn("--documents", output.getvalue())
        model_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
