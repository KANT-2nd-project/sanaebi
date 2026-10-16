import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.answering.adapter import GenerationAnswerer
from app.settings import get_rag_prompt_profile
from generation.presets import load_runtime_settings
from generation.profiles import RAG_PROMPT_PROFILE, build_profile_prompt
from generation.service import _build_prompt_values

CANDIDATES = {
    "examples_answer_scope_v6_rag_readability": "examples_answer_scope_v6",
    "examples_answer_scope_v7_rag_readability": "examples_answer_scope_v7_readability",
}
ROOT = Path(__file__).resolve().parents[2]


class RagReadabilityProfilesTests(unittest.TestCase):
    def test_exact_archived_delta_and_shared_input(self):
        historical = json.loads(
            (ROOT / "generation/archive/prompt_profiles.json").read_text()
        )
        v5 = build_profile_prompt("질문", [], "examples_answer_scope_v5")
        from generation.prompts import build_prompt

        base = build_prompt("질문", [])
        v5_suffix = v5.system[len(base.system.rstrip()) + 2 : -1]
        reference = build_profile_prompt("질문", ["근거"], RAG_PROMPT_PROFILE)
        for candidate, archived in CANDIDATES.items():
            with self.subTest(candidate=candidate):
                expected_delta = historical[archived].removeprefix(v5_suffix + "\n\n")
                actual = build_profile_prompt("질문", ["근거"], candidate)
                self.assertEqual(
                    actual.system,
                    reference.system.rstrip() + "\n\n" + expected_delta + "\n",
                )
                self.assertEqual(actual.user, reference.user)

    def test_candidates_support_no_matches_and_empty_snapshot(self):
        settings = load_runtime_settings(ROOT)
        for profile in CANDIDATES:
            answerer = GenerationAnswerer(replace(settings, prompt_profile=profile))
            self.assertTrue(answerer.supports_empty_retrieval)
            for state in ("no_matches", "no_published_documents"):
                values = _build_prompt_values(
                    {
                        "question": "안녕하세요",
                        "documents": [],
                        "prompt_profile": profile,
                        "evidence_state": state,
                    }
                )
                self.assertIn("JSON만 출력", values["system"])
            with patch.dict("os.environ", {"SANAEBI_RAG_PROMPT_PROFILE": profile}):
                self.assertEqual(get_rag_prompt_profile(), profile)

    def test_full_profile_rejects_evidence_state(self):
        with self.assertRaises(ValueError):
            _build_prompt_values(
                {
                    "question": "질문",
                    "documents": [],
                    "prompt_profile": "examples_answer_scope_v5",
                    "evidence_state": "no_matches",
                }
            )

    def test_candidate_adapter_preserves_empty_input_and_json_parsing(self):
        from app.answering.input import AnswerInput
        from app.answering.output import LLMResponseError
        from generation.types import ModelResponse

        settings = load_runtime_settings(ROOT)
        for profile in CANDIDATES:
            for state in ("no_matches", "no_published_documents"):
                captured = []

                def model(prompt, captured=captured):
                    captured.append(prompt)
                    return ModelResponse(
                        raw_text='{"answer":"안녕하세요.\\n\\n어떤 업무가 궁금하신가요?"}',
                        finish_reason="stop",
                    )

                with patch(
                    "app.answering.adapter.build_managed_model_call", return_value=model
                ):
                    answerer = GenerationAnswerer(
                        replace(settings, prompt_profile=profile)
                    )
                    answer = answerer.answer_input(
                        AnswerInput("안녕하세요", (), "snapshot", evidence_state=state)
                    )
                self.assertIn("\n\n", answer)
                self.assertEqual(len(captured), 1)
                self.assertIn("JSON만 출력", captured[0].system)
            with patch(
                "app.answering.adapter.build_managed_model_call",
                return_value=lambda prompt: ModelResponse(
                    raw_text="잘못된 형식", finish_reason="stop"
                ),
            ):
                answerer = GenerationAnswerer(replace(settings, prompt_profile=profile))
                with self.assertRaises(LLMResponseError):
                    answerer.answer_input(
                        AnswerInput(
                            "안녕하세요", (), "snapshot", evidence_state="no_matches"
                        )
                    )
