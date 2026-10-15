import csv
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from generation import __main__ as single
from generation.presets import load_preset, load_runtime_settings
from generation.profiles import DEFAULT_PROMPT_PROFILE, build_profile_prompt
from generation.prompts import build_prompt
from generation.providers import build_openai_model
from generation.service import generate_from_documents
from generation.types import ModelResponse
from generation_evaluation import __main__ as batch
from generation_evaluation.metrics import group_by_config, summarize_runs
from generation_evaluation.reporting import run_from_dict, run_to_dict
from generation_evaluation.runner import run_case
from tests.support.paths import ROOT


class RuntimeDefaultsTests(unittest.TestCase):
    def test_adopted_prompt_and_provider_options(self):
        preset = load_preset(ROOT)
        closure = ROOT / "generation_evaluation/reports/2026-10-15-answer-grounding-v3"
        self.assertEqual(DEFAULT_PROMPT_PROFILE, "examples_answer_scope_v3")
        self.assertEqual(preset.prompt_profile, DEFAULT_PROMPT_PROFILE)
        self.assertEqual(
            load_runtime_settings(ROOT).prompt_profile, preset.prompt_profile
        )
        expected = (closure / "candidate-system-prompt.txt").read_text()
        self.assertEqual(
            build_profile_prompt("질문", [], preset.prompt_profile).system, expected
        )
        with patch("generation.providers.ChatOpenAI") as client:
            build_openai_model(preset.config)
        self.assertEqual(
            client.call_args.kwargs,
            {
                "model": "gpt-6-luna",
                "timeout": 180,
                "max_retries": 0,
                "max_completion_tokens": 4096,
                "reasoning_effort": "xhigh",
            },
        )

    def test_default_and_historical_profile_are_separate(self):
        seen = []

        def model(prompt):
            seen.append(prompt)
            return ModelResponse('{"answer":"답변입니다."}')

        preset = load_preset(ROOT)
        current = run_case("case", preset.config, "질문", ["문서"], model)
        legacy = run_to_dict(current)
        del legacy["prompt_profile"]
        unknown = run_from_dict(legacy)
        self.assertIsNone(unknown.prompt_profile)
        self.assertEqual(run_from_dict(run_to_dict(current)), current)
        baseline = replace(current, prompt_profile="baseline")
        summaries = summarize_runs([current, baseline, unknown])
        self.assertEqual(len(summaries), 3)
        self.assertEqual(len(group_by_config([current, baseline, unknown])), 1)
        generate_from_documents("질문", ["문서"], model, prompt_profile="baseline")
        self.assertEqual(seen[-1], build_prompt("질문", ["문서"]))
        self.assertEqual(current.prompt_profile, DEFAULT_PROMPT_PROFILE)

    def test_two_default_clis_send_identical_prompt_and_config(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "generation").mkdir()
            (root / "data").mkdir()
            (root / "tmp").mkdir()
            for name in ("models.json", "experiments.json"):
                (root / "generation" / name).write_bytes(
                    (ROOT / "generation" / name).read_bytes()
                )
            (root / "tmp/generation-cli-documents.jsonl").write_text(
                json.dumps(
                    {
                        "document_id": "doc",
                        "revision_number": 1,
                        "title": "안내",
                        "document": "신청은 인사 포털에서 합니다.",
                    }
                )
                + "\n"
            )
            with (root / "data/dataset.csv").open("w") as f:
                writer = csv.writer(f)
                writer.writerow(["question_id", "question", "label"])
                writer.writerow(["Q1", "어디서 신청하나요?", "SEARCH_KNOWLEDGE"])
            seen = []

            def model(prompt):
                seen.append(prompt)
                return ModelResponse('{"answer":"인사 포털에서 신청합니다."}')

            records = []
            configs = []
            output = root / "batch.jsonl"
            for module, argv in [
                (single, ["generation", "--question", "어디서 신청하나요?"]),
                (
                    batch,
                    ["generation_evaluation", "--limit", "1", "--output", str(output)],
                ),
            ]:
                with (
                    patch.object(
                        module,
                        "__file__",
                        str(root / module.__package__ / "__main__.py"),
                    ),
                    patch.object(
                        module, "build_model_call", return_value=model
                    ) as factory,
                    patch("sys.argv", argv),
                    redirect_stdout(StringIO()) as stdout,
                ):
                    self.assertEqual(module.main(), 0)
                configs.append(factory.call_args.args[0])
                records.append(
                    json.loads(stdout.getvalue())
                    if module is single
                    else json.loads(output.read_text())
                )
            self.assertEqual(configs[0], configs[1])
            self.assertEqual(seen[0], seen[1])
            self.assertEqual(records[0]["prompt_sha256"], records[1]["prompt_sha256"])
            self.assertEqual(records[0]["prompt_profile"], DEFAULT_PROMPT_PROFILE)

    def test_unknown_alias_and_profile_fail_before_client(self):
        with self.assertRaisesRegex(ValueError, "등록되지 않은 모델"):
            load_preset(ROOT, model="qwen3-4b-q4km-96k")
        with self.assertRaisesRegex(ValueError, "등록되지 않은 실험"):
            load_preset(ROOT, experiment="company-full-context-v1")
        with patch("generation.providers.ChatOpenAI") as client:
            with self.assertRaises(ValueError):
                generate_from_documents("질문", [], client, prompt_profile="unknown")
            client.assert_not_called()
