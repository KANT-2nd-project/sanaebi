import unittest
from unittest.mock import Mock, patch

from generation.config import GenerationConfig, GenerationProvider
from generation.types import GenerationPrompt, GenerationResult, GenerationStatus
from generation_evaluation.runner import run_case


class GenerationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)
        self.prompt = GenerationPrompt(system="규칙", user="질문")

    def test_records_case_config_response_and_elapsed_time(self):
        events = []
        ticks = iter((100.0, 100.25))

        def clock():
            events.append("clock")
            return next(ticks)

        raw = '{"answer": " 안내 "}'

        def model_call(prompt):
            events.append("model")
            self.assertIs(prompt, self.prompt)
            return raw

        with patch("generation_evaluation.runner.perf_counter", side_effect=clock):
            run = run_case("case-001", self.config, self.prompt, model_call)

        self.assertEqual(events, ["clock", "model", "clock"])
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
            run = run_case("case-timeout", self.config, self.prompt, model_call)
        model_call.assert_called_once_with(self.prompt)
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
            run = run_case("case-error", self.config, self.prompt, model_call)
        self.assertEqual(run.case_id, "case-error")
        self.assertIs(run.config, self.config)
        self.assertIsNone(run.result)
        self.assertEqual(run.error_type, "RuntimeError")
        self.assertEqual(run.elapsed_seconds, 0.75)
        model_call.assert_called_once_with(self.prompt)

    def test_parse_failure_is_a_result_not_an_execution_error(self):
        with patch("generation_evaluation.runner.perf_counter", side_effect=(1.0, 1.5)):
            run = run_case(
                "case-parse", self.config, self.prompt, Mock(return_value="bad")
            )
        self.assertEqual(
            run.result, GenerationResult(GenerationStatus.PARSE_ERROR, "bad", None)
        )
        self.assertIsNone(run.error_type)

    def test_user_interrupt_propagates(self):
        error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt) as caught:
            run_case("case-stop", self.config, self.prompt, Mock(side_effect=error))
        self.assertIs(caught.exception, error)
