import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch

from generation.config import GenerationConfig, GenerationProvider
from generation.profiles import DEFAULT_PROMPT_PROFILE, build_profile_prompt
from generation.types import GenerationResult, GenerationStatus, ModelResponse
from generation_evaluation.runner import run_case


class GenerationRunnerTests(unittest.TestCase):
    def test_execution_error_message_is_not_exposed(self):
        stderr = StringIO()
        with redirect_stderr(stderr):
            run = run_case(
                "diagnostic",
                self.config,
                self.question,
                self.documents,
                Mock(side_effect=RuntimeError("credential=secret-test-value")),
            )
        self.assertEqual(run.error_type, "RuntimeError")
        self.assertIsNone(run.result)
        self.assertEqual(stderr.getvalue(), "[diagnostic] RuntimeError\n")

    def test_prompt_build_failure_is_recorded_without_model_call(self):
        model_call = Mock()
        with (
            patch(
                "generation.service.build_profile_prompt",
                side_effect=ValueError("invalid input"),
            ),
            patch("generation_evaluation.runner.perf_counter", side_effect=(1.0, 1.25)),
        ):
            run = run_case(
                "case-build", self.config, self.question, self.documents, model_call
            )
        self.assertIsNone(run.result)
        self.assertEqual(run.error_type, "ValueError")
        self.assertEqual(run.elapsed_seconds, 0.25)
        model_call.assert_not_called()
        self.assertIsNone(run.prompt_sha256)
        self.assertRegex(run.documents_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(run.document_count, 1)

    def setUp(self):
        self.config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)
        self.question = "예약은 어디에서 하나요?"
        self.documents = ["예약은 사내 포털에서 합니다."]
        self.prompt = build_profile_prompt(
            self.question, self.documents, DEFAULT_PROMPT_PROFILE
        )

    def test_records_case_config_response_and_elapsed_time(self):
        events = []
        ticks = iter((100.0, 100.25))

        def clock():
            events.append("clock")
            return next(ticks)

        raw = '{"answer": " 안내 "}'

        def model_call(prompt):
            events.append("model")
            self.assertEqual(prompt, self.prompt)
            return ModelResponse(raw)

        def record_build(question, documents, profile):
            events.append("prompt")
            self.assertEqual(question, self.question)
            self.assertIs(documents, self.documents)
            return build_profile_prompt(question, documents, profile)

        with (
            patch("generation_evaluation.runner.perf_counter", side_effect=clock),
            patch("generation.service.build_profile_prompt", side_effect=record_build),
        ):
            run = run_case(
                "case-001", self.config, self.question, self.documents, model_call
            )

        self.assertEqual(events, ["clock", "prompt", "model", "clock"])
        self.assertEqual(run.case_id, "case-001")
        self.assertIs(run.config, self.config)
        self.assertEqual(run.elapsed_seconds, 0.25)
        self.assertIsNone(run.error_type)
        self.assertEqual(
            run.result, GenerationResult(GenerationStatus.COMPLETED, raw, "안내")
        )

    def test_timeout_is_recorded_with_elapsed_time(self):
        model_call = Mock(side_effect=TimeoutError("timeout"))
        with patch(
            "generation_evaluation.runner.perf_counter", side_effect=(10.0, 12.5)
        ):
            run = run_case(
                "case-timeout", self.config, self.question, self.documents, model_call
            )
        model_call.assert_called_once_with(self.prompt)
        self.assertRegex(run.prompt_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(run.elapsed_seconds, 2.5)
        self.assertIsNone(run.error_type)
        self.assertEqual(
            run.result, GenerationResult(GenerationStatus.TIMEOUT, None, None)
        )

    def test_unexpected_error_is_recorded_with_case_config_and_time(self):
        error = RuntimeError("unexpected")
        model_call = Mock(side_effect=error)
        with patch(
            "generation_evaluation.runner.perf_counter", side_effect=(20.0, 20.75)
        ):
            run = run_case(
                "case-error", self.config, self.question, self.documents, model_call
            )
        self.assertEqual(run.case_id, "case-error")
        self.assertIs(run.config, self.config)
        self.assertIsNone(run.result)
        self.assertEqual(run.error_type, "RuntimeError")
        self.assertEqual(run.elapsed_seconds, 0.75)
        model_call.assert_called_once_with(self.prompt)

    def test_parse_failure_is_a_result_not_an_execution_error(self):
        with patch("generation_evaluation.runner.perf_counter", side_effect=(1.0, 1.5)):
            run = run_case(
                "case-parse",
                self.config,
                self.question,
                self.documents,
                Mock(return_value=ModelResponse("bad")),
            )
        self.assertEqual(
            run.result, GenerationResult(GenerationStatus.PARSE_ERROR, "bad", None)
        )
        self.assertIsNone(run.error_type)

    def test_user_interrupt_propagates(self):
        error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt) as caught:
            run_case(
                "case-stop",
                self.config,
                self.question,
                self.documents,
                Mock(side_effect=error),
            )
        self.assertIs(caught.exception, error)
