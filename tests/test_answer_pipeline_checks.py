"""생성 응답의 {"text"} 구조, 자동 점검 P1~P5·A1~A6, 모델별 실측값이 기준대로 나오는지 본다."""

import json
import unittest

from answer_pipeline.checks import (
    answer_text,
    evaluate_record,
    parse_answer,
    summarize,
)
from tests.answer_pipeline_support import (
    CONDITIONS,
    DOCUMENTS,
    GOOD_ANSWER_TEXT,
    LEAVE_DOC,
    answer,
    case,
    good,
    llm_record,
    no_llm_record,
    unsupported_case,
)


def result(record):
    evaluation = evaluate_record(record)
    return {c["code"]: c["ok"] for c in evaluation["checks"]}, evaluation


class RouteHandlingTests(unittest.TestCase):
    def test_good_record_passes_everything(self):
        oks, evaluation = result(good())
        self.assertEqual(evaluation["failed"], [])
        self.assertEqual(evaluation["warnings"], [])
        self.assertIsNone(oks["P5"])  # openai는 길이 점검을 하지 않는다
        self.assertIs(evaluation["auto_usable"], True)

    def test_unsupported_question_without_llm_passes(self):
        oks, evaluation = result(no_llm_record(unsupported_case()))
        self.assertIs(oks["P1"], True)
        self.assertEqual(evaluation["failed"], [])
        self.assertIs(evaluation["auto_usable"], False)  # 사용 가능 비율 대상이 아니다

    def test_answer_route_without_llm_fails_p1(self):
        _, evaluation = result(no_llm_record(case()))
        self.assertEqual(evaluation["failed"], ["P1"])

    def test_unsupported_route_answered_by_llm_fails_p1(self):
        # 현재 실행기는 세 경로 모두 LLM을 부른다 (기준 문서 F-2)
        _, evaluation = result(llm_record(unsupported_case()))
        self.assertIn("P1", evaluation["failed"])

    def test_error_before_model_call_does_not_judge_p1(self):
        # 실행기가 모델을 부르기 전에 실패 (예: Ollama 서버 시작 실패)
        record = no_llm_record(case())
        record["error"] = "RuntimeError"
        oks, evaluation = result(record)
        self.assertIsNone(oks["P1"])
        self.assertEqual(evaluation["failed"], ["A1"])

    def test_no_evidence_question_is_answered_with_shortage_notice(self):
        # 근거 부족이 정답이어도 SEARCH_KNOWLEDGE 경로는 LLM이 부족하다고 답한다
        record = llm_record(
            case(expected_document_ids=(), required_points=("찾지 못",)),
            text=answer("등록된 문서에서 장기근속 포상 기준을 찾지 못했어요."),
        )
        oks, evaluation = result(record)
        self.assertIs(oks["P1"], True)
        self.assertEqual(evaluation["failed"], [])


class PromptCheckTests(unittest.TestCase):
    def test_document_missing_from_prompt_fails_p2(self):
        record = good()
        record["prompt"] = record["prompt"].replace(LEAVE_DOC["text"], "")
        oks, _ = result(record)
        self.assertIs(oks["P2"], False)

    def test_question_missing_from_prompt_fails_p3(self):
        record = good()
        record["question"] = "다른 질문"
        oks, _ = result(record)
        self.assertIs(oks["P3"], False)

    def test_required_point_inside_documents_is_not_a_leak(self):
        oks, _ = result(good())  # "그루"는 회사 문서 안에 있다
        self.assertIs(oks["P4"], True)

    def test_required_point_in_template_is_a_leak(self):
        record = good()
        record["prompt"] = "채점 기준: 그루\n" + record["prompt"]
        oks, _ = result(record)
        self.assertIs(oks["P4"], False)

    def test_long_ollama_prompt_fails_p5(self):
        record = llm_record(provider="ollama")
        record["usage"]["input_tokens"] = (
            CONDITIONS["num_ctx"] - CONDITIONS["max_output_tokens"] + 1
        )
        oks, _ = result(record)
        self.assertIs(oks["P5"], False)

    def test_p5_uses_limits_recorded_with_the_run(self):
        record = llm_record(provider="ollama")
        record["usage"]["input_tokens"] = 10_000
        record["limits"] = {"num_ctx": 16384, "max_output_tokens": 512}
        oks, _ = result(record)
        self.assertIs(oks["P5"], True)


class AnswerCheckTests(unittest.TestCase):
    def test_call_error_skips_answer_checks(self):
        record = llm_record(error="ReadTimeout", text="", generation_complete=False)
        oks, evaluation = result(record)
        self.assertEqual(evaluation["failed"], ["A1"])
        for code in ("A2", "A3", "A4", "A5", "A6"):
            self.assertIsNone(oks[code], code)

    def test_truncated_broken_json_fails_a2_a3_but_still_checks_content(self):
        record = llm_record(
            text='{"text": "온오피스에서',
            generation_complete=False,
            finish_reason="length",
        )
        _, evaluation = result(record)
        self.assertEqual(evaluation["failed"], ["A2", "A3"])
        self.assertIn("A4", evaluation["warnings"])  # 원문으로 핵심 정보를 본다

    def test_text_and_reason_json_fails_a3(self):
        # 현재 실행기 프롬프트가 지시하는 형식 (기준 문서 F-2)
        text = json.dumps(
            {"text": GOOD_ANSWER_TEXT, "reason": "SEARCH_KNOWLEDGE"},
            ensure_ascii=False,
        )
        _, evaluation = result(llm_record(text=text))
        self.assertEqual(evaluation["failed"], ["A3"])
        self.assertIs(evaluation["auto_usable"], False)

    def test_missing_required_point_is_a4_warning_only(self):
        oks, evaluation = result(llm_record(text=answer("인사팀에 문의하세요.")))
        self.assertIs(oks["A4"], False)
        self.assertEqual(evaluation["failed"], [])
        self.assertEqual(evaluation["warnings"], ["A4"])
        self.assertIs(evaluation["auto_flagged"], False)

    def test_number_and_claim_are_warnings_only(self):
        record = llm_record(
            text=answer("그루에서 7일 전까지 신청하세요. 연차를 승인했습니다.")
        )
        _, evaluation = result(record)
        self.assertEqual(evaluation["failed"], [])
        self.assertEqual(evaluation["warnings"], ["A5", "A6"])
        self.assertIs(evaluation["auto_flagged"], False)

    def test_numbers_from_documents_are_not_warned(self):
        oks, _ = result(good())  # "3일"은 회사 문서에 있다
        self.assertIs(oks["A5"], True)

    def test_citation_numbers_are_not_warned(self):
        # [문서 1]의 1은 근거 표기 번호라 근거 없는 숫자로 보지 않는다
        cited = answer("그루에서 사용 3일 전까지 신청하세요 [문서 1]. [문서12]")
        oks, _ = result(llm_record(text=cited))
        self.assertIs(oks["A5"], True)

        # 표기 밖의 숫자는 그대로 잡는다
        record = llm_record(text=answer("그루에서 7일 전까지 신청하세요 [문서 1]."))
        a5 = next(c for c in evaluate_record(record)["checks"] if c["code"] == "A5")
        self.assertIs(a5["ok"], False)
        self.assertEqual(a5["detail"], "근거·질문에 없는 숫자: 7")


class SummaryTests(unittest.TestCase):
    def test_summary_counts_and_measurements(self):
        missing_document = llm_record(
            case("dev-hr-02"), documents={"2": DOCUMENTS["2"]}
        )
        ollama_cold = llm_record(provider="ollama", latency_seconds=9.0)
        ollama_cold["cold_start"] = True
        records = [
            good(),
            missing_document,
            ollama_cold,
            llm_record(provider="ollama", repeat=2, latency_seconds=2.0),
            llm_record(provider="ollama", repeat=3, error="ConnectError", text=""),
            llm_record(unsupported_case("dev-unsupported-01")),
        ]
        evaluations = [evaluate_record(r) for r in records]
        summary = summarize(records, evaluations)

        local = summary["models"]["local"]
        self.assertEqual(local["provider"], "ollama")
        self.assertEqual(local["calls"], 3)
        self.assertEqual(local["failures"]["A1"], 1)
        self.assertEqual(local["auto_usable"], 2)
        self.assertEqual(local["served_models"], ["test-ollama"])
        self.assertEqual(local["measured"]["successful_calls"], 2)
        self.assertEqual(local["measured"]["latency_mean_seconds"], 2.0)
        self.assertEqual(local["measured"]["cold_start_latency_seconds"], 9.0)
        self.assertEqual(local["measured"]["input_tokens_total"], 1000)
        self.assertEqual(summary["models"]["cloud"]["calls"], 3)
        self.assertEqual(summary["no_llm_records"], 0)
        # UNSUPPORTED 질문에 LLM이 답함: P1 실패
        self.assertEqual(summary["wrong_route_cases"], ["dev-unsupported-01"])
        # 정답 근거 문서(1번)가 프롬프트에 빠짐
        self.assertEqual(summary["document_problem_cases"], ["dev-hr-02"])
        json.dumps(summary)  # evaluation_summary.json으로 저장할 수 있어야 한다


class ParseAnswerTests(unittest.TestCase):
    def test_accepts_text_only(self):
        self.assertIsNotNone(parse_answer('{"text": "안내"}'))
        self.assertIsNone(parse_answer('{"text": "  "}'))
        self.assertIsNone(parse_answer('{"text": "안내", "reason": "x"}'))
        self.assertIsNone(parse_answer('{"answer": "안내", "next_steps": []}'))
        self.assertIsNone(parse_answer('```json\n{"text": "안내"}'))
        self.assertIsNone(parse_answer(None))

    def test_answer_text_falls_back_to_raw_response(self):
        self.assertEqual(answer_text({"response_text": '{"text": "안내"}'}), "안내")
        self.assertEqual(answer_text({"response_text": "그냥 문장"}), "그냥 문장")
        self.assertEqual(answer_text({}), "")


if __name__ == "__main__":
    unittest.main()
