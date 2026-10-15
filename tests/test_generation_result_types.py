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
        cases.extend(
            [
                (GenerationStatus.REFUSAL, "raw", "답"),
                (GenerationStatus.REFUSAL, "raw", None),
                (GenerationStatus.REFUSAL, None, None),
            ]
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

    def test_refusal_requires_text_and_may_preserve_absent_raw_text(self):
        result = GenerationResult(
            GenerationStatus.REFUSAL,
            None,
            None,
            refusal="요청을 처리할 수 없습니다.",
        )
        self.assertIsNone(result.raw_text)
        self.assertEqual(result.refusal, "요청을 처리할 수 없습니다.")

        for value in (None, "", "  "):
            with self.subTest(refusal=value), self.assertRaises(ValueError):
                GenerationResult(GenerationStatus.REFUSAL, "raw", None, refusal=value)
