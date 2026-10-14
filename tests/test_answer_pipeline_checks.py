"""코드가 판정하는 지침 4개, 호출 결과, 실행 점검 P1~P5, 모델별 집계가 기준대로 나오는지 본다."""

import json
import unittest

from answer_pipeline.checks import (
    answer_text,
    call_status,
    evaluate_record,
    longest_copy,
    parse_answer,
    summarize,
)
from tests.answer_pipeline_support import (
    CONDITIONS,
    DOCUMENTS,
    GOOD_ANSWER_TEXT,
    LEAVE_DOC,
    ROOM_DOC,
    answer,
    case,
    good,
    llm_record,
    no_llm_record,
    structured,
    unsupported_case,
)


def compliant(**overrides):
    """정답 문서 제목을 밝힌 구조화 응답 기록 (코드 지침 4개 모두 통과)."""
    values = {
        "text": "",
        "structured_response": structured(GOOD_ANSWER_TEXT, [LEAVE_DOC["title"]]),
    }
    values.update(overrides)
    return llm_record(**values)


def guideline(record, key, copy_limit=100):
    return evaluate_record(record, copy_limit)["guidelines"][key]


def run_checks(record):
    evaluation = evaluate_record(record)
    return {c["code"]: c["ok"] for c in evaluation["run_checks"]}, evaluation


class CodeGuidelineTests(unittest.TestCase):
    def test_compliant_answer_passes_all_code_guidelines(self):
        evaluation = evaluate_record(compliant())
        self.assertEqual(evaluation["status"], "answered")
        self.assertEqual(
            {k: v["ok"] for k, v in evaluation["guidelines"].items()},
            {
                "json_format": True,
                "document_titles": True,
                "korean_only": True,
                "no_long_copy": True,
            },
        )

    def test_json_format(self):
        self.assertIs(
            guideline(good(), "json_format")["ok"], True
        )  # 과거 {"text"} 기록
        broken = llm_record(text='{"text": "온오피스에서', finish_reason="length")
        self.assertIs(guideline(broken, "json_format")["ok"], False)
        extra = json.dumps({"text": "안내", "reason": "x"}, ensure_ascii=False)
        self.assertIs(guideline(llm_record(text=extra), "json_format")["ok"], False)
        invalid = compliant(structured_response={"answer": "불완전"})
        self.assertIs(guideline(invalid, "json_format")["ok"], False)

    def test_empty_answer_fails_json_and_skips_other_guidelines(self):
        record = compliant(structured_response=structured(""))
        evaluation = evaluate_record(record)
        self.assertEqual(evaluation["status"], "empty")
        self.assertIs(evaluation["guidelines"]["json_format"]["ok"], False)
        for key in ("document_titles", "korean_only", "no_long_copy"):
            self.assertIsNone(evaluation["guidelines"][key]["ok"], key)

    def test_document_titles(self):
        # 본문에 정답 문서 제목을 쓴 과거 기록도 제목을 밝힌 것으로 본다
        in_text = llm_record(text=answer(f"{GOOD_ANSWER_TEXT} ({LEAVE_DOC['title']})"))
        self.assertIs(guideline(in_text, "document_titles")["ok"], True)

        none = guideline(good(), "document_titles")
        self.assertEqual((none["ok"], none["detail"]), (False, "밝힌 문서 제목 없음"))

        wrong = compliant(
            structured_response=structured(GOOD_ANSWER_TEXT, [ROOM_DOC["title"]])
        )
        self.assertIn(
            "정답 문서 제목이 없음", guideline(wrong, "document_titles")["detail"]
        )

        made_up = compliant(
            structured_response=structured(
                GOOD_ANSWER_TEXT, [LEAVE_DOC["title"], "휴가 규정"]
            )
        )
        result = guideline(made_up, "document_titles")
        self.assertEqual(
            (result["ok"], result["detail"]),
            (False, "회사 문서에 없는 제목: 휴가 규정"),
        )

    def test_document_titles_not_judged_without_expected_documents(self):
        for expected in (None, ()):
            record = llm_record(
                case(expected_document_ids=expected, required_points=())
            )
            self.assertIsNone(guideline(record, "document_titles")["ok"], expected)

    def test_korean_only(self):
        self.assertIs(guideline(compliant(), "korean_only")["ok"], True)
        chinese = compliant(
            structured_response=structured(
                "그루에서 신청하세요. 请提前三天申请。", [LEAVE_DOC["title"]]
            )
        )
        result = guideline(chinese, "korean_only")
        self.assertIs(result["ok"], False)
        self.assertIn("请提前三天申请", result["detail"])
        english = compliant(
            structured_response=structured(
                "Please submit your leave request in Groo. 그루에서 신청하세요.",
                [LEAVE_DOC["title"]],
            )
        )
        self.assertIs(guideline(english, "korean_only")["ok"], False)

    def test_short_english_terms_and_urls_are_korean_answers(self):
        record = compliant(
            structured_response=structured(
                "VPN과 Google Workspace 관리 콘솔에서 확인하세요. "
                "https://support.google.com/a/users/answer/12345 참고",
                [LEAVE_DOC["title"]],
            )
        )
        self.assertIs(guideline(record, "korean_only")["ok"], True)

    def test_long_copy_uses_limit(self):
        copied = compliant(
            structured_response=structured(LEAVE_DOC["text"], [LEAVE_DOC["title"]])
        )
        length = len(LEAVE_DOC["text"])
        self.assertIs(
            guideline(copied, "no_long_copy", copy_limit=length + 1)["ok"], True
        )
        result = guideline(copied, "no_long_copy", copy_limit=30)
        self.assertIs(result["ok"], False)
        self.assertIn(f"{length}자 그대로 겹침", result["detail"])
        self.assertEqual(evaluate_record(copied)["copy_overlap"], length)

    def test_longest_copy_ignores_spacing_and_document_boundaries(self):
        length, part = longest_copy("가나 다라마", ["가나\n다라", "마바"])
        self.assertEqual((length, part), (5, "가나 다라"))

    def test_other_routes_and_failed_calls_are_not_judged(self):
        for record in (
            llm_record(unsupported_case()),
            llm_record(error="ReadTimeout", text="", generation_complete=False),
        ):
            self.assertEqual(evaluate_record(record)["guidelines"], {})


class CallStatusTests(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(call_status(good()), "answered")
        self.assertEqual(
            call_status(llm_record(error="ReadTimeout", text="")), "timeout"
        )
        self.assertEqual(
            call_status(llm_record(error="APITimeoutError", text="")), "timeout"
        )
        self.assertEqual(
            call_status(llm_record(error="ConnectError", text="")), "error"
        )
        self.assertEqual(
            call_status(compliant(structured_response=structured(" "))), "empty"
        )
        ollama_json = json.dumps(structured(""), ensure_ascii=False)
        self.assertEqual(call_status(llm_record(text=ollama_json)), "empty")


class RunCheckTests(unittest.TestCase):
    def test_good_record_passes_run_checks(self):
        oks, evaluation = run_checks(good())
        self.assertEqual(evaluation["run_failed"], [])
        self.assertIsNone(oks["P5"])  # openai는 길이 점검을 하지 않는다

    def test_unsupported_question_without_llm_passes(self):
        oks, evaluation = run_checks(no_llm_record(unsupported_case()))
        self.assertIs(oks["P1"], True)
        self.assertEqual(evaluation["run_failed"], [])

    def test_answer_route_without_llm_fails_p1(self):
        _, evaluation = run_checks(no_llm_record(case()))
        self.assertEqual(evaluation["run_failed"], ["P1"])

    def test_unsupported_route_answered_by_llm_fails_p1(self):
        _, evaluation = run_checks(llm_record(unsupported_case()))
        self.assertIn("P1", evaluation["run_failed"])

    def test_error_before_model_call_does_not_judge_p1(self):
        # 실행기가 모델을 부르기 전에 실패 (예: Ollama 서버 시작 실패)
        record = no_llm_record(case())
        record["error"] = "RuntimeError"
        oks, evaluation = run_checks(record)
        self.assertIsNone(oks["P1"])
        self.assertEqual(evaluation["status"], "error")

    def test_document_missing_from_prompt_fails_p2(self):
        record = good()
        record["prompt"] = record["prompt"].replace(LEAVE_DOC["text"], "")
        oks, _ = run_checks(record)
        self.assertIs(oks["P2"], False)

    def test_question_missing_from_prompt_fails_p3(self):
        record = good()
        record["question"] = "다른 질문"
        oks, _ = run_checks(record)
        self.assertIs(oks["P3"], False)

    def test_required_point_inside_documents_is_not_a_leak(self):
        oks, _ = run_checks(good())  # "그루"는 회사 문서 안에 있다
        self.assertIs(oks["P4"], True)

    def test_required_point_in_template_is_a_leak(self):
        record = good()
        record["prompt"] = "채점 기준: 그루\n" + record["prompt"]
        oks, _ = run_checks(record)
        self.assertIs(oks["P4"], False)

    def test_long_ollama_prompt_fails_p5(self):
        record = llm_record(provider="ollama")
        record["usage"]["input_tokens"] = (
            CONDITIONS["num_ctx"] - CONDITIONS["max_output_tokens"] + 1
        )
        oks, _ = run_checks(record)
        self.assertIs(oks["P5"], False)

    def test_p5_uses_limits_recorded_with_the_run(self):
        record = llm_record(provider="ollama")
        record["usage"]["input_tokens"] = 10_000
        record["limits"] = {"num_ctx": 16384, "max_output_tokens": 512}
        oks, _ = run_checks(record)
        self.assertIs(oks["P5"], True)


class SummaryTests(unittest.TestCase):
    def test_summary_counts_answer_route_calls_and_measurements(self):
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
            llm_record(provider="ollama", repeat=4, error="ReadTimeout", text=""),
            llm_record(
                provider="ollama",
                repeat=5,
                text=json.dumps(structured(""), ensure_ascii=False),
                finish_reason="length",
            ),
            llm_record(unsupported_case("dev-unsupported-01")),
        ]
        evaluations = [evaluate_record(r) for r in records]
        summary = summarize(records, evaluations)

        local = summary["models"]["local"]
        self.assertEqual(local["provider"], "ollama")
        self.assertEqual(local["calls"], 5)
        self.assertEqual(local["failures"], {"error": 1, "timeout": 1, "empty": 1})
        self.assertAlmostEqual(local["failure_rate"], 3 / 5)
        self.assertEqual(local["truncated"], 1)
        self.assertEqual(local["answer_length_mean"], len(GOOD_ANSWER_TEXT))
        self.assertEqual(local["served_models"], ["test-ollama"])
        self.assertEqual(local["measured"]["latency_mean_seconds"], 1.5)
        self.assertEqual(local["measured"]["latency_max_seconds"], 2.0)
        self.assertEqual(local["measured"]["cold_start_latency_seconds"], 9.0)
        # UNSUPPORTED 기록은 2장 집계에서 뺀다
        self.assertEqual(summary["models"]["cloud"]["calls"], 2)
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
