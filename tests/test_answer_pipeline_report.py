"""역순 디버깅, 추정 비용, 사람 채점 집계, 선정 규칙, 보고서 작성을 본다.

역순 디버깅은 한 단계만 망가뜨린 기록에서 그 단계를 원인으로 찾는지 본다 (고장 주입).
"""

import json
import tempfile
import unittest
from pathlib import Path

from answer_pipeline.checks import evaluate_record, summarize
from answer_pipeline.report import (
    debug_records,
    estimate_costs,
    load_prices,
    render_report,
    select_model,
)
from answer_pipeline.run import record_key
from answer_pipeline.scoring import summarize_human_scores, usable_summary
from tests.answer_pipeline_support import (
    DOCUMENTS,
    LEAVE_DOC,
    answer,
    case,
    good,
    human,
    llm_record,
    no_llm_record,
    unsupported_case,
)


def trace(records, scores=None):
    evaluations = [evaluate_record(r) for r in records]
    traces = debug_records(records, evaluations, scores)
    return {record_key(t): t for t in traces}


def origin_of(record, scores=None):
    result = trace([record], scores)[record_key(record)]
    return result["origin"], result["flagged"]


def content_failure(provider="ollama", repeat=1):
    # 입력·경로·문서·프롬프트·형식은 정상인데 핵심 정보(그루)가 빠진 응답 (A4 경고)
    return llm_record(
        provider=provider, repeat=repeat, text=answer("인사팀에 문의하세요.")
    )


def zero_scores(*records):
    # 사람 채점 0점: ⑦내용 단계의 문제 (사용 불가)
    return {record_key(r): human(points=0) for r in records}


class OriginStageTests(unittest.TestCase):
    def test_good_record_has_no_origin(self):
        self.assertEqual(origin_of(good()), (None, False))

    def test_bad_grading_data_traces_to_input(self):
        # 정답 근거 문서가 프롬프트에 있는데 그 문서에 없는 핵심 표현을 요구함
        # A4는 경고라 이상한 답변은 아니고 숨은 문제로 남는다
        record = llm_record(case(required_points=("인사 포털",)))
        self.assertEqual(origin_of(record), ("input", False))

    def test_unsupported_question_answered_by_llm_traces_to_prompt(self):
        # 정답 경로를 그대로 넘겼는데 실행기가 LLM으로 답함 → ④ (P1)
        self.assertEqual(origin_of(llm_record(unsupported_case())), ("prompt", True))

    def test_missing_document_traces_to_documents(self):
        # 정답 근거 문서가 프롬프트에 빠짐 → 핵심 정보 누락 (A4 경고)
        record = llm_record(
            documents={"2": DOCUMENTS["2"]}, text=answer("온오피스에서 확인하세요.")
        )
        self.assertEqual(origin_of(record), ("documents", False))
        self.assertEqual(origin_of(record, zero_scores(record)), ("documents", True))

    def test_document_dropped_from_prompt_traces_to_prompt(self):
        # evidence에는 있는데 실제 프롬프트에서 빠짐 → P2 실패
        record = good()
        record["prompt"] = record["prompt"].replace(LEAVE_DOC["text"], "")
        self.assertEqual(origin_of(record), ("prompt", True))

    def test_answer_route_without_llm_traces_to_prompt(self):
        self.assertEqual(origin_of(no_llm_record(case())), ("prompt", True))

    def test_call_error_traces_to_call(self):
        record = llm_record(error="ConnectError", text="", generation_complete=False)
        self.assertEqual(origin_of(record), ("call", True))

    def test_truncation_traces_to_format(self):
        record = llm_record(text='{"text": "그루에서 신청', generation_complete=False)
        self.assertEqual(origin_of(record), ("format", True))

    def test_missing_required_point_alone_is_not_flagged(self):
        # A4는 경고라 원인 판정에 넣지 않는다
        self.assertEqual(origin_of(content_failure()), (None, False))

    def test_missing_required_point_with_zero_score_traces_to_content(self):
        record = content_failure()
        self.assertEqual(origin_of(record, zero_scores(record)), ("content", True))

    def test_critical_defect_flags_answer(self):
        record = good()
        scores = {record_key(record): human(2, 2, 2, 2, 2, 2, "C2")}
        result = trace([record], scores)[record_key(record)]
        self.assertEqual((result["origin"], result["flagged"]), ("content", True))
        self.assertIn("치명:C2", result["symptoms"])

    def test_grounded_one_is_unusable_without_zero_scores(self):
        record = good()
        self.assertEqual(
            origin_of(record, {record_key(record): human(grounded=1)}),
            ("content", True),
        )

    def test_usable_answer_is_not_flagged(self):
        record = good()
        scores = {record_key(record): human(citation=None, clarity=1)}
        self.assertEqual(origin_of(record, scores), (None, False))

    def test_warnings_alone_do_not_flag(self):
        record = llm_record(text=answer("그루에서 7일 전까지 신청하세요."))
        self.assertEqual(origin_of(record), (None, False))


class TracePathTests(unittest.TestCase):
    def test_path_lists_stages_from_content_back_to_input(self):
        record = content_failure()
        result = trace([record], zero_scores(record))
        path = next(iter(result.values()))["path"]
        self.assertEqual(
            [step["stage"] for step in path],
            ["content", "format", "call", "prompt", "documents", "input"],
        )

    def test_sibling_comparison_separates_model_and_prompt(self):
        local1 = content_failure("ollama", 1)
        local2 = content_failure("ollama", 2)
        cloud1 = good()

        # 이 모델만 두 번 다 실패, 다른 모델은 정상 → 모델 한계
        traces = trace([local1, local2, cloud1], zero_scores(local1, local2))
        self.assertTrue(
            traces[record_key(local1)]["interpretation"].startswith("모델 한계")
        )

        # 모든 모델 실패 → 프롬프트·근거 의심
        cloud1 = content_failure("openai", 1)
        traces = trace([local1, local2, cloud1], zero_scores(local1, local2, cloud1))
        self.assertTrue(
            traces[record_key(local1)]["interpretation"].startswith("프롬프트")
        )

        # 같은 모델의 다른 반복은 정상 → 우연한 변동
        local2 = llm_record(provider="ollama", repeat=2)
        traces = trace([local1, local2], zero_scores(local1))
        self.assertTrue(
            traces[record_key(local1)]["interpretation"].startswith("우연한 변동")
        )


PRICES = {
    "cloud": {
        "model": "test-openai",
        "input_per_1m_tokens": 2.0,
        "output_per_1m_tokens": 8.0,
        "currency": "USD",
        "checked_on": "2026-10-13",
        "source": "https://example.com/pricing",
    }
}


def run_records():
    return [
        llm_record(provider="ollama"),
        llm_record(provider="openai"),
        llm_record(provider="openai", repeat=2),
        llm_record(unsupported_case("out-1"), provider="openai"),
    ]


class PriceFileTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / "prices.json"

    def write(self, prices):
        self.path.write_text(json.dumps(prices, ensure_ascii=False), encoding="utf-8")

    def test_loads_complete_price(self):
        self.write(PRICES)
        self.assertEqual(load_prices(self.path), PRICES)

    def test_rejects_placeholder_values(self):
        for field, value in (
            ("input_per_1m_tokens", "확인 필요"),
            ("checked_on", "YYYY-MM-DD"),
            ("source", " "),
        ):
            with self.subTest(field=field):
                self.write({"cloud": {**PRICES["cloud"], field: value}})
                with self.assertRaises(ValueError):
                    load_prices(self.path)

    def test_example_price_file_must_be_filled_before_use(self):
        example = (
            Path(__file__).resolve().parents[1]
            / "answer_pipeline"
            / "examples"
            / "prices.example.json"
        )
        with self.assertRaises(ValueError):
            load_prices(example)


class CostAndHumanSummaryTests(unittest.TestCase):
    def test_estimated_cost_uses_measured_tokens(self):
        records = run_records()
        summary = summarize(records, [evaluate_record(r) for r in records])
        costs = estimate_costs(summary, records, PRICES)
        self.assertIsNone(costs["local"])  # 단가 없음
        # cloud 3회 × (입력 500, 출력 40) → 1500 × 2/1M + 120 × 8/1M
        self.assertAlmostEqual(costs["cloud"]["total"], 0.00396)
        self.assertAlmostEqual(costs["cloud"]["per_call"], 0.00132)
        self.assertTrue(costs["cloud"]["model_matches"])

    def test_human_scores_are_averaged_per_model(self):
        scores = {
            ("q1", "cloud", 1): human(clarity=2, grounded=0),
            ("q1", "cloud", 2): human(2, None, 2, 2, 2, 1, "C2"),
            ("q1", "local", 1): human(clarity=0),
        }
        summary = summarize_human_scores(scores)
        self.assertEqual(summary["cloud"]["scored"], 2)
        self.assertEqual(summary["cloud"]["means"]["clarity"], 1.5)
        self.assertEqual(summary["cloud"]["means"]["citation"], 2.0)  # NA 제외
        self.assertEqual(summary["cloud"]["zeros"]["grounded"], 1)
        self.assertEqual(summary["cloud"]["critical"]["C2"], 1)
        self.assertEqual(summary["cloud"]["critical_responses"], 1)
        self.assertEqual(summary["local"]["zeros"]["clarity"], 1)


def verdict(provider, ratio, release=True):
    return {"provider": provider, "usable_ratio": ratio, "release": release}


class SelectionRuleTests(unittest.TestCase):
    def test_local_wins_within_gap(self):
        choice, _ = select_model(
            {"local": verdict("ollama", 0.80), "cloud": verdict("openai", 0.90)}
        )
        self.assertEqual(choice, "local")

    def test_better_model_wins_beyond_gap(self):
        choice, _ = select_model(
            {"local": verdict("ollama", 0.70), "cloud": verdict("openai", 0.90)}
        )
        self.assertEqual(choice, "cloud")

    def test_only_passing_model_wins(self):
        choice, _ = select_model(
            {
                "local": verdict("ollama", 0.95, release=False),
                "cloud": verdict("openai", 0.60),
            }
        )
        self.assertEqual(choice, "cloud")

    def test_none_passing_picks_highest_ratio_with_note(self):
        choice, lines = select_model(
            {
                "local": verdict("ollama", 0.50, release=False),
                "cloud": verdict("openai", 0.60, release=False),
            }
        )
        self.assertEqual(choice, "cloud")
        self.assertIn("부족", lines[-1])

    def test_pending_scores_are_not_judged(self):
        choice, _ = select_model(
            {
                "local": verdict("ollama", None, release=None),
                "cloud": verdict("openai", 0.9),
            }
        )
        self.assertIsNone(choice)


class RenderReportTests(unittest.TestCase):
    def build(self, scores, prices=None):
        records = run_records()
        evaluations = [evaluate_record(r) for r in records]
        summary = summarize(records, evaluations)
        if prices:
            summary["costs"] = estimate_costs(summary, records, prices)
        traces = debug_records(records, evaluations, scores)
        usable = usable_summary(records, evaluations, scores)
        meta = {
            "created": "2026-10-14T12:00:00+09:00",
            "models": [
                {"name": "local", "provider": "ollama", "num_ctx": 4096},
                {"name": "cloud", "provider": "openai", "timeout_seconds": 600.0},
            ],
        }
        return records, render_report(
            "test-run", records, summary, traces, scores, usable, meta
        )

    def test_report_has_comparison_selection_and_trace_sections(self):
        records = run_records()
        scores = {
            record_key(records[0]): human(),
            record_key(records[1]): human(relevance=0),
            record_key(records[2]): human(),
        }
        _, report = self.build(scores, PRICES)
        for heading in (
            "## 1. 실행 정보",
            "## 2. 요약 비교표",
            "## 3. 선정 규칙 적용 (C-3)",
            "## 4. 질문 형식별 사용 가능 비율",
            "### 선정 결정 (직접 작성)",
            "## 13. 사례별 역추적",
        ):
            self.assertIn(heading, report)
        self.assertIn("1/2 (50.0%)", report)  # cloud 사용 가능 답변
        self.assertIn("1/1 (100.0%)", report)  # local
        self.assertIn("사람 채점 relevance = 0", report)
        self.assertIn("0.001320 USD/회 (추정)", report)
        self.assertIn("| num_ctx | 4096 | - |", report)

    def test_report_without_prices_or_human_scores(self):
        _, report = self.build({})
        self.assertIn("단가 파일(`--prices`)을 주지 않아", report)
        self.assertIn("채점 대기", report)
        self.assertIn("사람 채점이 끝나지 않아 판정하지 않았다", report)


if __name__ == "__main__":
    unittest.main()
