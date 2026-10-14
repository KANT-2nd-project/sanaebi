import unittest

from generation.types import GenerationResult, GenerationStatus


class GenerationResultTests(unittest.TestCase):
    def test_rejects_inconsistent_status_and_content(self):
        cases = [
            (GenerationStatus.COMPLETED, None, "답"),
            (GenerationStatus.COMPLETED, "raw", None),
            (GenerationStatus.COMPLETED, "raw", ""),
            (GenerationStatus.COMPLETED, "raw", " \n\t"),
            (GenerationStatus.TIMEOUT, "", None),
            (GenerationStatus.TIMEOUT, None, "답"),
        ]
        for status in (GenerationStatus.PARSE_ERROR, GenerationStatus.EMPTY_ANSWER):
            cases.extend(
                [(status, None, None), (status, "raw", "답"), (status, "raw", "")]
            )
        for status, raw, answer in cases:
            with (
                self.subTest(status=status, raw=raw, answer=answer),
                self.assertRaises(ValueError),
            ):
                GenerationResult(status, raw, answer)

    def test_rejects_invalid_field_types(self):
        for status in ("completed", None, 1):
            with self.subTest(status=status), self.assertRaises(TypeError):
                GenerationResult(status, "raw", "답")
        for value in (1, True, [], {}):
            with self.subTest(raw=value), self.assertRaises(TypeError):
                GenerationResult(GenerationStatus.COMPLETED, value, "답")
            with self.subTest(answer=value), self.assertRaises(TypeError):
                GenerationResult(GenerationStatus.COMPLETED, "raw", value)

    def test_valid_results_preserve_text(self):
        result = GenerationResult(GenerationStatus.COMPLETED, " raw\n", " 답 \n")
        self.assertEqual(result.raw_text, " raw\n")
        self.assertEqual(result.answer, " 답 \n")
        self.assertIsNone(
            GenerationResult(GenerationStatus.TIMEOUT, None, None).raw_text
        )
        for status in (GenerationStatus.PARSE_ERROR, GenerationStatus.EMPTY_ANSWER):
            self.assertEqual(GenerationResult(status, "", None).raw_text, "")
