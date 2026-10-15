import json
import unittest
from unittest.mock import Mock

from generation.profiles import build_profile_prompt
from generation.prompts import build_prompt
from generation.strategies import execute_strategy
from generation.types import GenerationStatus, ModelResponse


class GenerationProfileTests(unittest.TestCase):
    def test_baseline_is_identical_to_existing_prompt_builder(self):
        question = "휴가 신청은 어디서 하나요?"
        documents = ["문서 하나", "문서 둘"]
        self.assertEqual(
            build_profile_prompt(question, documents), build_prompt(question, documents)
        )

    def test_concise_adds_only_rules_and_keeps_user_input(self):
        prompt = build_profile_prompt("질문", ["문서"], "concise")
        baseline = build_prompt("질문", ["문서"])
        self.assertEqual(prompt.user, baseline.user)
        for rule in (
            "다른 업무의 절차를 가져오지 마세요.",
            "조회 권한이나 조회 경로를 추정하지 마세요.",
            "문의 창구를 실제 처리 메뉴나 처리 절차로 바꾸지 마세요.",
        ):
            self.assertIn(rule, prompt.system)

    def test_examples_are_synthetic_and_do_not_mutate_documents(self):
        documents = ["실제 입력 문서"]
        original = documents.copy()
        prompt = build_profile_prompt("질문", documents, "examples")
        self.assertIn("합성 예시", prompt.system)
        self.assertIn("개인 교육과 외부 강사 등록", prompt.system)
        self.assertIn("개인 교육비 신청", prompt.system)
        self.assertNotIn("공급업체 지급 계좌", prompt.system)
        self.assertIn("AND 조건", prompt.system)
        self.assertNotIn("실제 입력 문서", prompt.system)
        self.assertEqual(documents, original)

    def test_followup_profiles_preserve_documents_and_reference(self):
        reference = build_profile_prompt("질문", ["실제 문서"], "examples")
        for profile in ("examples_coverage", "examples_conditions"):
            prompt = build_profile_prompt("질문", ["실제 문서"], profile)
            self.assertEqual(prompt.user, reference.user)
            self.assertTrue(prompt.system.startswith(reference.system.rstrip()))
            self.assertNotIn("실제 문서", prompt.system)

    def test_json_examples_change_only_example_serialization(self):
        reference = build_profile_prompt("질문", ["문서"], "examples")
        candidate = build_profile_prompt("질문", ["문서"], "examples_json")
        restored = []
        count = 0
        for line in candidate.system.splitlines():
            if line.startswith("답변: "):
                value = json.loads(line.removeprefix("답변: "))
                self.assertEqual(set(value), {"answer"})
                restored.append("답변: " + value["answer"])
                count += 1
            else:
                restored.append(line)
        self.assertEqual(count, 6)
        self.assertEqual("\n".join(restored), reference.system.rstrip("\n"))
        self.assertEqual(candidate.user, reference.user)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            build_profile_prompt("질문", [], "unknown")


class GenerationStrategyTests(unittest.TestCase):
    def setUp(self):
        self.documents = [
            "문서 ID: DOC-1\n개정: 1\n제목: 공통 안내\n본문:\n직원은 포털에서 상태를 조회할 수 있습니다."
        ]
        self.quote = "직원은 포털에서 상태를 조회할 수 있습니다."

    def evidence_response(self, document_id="DOC-1", quote=None):
        return ModelResponse(
            json.dumps(
                {
                    "evidence": [
                        {
                            "document_id": document_id,
                            "quote": quote or self.quote,
                            "scope": "임직원",
                            "conditions": "조건 없음",
                        }
                    ],
                    "missing": [],
                },
                ensure_ascii=False,
            ),
            input_tokens=100,
            output_tokens=20,
            finish_reason="stop",
        )

    def test_single_strategy_preserves_contract_and_records_stage(self):
        response = ModelResponse('{"answer":"포털에서 확인하세요."}', 10, 5, "stop")
        model_call = Mock(return_value=response)

        outcome = execute_strategy(
            "어디에서 확인하나요?", self.documents, model_call, strategy="single"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.COMPLETED)
        self.assertEqual(
            outcome["stages"],
            [
                {
                    "name": "answer",
                    "status": "completed",
                    "raw_text": response.raw_text,
                }
            ],
        )

    def test_evidence_extraction_refusal_stops_without_fallback(self):
        response = ModelResponse(
            None,
            30,
            5,
            "stop",
            refusal="근거 추출 요청을 처리할 수 없습니다.",
        )
        model_call = Mock(return_value=response)

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.REFUSAL)
        self.assertEqual(outcome["result"].refusal, response.refusal)
        self.assertIsNone(outcome["result"].raw_text)
        self.assertEqual(outcome["stages"][0]["status"], "refusal")
        self.assertEqual(outcome["stages"][0]["refusal"], response.refusal)

    def test_final_answer_refusal_survives_usage_aggregation(self):
        extraction = self.evidence_response()
        final = ModelResponse(
            None, 40, 7, "stop", refusal="답변 요청을 처리할 수 없습니다."
        )
        model_call = Mock(side_effect=[extraction, final])

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        self.assertEqual(model_call.call_count, 2)
        result = outcome["result"]
        self.assertEqual(result.status, GenerationStatus.REFUSAL)
        self.assertEqual(result.refusal, final.refusal)
        self.assertEqual((result.input_tokens, result.output_tokens), (140, 27))
        self.assertEqual(outcome["stages"][-1]["status"], "refusal")

    def test_evidence_first_passes_only_verified_quotes_to_final_call(self):
        extraction = self.evidence_response()
        final = ModelResponse('{"answer":"포털에서 확인하세요."}', 40, 10, "stop")
        model_call = Mock(side_effect=[extraction, final])

        outcome = execute_strategy(
            "어디에서 확인하나요?",
            self.documents,
            model_call,
            profile="concise",
            strategy="evidence_first",
        )

        self.assertEqual(model_call.call_count, 2)
        final_prompt = model_call.call_args.args[0]
        self.assertIn("DOC-1", final_prompt.user)
        self.assertIn("공통 안내", final_prompt.user)
        self.assertIn(self.quote, final_prompt.user)
        self.assertNotIn("임직원", final_prompt.user)
        self.assertNotIn("조건 없음", final_prompt.user)
        self.assertNotIn("개정: 1", final_prompt.user)
        self.assertIn("원문과 일치하는지 확인한 문서 ID", final_prompt.system)
        self.assertEqual(outcome["result"].input_tokens, 140)
        self.assertEqual(outcome["result"].output_tokens, 30)
        self.assertEqual(
            [stage["name"] for stage in outcome["stages"]],
            ["evidence_extraction", "answer"],
        )

    def test_unknown_document_id_stops_without_fallback(self):
        model_call = Mock(return_value=self.evidence_response(document_id="DOC-X"))

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.PARSE_ERROR)
        self.assertEqual(outcome["stages"][0]["name"], "evidence_extraction")
        self.assertEqual(
            outcome["stages"][0]["raw_text"], model_call.return_value.raw_text
        )
        self.assertIn(
            "snapshot과 일치하지 않음", outcome["stages"][0]["validation_error"]
        )

    def test_inexact_quote_stops_without_fallback(self):
        model_call = Mock(
            return_value=self.evidence_response(
                quote="직원은 포털에서 모든 정보를 조회합니다."
            )
        )

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.PARSE_ERROR)
        self.assertEqual(
            outcome["stages"][0]["raw_text"], model_call.return_value.raw_text
        )
        self.assertIn(
            "snapshot 본문과 일치하지 않음", outcome["stages"][0]["validation_error"]
        )

    def test_header_quote_is_rejected_even_if_it_matches_snapshot(self):
        model_call = Mock(return_value=self.evidence_response(quote="공통 안내"))

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.PARSE_ERROR)
        self.assertIn(
            "snapshot 본문과 일치하지 않음", outcome["stages"][0]["validation_error"]
        )

    def test_document_without_required_metadata_fails_auditably(self):
        response = ModelResponse('{"evidence": [], "missing": ["정보"]}')
        model_call = Mock(return_value=response)

        outcome = execute_strategy(
            "질문",
            ["문서 메타데이터 없이 본문만 있음"],
            model_call,
            strategy="evidence_first",
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.PARSE_ERROR)
        self.assertIn(
            "ID, 제목 또는 본문 경계", outcome["stages"][0]["validation_error"]
        )

    def test_empty_quote_stops_without_fallback(self):
        model_call = Mock(return_value=self.evidence_response(quote=" "))

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.PARSE_ERROR)
        self.assertEqual(len(outcome["stages"]), 1)

    def test_evidence_count_and_quote_length_are_bounded(self):
        too_many = {
            "evidence": [
                {
                    "document_id": "DOC-1",
                    "quote": self.quote,
                    "scope": "",
                    "conditions": "",
                }
                for _ in range(7)
            ],
            "missing": [],
        }
        too_long = {
            "evidence": [
                {
                    "document_id": "DOC-1",
                    "quote": "x" * 301,
                    "scope": "",
                    "conditions": "",
                }
            ],
            "missing": [],
        }
        for payload in (too_many, too_long):
            with self.subTest(payload=payload["evidence"][0]["quote"][:12]):
                model_call = Mock(
                    return_value=ModelResponse(json.dumps(payload, ensure_ascii=False))
                )
                outcome = execute_strategy(
                    "질문", self.documents, model_call, strategy="evidence_first"
                )
                model_call.assert_called_once()
                self.assertEqual(outcome["result"].status, GenerationStatus.PARSE_ERROR)
                self.assertEqual(len(outcome["stages"]), 1)

    def test_empty_evidence_returns_deterministic_abstention(self):
        response = ModelResponse(
            '{"evidence": [], "missing": ["조회 경로"]}', 30, 10, "stop"
        )
        model_call = Mock(return_value=response)

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.COMPLETED)
        self.assertEqual(
            outcome["result"].answer,
            "제공된 문서에서 질문에 답할 근거를 확인할 수 없습니다.",
        )
        self.assertEqual(outcome["result"].input_tokens, 30)
        self.assertEqual(len(outcome["stages"]), 1)

    def test_final_stage_parse_failure_preserves_both_stage_records(self):
        model_call = Mock(
            side_effect=[self.evidence_response(), ModelResponse("bad JSON", 40, 4)]
        )

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        self.assertEqual(outcome["result"].status, GenerationStatus.PARSE_ERROR)
        self.assertEqual(outcome["result"].input_tokens, 140)
        self.assertEqual(outcome["result"].output_tokens, 24)
        self.assertEqual(outcome["stages"][1]["raw_text"], "bad JSON")

    def test_extraction_timeout_does_not_retry_or_fallback(self):
        model_call = Mock(side_effect=TimeoutError)

        outcome = execute_strategy(
            "질문", self.documents, model_call, strategy="evidence_first"
        )

        model_call.assert_called_once()
        self.assertEqual(outcome["result"].status, GenerationStatus.TIMEOUT)
        self.assertEqual(outcome["stages"][0]["status"], "timeout")

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            execute_strategy("질문", self.documents, Mock(), strategy="fallback")

    def test_unknown_profile_is_rejected_before_extraction_call(self):
        model_call = Mock()
        with self.assertRaises(ValueError):
            execute_strategy(
                "질문",
                self.documents,
                model_call,
                profile="unknown",
                strategy="evidence_first",
            )
        model_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
