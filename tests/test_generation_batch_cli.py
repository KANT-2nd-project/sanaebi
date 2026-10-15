import csv
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from generation.config import GenerationConfig, GenerationProvider
from generation.types import ModelResponse


class GenerationBatchCliTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for folder in ("generation", "generation_evaluation", "data"):
            (self.root / folder).mkdir()
        (self.root / "generation/models.json").write_text(
            json.dumps(
                {
                    "alias": {
                        "provider": "ollama",
                        "model_name": "fake",
                        "timeout_seconds": 10,
                    }
                }
            )
        )
        (self.root / "generation/experiments.json").write_text(
            json.dumps({"baseline": {"documents": "docs.jsonl", "models": ["alias"]}})
        )
        (self.root / "docs.jsonl").write_text(
            json.dumps(
                {
                    "document_id": "doc",
                    "revision_number": 1,
                    "title": "제목",
                    "document": "본문",
                }
            )
            + "\n"
        )
        self.rows = [
            {"question_id": "Q2", "question": "두 번째?", "label": "SEARCH_KNOWLEDGE"},
            {"question_id": "Q0", "question": "실행해줘", "label": "UNSUPPORTED"},
            {"question_id": "Q1", "question": "첫 번째?", "label": "SEARCH_KNOWLEDGE"},
        ]
        self.write_rows()
        self.output = self.root / "out/runs.jsonl"

    def write_rows(self):
        with (self.root / "data/dataset.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as f:
            writer = csv.DictWriter(f, fieldnames=["question_id", "question", "label"])
            writer.writeheader()
            writer.writerows(self.rows)

    def execute(self, model, extra=()):
        from generation_evaluation.__main__ import main

        argv = [
            "generation_evaluation",
            "--experiment",
            "baseline",
            "--model",
            "alias",
            "--output",
            str(self.output),
            *extra,
        ]
        with (
            patch(
                "generation_evaluation.__main__.__file__",
                str(self.root / "generation_evaluation/__main__.py"),
            ),
            patch(
                "generation_evaluation.__main__.build_model_call", return_value=model
            ) as factory,
            patch("sys.argv", argv),
            redirect_stdout(StringIO()) as stdout,
        ):
            code = main()
        return code, json.loads(stdout.getvalue()), factory

    def test_sorted_selected_cases_use_shared_service_and_save_each_result(self):
        seen = []

        def model(prompt):
            if seen:
                self.assertEqual(len(self.output.read_text().splitlines()), 1)
            seen.append(prompt)
            if len(seen) == 2:
                raise RuntimeError("failed")
            return ModelResponse('{"answer":"답변"}')

        code, summary, factory = self.execute(model)
        records = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.assertEqual(code, 1)
        self.assertEqual([r["case_id"] for r in records], ["Q1", "Q2"])
        self.assertEqual(records[1]["error_type"], "RuntimeError")
        self.assertIn("본문", seen[0].user)
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["completed"], 1)
        factory.assert_called_once()
        for record in records:
            self.assertRegex(record["prompt_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(record["document_count"], 1)

    def test_limit_selects_first_case(self):
        code, summary, _ = self.execute(
            lambda p: ModelResponse('{"answer":"답"}'), ["--limit", "1"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(summary["available"], 2)
        self.assertEqual(summary["attempted"], 1)

    def test_openai_options_are_loaded_from_model_alias(self):
        settings = {
            "provider": "openai",
            "model_name": "gpt-6-luna",
            "timeout_seconds": 30,
            "max_output_tokens": 1024,
            "reasoning_effort": "low",
        }
        (self.root / "generation/models.json").write_text(
            json.dumps({"alias": settings})
        )
        code, summary, factory = self.execute(
            lambda _prompt: ModelResponse('{"answer":"답"}'), ["--limit", "1"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(summary["attempted"], 1)
        factory.assert_called_once_with(
            GenerationConfig(
                GenerationProvider.OPENAI,
                "gpt-6-luna",
                30,
                max_output_tokens=1024,
                reasoning_effort="low",
            )
        )

    def test_interrupt_keeps_previously_flushed_record(self):
        calls = 0

        def model(prompt):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt()
            return ModelResponse('{"answer":"답"}')

        with self.assertRaises(KeyboardInterrupt):
            self.execute(model)
        self.assertEqual(len(self.output.read_text().splitlines()), 1)

    def test_existing_output_is_not_overwritten_or_called(self):
        self.output.parent.mkdir()
        self.output.write_text("original")
        with self.assertRaises(FileExistsError):
            self.execute(lambda p: self.fail("must not call model"))
        self.assertEqual(self.output.read_text(), "original")

    def test_invalid_selected_rows_fail_before_output(self):
        for rows in (
            [self.rows[0], self.rows[0]],
            [{**self.rows[0], "question": " "}],
            [self.rows[1]],
        ):
            with self.subTest(rows=rows):
                self.rows = rows
                self.write_rows()
                with self.assertRaises(ValueError):
                    self.execute(lambda p: self.fail("must not call model"))
                self.assertFalse(self.output.exists())

    def test_nonpositive_limit_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            self.execute(lambda p: self.fail("must not call model"), ["--limit", "0"])
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.output.exists())
