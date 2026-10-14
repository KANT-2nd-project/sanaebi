import unittest

from generation.config import GenerationConfig, GenerationProvider
from generation.types import GenerationResult, GenerationStatus
from generation_evaluation.metrics import (
    completion_rate,
    count_outcomes,
    group_by_config,
    mean_attempt_seconds,
    mean_completed_seconds,
)
from generation_evaluation.types import GenerationRun


class GenerationMetricsTests(unittest.TestCase):
    def setUp(self):
        self.config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)

    def test_grouping_empty_input(self):
        self.assertEqual(group_by_config([]), {})

    def test_grouping_merges_equal_configs_and_preserves_run_order(self):
        equal_config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)
        first = GenerationRun("1", self.config, None, 0.1, "ConnectError")
        second = GenerationRun("2", equal_config, None, 0.2, "ConnectError")
        groups = group_by_config([first, second])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[self.config], [first, second])

    def test_grouping_separates_provider_model_and_timeout(self):
        configs = [
            self.config,
            GenerationConfig(GenerationProvider.OPENAI, "test-model", 30.0),
            GenerationConfig(GenerationProvider.OLLAMA, "other-model", 30.0),
            GenerationConfig(GenerationProvider.OLLAMA, "test-model", 60.0),
        ]
        runs = [
            GenerationRun(str(i), config, None, 0.1, "ConnectError")
            for i, config in enumerate(configs)
        ]
        groups = group_by_config(runs)
        self.assertEqual(len(groups), 4)
        for run in runs:
            self.assertEqual(groups[run.config], [run])

    def test_completed_mean_excludes_failed_runs(self):
        completed = GenerationResult(
            GenerationStatus.COMPLETED, '{"answer":"답"}', "답"
        )
        runs = [
            GenerationRun("1", self.config, completed, 2.0),
            GenerationRun("2", self.config, completed, 4.0),
            GenerationRun("error", self.config, None, 0.2, "ConnectError"),
        ]
        for status in (
            GenerationStatus.TIMEOUT,
            GenerationStatus.PARSE_ERROR,
            GenerationStatus.EMPTY_ANSWER,
        ):
            runs.append(
                GenerationRun(
                    status.value,
                    self.config,
                    GenerationResult(status, None, None),
                    30.0,
                )
            )
        self.assertEqual(mean_completed_seconds(runs), 3.0)

    def test_completed_mean_distinguishes_no_completion_from_zero(self):
        self.assertIsNone(mean_completed_seconds([]))
        self.assertIsNone(
            mean_completed_seconds(
                [GenerationRun("error", self.config, None, 0.2, "ConnectError")]
            )
        )
        completed = GenerationResult(
            GenerationStatus.COMPLETED, '{"answer":"답"}', "답"
        )
        self.assertEqual(
            mean_completed_seconds(
                [GenerationRun("zero", self.config, completed, 0.0)]
            ),
            0.0,
        )

    def test_mean_attempt_seconds_includes_timeouts_and_execution_errors(self):
        completed = GenerationResult(
            GenerationStatus.COMPLETED, '{"answer":"답"}', "답"
        )
        runs = [
            GenerationRun("1", self.config, completed, 2.0),
            GenerationRun("2", self.config, completed, 4.0),
            GenerationRun(
                "3",
                self.config,
                GenerationResult(GenerationStatus.TIMEOUT, None, None),
                30.0,
            ),
            GenerationRun("4", self.config, None, 0.2, "ConnectError"),
        ]
        self.assertAlmostEqual(mean_attempt_seconds(runs), 9.05)

    def test_mean_attempt_seconds_distinguishes_empty_from_zero(self):
        self.assertIsNone(mean_attempt_seconds([]))
        run = GenerationRun("error", self.config, None, 0.0, "ConnectError")
        self.assertEqual(mean_attempt_seconds([run]), 0.0)

    def test_completion_rate_includes_failed_attempts(self):
        completed = GenerationResult(
            GenerationStatus.COMPLETED, '{"answer":"답"}', "답"
        )
        runs = [
            GenerationRun("1", self.config, completed, 0.25),
            GenerationRun("2", self.config, completed, 0.25),
            GenerationRun(
                "3",
                self.config,
                GenerationResult(GenerationStatus.PARSE_ERROR, "bad", None),
                0.25,
            ),
            GenerationRun(
                "4",
                self.config,
                GenerationResult(GenerationStatus.TIMEOUT, None, None),
                30.0,
            ),
            GenerationRun("5", self.config, None, 0.5, "ConnectError"),
        ]
        self.assertAlmostEqual(completion_rate(runs), 0.4)

    def test_completion_rate_distinguishes_no_runs_from_all_failures(self):
        self.assertIsNone(completion_rate([]))
        runs = [GenerationRun("error", self.config, None, 0.5, "ConnectError")]
        self.assertEqual(completion_rate(runs), 0.0)

    def test_completion_rate_all_completed(self):
        result = GenerationResult(GenerationStatus.COMPLETED, '{"answer":"답"}', "답")
        self.assertEqual(
            completion_rate([GenerationRun("1", self.config, result, 0.25)]), 1.0
        )

    def test_completion_rate_rejects_missing_result_and_error(self):
        with self.assertRaises(ValueError):
            completion_rate([GenerationRun("invalid", self.config, None, 0.25)])

    def test_empty_input_has_all_zero_counts(self):
        self.assertEqual(
            count_outcomes([]),
            {
                "total": 0,
                "completed": 0,
                "parse_error": 0,
                "empty_answer": 0,
                "timeout": 0,
                "execution_error": 0,
            },
        )

    def test_every_run_is_counted_once_including_failures(self):
        runs = [
            GenerationRun(
                str(index),
                self.config,
                GenerationResult(status, None, None),
                0.25,
            )
            for index, status in enumerate(
                [
                    GenerationStatus.COMPLETED,
                    GenerationStatus.COMPLETED,
                    GenerationStatus.PARSE_ERROR,
                    GenerationStatus.EMPTY_ANSWER,
                    GenerationStatus.TIMEOUT,
                ]
            )
        ]
        runs.append(GenerationRun("error", self.config, None, 0.5, "ConnectError"))
        counts = count_outcomes(runs)
        self.assertEqual(
            counts,
            {
                "total": 6,
                "completed": 2,
                "parse_error": 1,
                "empty_answer": 1,
                "timeout": 1,
                "execution_error": 1,
            },
        )
        self.assertEqual(
            counts["total"], sum(v for k, v in counts.items() if k != "total")
        )

    def test_missing_result_and_error_is_rejected(self):
        with self.assertRaises(ValueError):
            count_outcomes([GenerationRun("invalid", self.config, None, 0.25)])
