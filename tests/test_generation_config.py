import unittest

from generation.config import GenerationConfig, GenerationProvider


class GenerationConfigTests(unittest.TestCase):
    def test_token_limits_reject_wrong_types_and_nonpositive_values(self):
        for field in ("context_window", "max_output_tokens"):
            for value in (True, False, 1.5, "512", [], {}):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(TypeError),
                ):
                    GenerationConfig(
                        GenerationProvider.OLLAMA, "model", 30, **{field: value}
                    )
            for value in (0, -1):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValueError),
                ):
                    GenerationConfig(
                        GenerationProvider.OLLAMA, "model", 30, **{field: value}
                    )

    def test_output_must_leave_room_for_input(self):
        for output in (512, 513):
            with self.subTest(output=output), self.assertRaises(ValueError):
                GenerationConfig(GenerationProvider.OLLAMA, "model", 30, 512, output)
        for context, output in ((None, None), (512, None), (None, 1), (512, 511)):
            with self.subTest(context=context, output=output):
                config = GenerationConfig(
                    GenerationProvider.OLLAMA, "model", 30, context, output
                )
                self.assertEqual(
                    (config.context_window, config.max_output_tokens), (context, output)
                )

    def test_nonfinite_timeouts_are_rejected(self):
        for timeout in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                GenerationConfig(GenerationProvider.OLLAMA, "example", timeout)

    def test_positive_fractional_timeout_is_accepted(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "example", 0.25)
        self.assertEqual(config.timeout_seconds, 0.25)

    def test_model_names_are_not_restricted_to_current_candidates(self):
        for name in (
            "gpt-6-luna",
            "qwen3:4b-instruct-2507-q4_K_M",
            "future-experiment-model",
        ):
            with self.subTest(name=name):
                config = GenerationConfig(
                    provider=GenerationProvider.OLLAMA,
                    model_name=name,
                    timeout_seconds=30.0,
                )
                self.assertEqual(config.model_name, name)
                self.assertEqual(config.timeout_seconds, 30.0)

    def test_blank_model_names_are_rejected(self):
        for name in ("", " ", "\n\t"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                GenerationConfig(
                    provider=GenerationProvider.OLLAMA,
                    model_name=name,
                    timeout_seconds=30.0,
                )

    def test_nonpositive_timeout_is_rejected(self):
        for timeout in (0, -1, -0.5):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                GenerationConfig(
                    provider=GenerationProvider.OLLAMA,
                    model_name="example",
                    timeout_seconds=timeout,
                )

    def test_both_providers_are_accepted(self):
        for provider in GenerationProvider:
            with self.subTest(provider=provider):
                config = GenerationConfig(provider, "example", 30.0)
                self.assertIs(config.provider, provider)

    def test_plain_strings_and_other_types_are_rejected_as_provider(self):
        for provider in ("ollama", "openai", "unknown", None, 1):
            with self.subTest(provider=provider), self.assertRaises(TypeError):
                GenerationConfig(provider, "example", 30.0)
