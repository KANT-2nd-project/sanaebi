import unittest

from generation.config import GenerationConfig, GenerationProvider
from generation.types import GenerationResult, GenerationStatus
from generation_evaluation.types import GenerationRun


class GenerationRunValidationTests(unittest.TestCase):
    def setUp(self):
        self.config = GenerationConfig(GenerationProvider.OLLAMA, "example", 30.0)
        self.completed = GenerationResult(
            GenerationStatus.COMPLETED, '{"answer":"답"}', "답"
        )

    def test_zero_elapsed_time_is_valid(self):
        run = GenerationRun("zero", self.config, self.completed, 0.0)
        self.assertEqual(run.elapsed_seconds, 0.0)

    def test_result_and_execution_error_records_are_valid(self):
        for result in (
            self.completed,
            GenerationResult(GenerationStatus.TIMEOUT, None, None),
        ):
            with self.subTest(result=result):
                run = GenerationRun("result", self.config, result, 0.25)
                self.assertIs(run.result, result)
        run = GenerationRun("error", self.config, None, 0.25, "ConnectError")
        self.assertEqual(run.error_type, "ConnectError")

    def test_negative_or_nonfinite_elapsed_time_is_rejected(self):
        for elapsed in (-1.0, float("inf"), float("-inf"), float("nan")):
            with self.subTest(elapsed=elapsed), self.assertRaises(ValueError):
                GenerationRun("invalid", self.config, self.completed, elapsed)

    def test_missing_result_and_error_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            GenerationRun("invalid", self.config, None, 0.25)

    def test_result_and_error_cannot_coexist(self):
        with self.assertRaises(ValueError):
            GenerationRun("invalid", self.config, self.completed, 0.25, "RuntimeError")

    def test_empty_or_whitespace_error_name_is_rejected(self):
        for error in ("", " ", "\n\t"):
            with self.subTest(error=error), self.assertRaises(ValueError):
                GenerationRun("invalid", self.config, None, 0.25, error)
