import unittest
from dataclasses import replace

from generation.config import (
    GenerationConfig,
    GenerationOutputMode,
    GenerationProvider,
)
from generation.types import GenerationResult, GenerationStatus
from generation_evaluation.metrics import (
    completion_rate,
    count_outcomes,
    group_by_config,
    mean_attempt_seconds,
    mean_completed_seconds,
    summarize_runs,
)
from generation_evaluation.types import GenerationRun


class GenerationMetricsTests(unittest.TestCase):
    def comparison_runs(self):
        other = GenerationConfig(GenerationProvider.OLLAMA, "other", 30)
        return [
            GenerationRun(
                case,
                config,
                None,
                0.2,
                "ConnectError",
                documents_sha256="a" * 64,
                document_count=2,
                prompt_sha256=prompt * 64,
            )
            for config in (self.config, other)
            for case, prompt in (("case-a", "b"), ("case-b", "c"))
        ]

    def test_comparable_summary_accepts_multiple_questions_and_keeps_failures(self):
        from generation_evaluation import metrics

        runs = self.comparison_runs()
        summaries = metrics.summarize_comparable_runs(runs)
        self.assertEqual(summaries, summarize_runs(runs))
        self.assertEqual([s.counts["execution_error"] for s in summaries], [2, 2])
        self.assertEqual(metrics.summarize_comparable_runs([]), [])

    def test_comparable_summary_rejects_mixed_or_unknown_identity(self):
        from generation_evaluation import metrics

        for updates in (
            {"documents_sha256": "d" * 64},
            {"document_count": 3},
            {"prompt_sha256": "d" * 64},
            {"documents_sha256": None},
            {"document_count": None},
            {"prompt_sha256": None},
            {"case_id": " "},
        ):
            runs = self.comparison_runs()
            runs[-1] = replace(runs[-1], **updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                metrics.summarize_comparable_runs(runs)

    def test_comparable_summary_rejects_missing_cases_and_unbalanced_attempts(self):
        from generation_evaluation import metrics

        runs = self.comparison_runs()
        for mismatched in (runs[:-1], runs + [runs[0]]):
            with self.subTest(runs=mismatched), self.assertRaises(ValueError):
                metrics.summarize_comparable_runs(mismatched)
        repeated = runs + runs
        self.assertEqual(
            metrics.summarize_comparable_runs(repeated), summarize_runs(repeated)
        )

    def test_truncated_is_counted_as_attempt_but_not_completion(self):
        runs = [
            GenerationRun(
                "ok",
                self.config,
                GenerationResult(GenerationStatus.COMPLETED, '{"answer":"답"}', "답"),
                2,
            ),
            GenerationRun(
                "cut",
                self.config,
                GenerationResult(
                    GenerationStatus.TRUNCATED, '{"answer":', None, 10, 512, "length"
                ),
                4,
            ),
            GenerationRun(
                "refusal",
                self.config,
                GenerationResult(
                    GenerationStatus.REFUSAL,
                    None,
                    None,
                    refusal="요청을 처리할 수 없습니다.",
                ),
                3,
            ),
        ]
        counts = count_outcomes(runs)
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["truncated"], 1)
        self.assertEqual(counts["refusal"], 1)
        self.assertEqual(counts["completed"], 1)
        self.assertAlmostEqual(completion_rate(runs), 1 / 3)
        self.assertEqual(mean_attempt_seconds(runs), 3)
        self.assertEqual(mean_completed_seconds(runs), 2)

    def setUp(self):
        self.config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)

    def test_summary_empty_input(self):
        self.assertEqual(summarize_runs([]), [])

    def test_summaries_keep_config_metrics_separate(self):
        other = GenerationConfig(GenerationProvider.OPENAI, "other-model", 30.0)
        completed = GenerationResult(
            GenerationStatus.COMPLETED, '{"answer":"답"}', "답"
        )
        timeout = GenerationResult(GenerationStatus.TIMEOUT, None, None)
        runs = [
            GenerationRun("a", self.config, completed, 2.0),
            GenerationRun("a", other, timeout, 30.0),
            GenerationRun("b", self.config, completed, 4.0),
        ]
        summaries = summarize_runs(runs)
        self.assertEqual(len(summaries), 2)
        by_config = {summary.config: summary for summary in summaries}
        first = by_config[self.config]
        second = by_config[other]
        self.assertEqual(first.counts, count_outcomes([runs[0], runs[2]]))
        self.assertEqual(first.completion_rate, 1.0)
        self.assertEqual(first.mean_attempt_seconds, 3.0)
        self.assertEqual(first.mean_completed_seconds, 3.0)
        self.assertEqual(second.counts, count_outcomes([runs[1]]))
        self.assertEqual(second.completion_rate, 0.0)
        self.assertEqual(second.mean_attempt_seconds, 30.0)
        self.assertIsNone(second.mean_completed_seconds)

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

    def test_grouping_separates_output_modes(self):
        prompt_json = GenerationConfig(
            GenerationProvider.OPENAI,
            "test-model",
            30.0,
            output_mode=GenerationOutputMode.PROMPT_JSON,
        )
        strict = replace(
            prompt_json, output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA
        )
        runs = [
            GenerationRun("prompt", prompt_json, None, 0.1, "ConnectError"),
            GenerationRun("strict", strict, None, 0.1, "ConnectError"),
        ]
        groups = group_by_config(runs)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[prompt_json], [runs[0]])
        self.assertEqual(groups[strict], [runs[1]])

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
                    GenerationResult(
                        status,
                        None if status is GenerationStatus.TIMEOUT else "raw",
                        None,
                    ),
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
                "truncated": 0,
                "refusal": 0,
            },
        )

    def test_every_run_is_counted_once_including_failures(self):
        runs = [
            GenerationRun(
                str(index),
                self.config,
                GenerationResult(
                    status,
                    None if status is GenerationStatus.TIMEOUT else "raw",
                    "답" if status is GenerationStatus.COMPLETED else None,
                    refusal=(
                        "요청을 처리할 수 없습니다."
                        if status is GenerationStatus.REFUSAL
                        else None
                    ),
                ),
                0.25,
            )
            for index, status in enumerate(
                [
                    GenerationStatus.COMPLETED,
                    GenerationStatus.COMPLETED,
                    GenerationStatus.PARSE_ERROR,
                    GenerationStatus.EMPTY_ANSWER,
                    GenerationStatus.TIMEOUT,
                    GenerationStatus.REFUSAL,
                ]
            )
        ]
        runs.append(GenerationRun("error", self.config, None, 0.5, "ConnectError"))
        counts = count_outcomes(runs)
        self.assertEqual(
            counts,
            {
                "total": 7,
                "completed": 2,
                "parse_error": 1,
                "empty_answer": 1,
                "timeout": 1,
                "execution_error": 1,
                "truncated": 0,
                "refusal": 1,
            },
        )
        self.assertEqual(
            counts["total"], sum(v for k, v in counts.items() if k != "total")
        )
