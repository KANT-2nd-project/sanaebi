"""Real adapter composition, fallback and concurrent request isolation."""

import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.answering.adapter import GenerationAnswerer
from generation.advisory import ClassificationContext, compose_advisory
from generation.presets import load_runtime_settings
from generation.types import ModelResponse
from tests.runtime.test_langchain_adapter import snapshot
from tests.support.paths import ROOT


class AdvisoryPromptTests(unittest.TestCase):
    def test_full_and_rag_reuse_exact_composer_and_fallback(self):
        for retrieved in (False, True):
            with self.subTest(retrieved=retrieved):
                provider = Mock(return_value=ModelResponse('{"answer":"답변"}'))
                answerer = GenerationAnswerer(load_runtime_settings(ROOT))
                with patch.object(answerer, "_get_client", return_value=provider):
                    context = snapshot()
                    method = answerer.answer
                    if retrieved:
                        context = SimpleNamespace(
                            snapshot_fingerprint="fixed",
                            evidence=(
                                SimpleNamespace(
                                    knowledge_id="policy",
                                    title="규정",
                                    text="근거",
                                    revision=1,
                                ),
                            ),
                        )
                        method = answerer.answer_retrieved
                    method("질문", context)
                    original = provider.call_args.args[0]
                    for label in ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"):
                        classification = ClassificationContext(label)
                        method("질문", context, classification_context=classification)
                        self.assertEqual(
                            provider.call_args.args[0],
                            compose_advisory(original, classification),
                        )
                    for classification in (
                        None,
                        ClassificationContext(None),
                        ClassificationContext(
                            "CLARIFY", source="client", status="provided"
                        ),
                        ClassificationContext(None, status="inference_error"),
                    ):
                        method("질문", context, classification_context=classification)
                        self.assertEqual(provider.call_args.args[0], original)
                asyncio.run(answerer.aclose())

    def test_simultaneous_requests_do_not_share_label_or_question(self):
        barrier = Barrier(3)
        seen = []

        def provider(prompt):
            barrier.wait(timeout=10)
            seen.append(prompt)
            return ModelResponse('{"answer":"답변"}')

        answerer = GenerationAnswerer(load_runtime_settings(ROOT))
        labels = ("SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED")
        with (
            patch.object(answerer, "_get_client", return_value=provider),
            ThreadPoolExecutor(max_workers=3) as pool,
        ):
            futures = [
                pool.submit(
                    answerer.answer,
                    f"질문-{i}",
                    snapshot(),
                    classification_context=ClassificationContext(label),
                )
                for i, label in enumerate(labels)
            ]
            self.assertEqual([f.result() for f in futures], ["답변"] * 3)
        for i, label in enumerate(labels):
            [prompt] = [p for p in seen if f"질문-{i}" in p.user]
            self.assertIn(f'"label":"{label}"', prompt.user)
            self.assertEqual(prompt.user.count("[분류 참고 데이터]"), 1)
        asyncio.run(answerer.aclose())
