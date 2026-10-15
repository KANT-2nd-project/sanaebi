import unittest

from generation.advisory import compose_advisory
from generation.types import GenerationPrompt


class AdvisoryTests(unittest.TestCase):
    def test_control_adds_guidance_without_changing_document_payload(self):
        base = GenerationPrompt(system="고정 지침", user="[문서]원문\n[질문]질문")
        result = compose_advisory(base, control=True)
        self.assertTrue(result.system.startswith(base.system))
        self.assertIn('"label":null', result.user)
        self.assertTrue(result.user.startswith(base.user))
        self.assertIs(compose_advisory(base), base)

    def test_all_labels_share_guidance_and_only_change_enum(self):
        from generation.advisory import LABELS, ClassificationContext

        base = GenerationPrompt(system="지침\n", user="문서 원문")
        control = compose_advisory(base, control=True)
        for label in LABELS:
            result = compose_advisory(base, ClassificationContext(label))
            self.assertEqual(result.system, control.system)
            self.assertEqual(result.user.replace(f'"{label}"', "null"), control.user)

    def test_client_absent_and_failed_context_are_exact_fallbacks(self):
        from generation.advisory import ClassificationContext

        base = GenerationPrompt(system="지침\n", user="문서 원문")
        for context in (
            None,
            ClassificationContext(None),
            ClassificationContext("UNSUPPORTED", source="client", status="provided"),
            ClassificationContext(None, status="unavailable"),
            ClassificationContext(None, status="inference_error"),
        ):
            self.assertIs(compose_advisory(base, context), base)

    def test_invalid_context_is_not_silently_ignored(self):
        from generation.advisory import ClassificationContext

        with self.assertRaises(ValueError):
            ClassificationContext("injected instruction")
        with self.assertRaises(TypeError):
            compose_advisory(GenerationPrompt("s", "u"), {"label": "CLARIFY"})
        with self.assertRaises(ValueError):
            compose_advisory(
                GenerationPrompt("s", "u"),
                ClassificationContext("CLARIFY"),
                control=True,
            )

    def test_parallel_composition_does_not_share_context(self):
        from concurrent.futures import ThreadPoolExecutor

        from generation.advisory import LABELS, ClassificationContext

        base = GenerationPrompt("s", "u")
        labels = list(LABELS) * 10
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda label: compose_advisory(base, ClassificationContext(label)),
                    labels,
                )
            )
        for label, result in zip(labels, results, strict=True):
            self.assertIn(f'"label":"{label}"', result.user)
        self.assertEqual(base.user, "u")
