"""추정 비용과 보고서 작성(지침 준수, 추가 비교, 사람 확인, 어긴 답변, 실행 점검)을 본다."""

import json
import tempfile
import unittest
from pathlib import Path

from archive.answering_v1.answer_pipeline.checks import (
    JUDGE_GUIDELINES,
    evaluate_record,
    summarize,
)
from archive.answering_v1.answer_pipeline.report import (
    estimate_costs,
    load_prices,
    render_report,
)
from archive.answering_v1.answer_pipeline.run import record_key
from archive.answering_v1.answer_pipeline.scoring import agreement, verdicts_by_key
from tests.support.answer_pipeline import (
    GOOD_ANSWER_TEXT,
    LEAVE_DOC,
    llm_record,
    structured,
    unsupported_case,
)
from tests.support.paths import ROOT

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


def compliant(provider="openai", repeat=1, **overrides):
    values = {
        "text": "",
        "structured_response": structured(GOOD_ANSWER_TEXT, [LEAVE_DOC["title"]]),
    }
    values.update(overrides)
    return llm_record(provider=provider, repeat=repeat, **values)


def run_records():
    return [
        compliant(provider="ollama"),
        compliant(provider="openai"),
        compliant(provider="openai", repeat=2),
        llm_record(unsupported_case("out-1"), provider="openai"),
    ]


def judged(records, failed=None):
    failed = failed or {}
    rows = {}
    for record in records:
        key = record_key(record)
        rows[key] = {
            "case_id": record["case_id"],
            "model_name": record["model_name"],
            "repeat": record["repeat"],
            "judge_model": "judge-test",
            "verdicts": {
                g: {"ok": g not in failed.get(key, ()), "reason": f"{g} 이유"}
                for g in JUDGE_GUIDELINES
            },
        }
    return rows


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
            ROOT
            / "archive"
            / "answering_v1"
            / "answer_pipeline"
            / "examples"
            / "prices.example.json"
        )
        with self.assertRaises(ValueError):
            load_prices(example)


class CostTests(unittest.TestCase):
    def test_estimated_cost_uses_measured_tokens_of_answer_calls(self):
        records = run_records()
        summary = summarize(records, [evaluate_record(r) for r in records])
        costs = estimate_costs(summary, records, PRICES)
        self.assertIsNone(costs["local"])  # 단가 없음
        # cloud 문서 답변 2회 × (입력 500, 출력 40) → 1000 × 2/1M + 80 × 8/1M
        self.assertAlmostEqual(costs["cloud"]["total"], 0.00264)
        self.assertAlmostEqual(costs["cloud"]["per_call"], 0.00132)
        self.assertTrue(costs["cloud"]["model_matches"])


class RenderReportTests(unittest.TestCase):
    def render(self, records, judgments, human=None, prices=None):
        human = human or {}
        evaluations = [evaluate_record(r) for r in records]
        summary = summarize(records, evaluations)
        if prices:
            summary["costs"] = estimate_costs(summary, records, prices)
        verdicts = verdicts_by_key(evaluations, judgments, human)
        meta = {"created": "2026-10-14T18:00:00+09:00", "cases": 2, "repeats": 2}
        return render_report(
            "run-01",
            records,
            summary,
            verdicts,
            judgments,
            agreement(judgments, human),
            meta,
            100,
        )

    def test_report_sections_and_values(self):
        records = run_records()
        answer_records = records[:3]
        failed = {record_key(records[2]): ("no_false_completion",)}
        human = {record_key(records[2]): {"no_false_completion": False}}
        report = self.render(records, judged(answer_records, failed), human, PRICES)

        for heading in (
            "## 1. 지침 준수 (모델별 지킨 비율)",
            "## 2. 추가 비교",
            "## 3. 사람 확인 (심판 판정과 같은 비율)",
            "## 4. 지침을 어긴 답변",
            "## 5. 실행 점검",
            "## 6. 실행 정보",
        ):
            self.assertIn(heading, report)
        self.assertIn(
            "| 신청·변경·조회를 처리한 것처럼 말하지 않는다 | 심판 LLM | 1/2 (50.0%) | 1/1 (100.0%) |",
            report,
        )
        self.assertIn("| 출력 형식을 JSON으로 준다 | 코드 | 2/2 (100.0%) |", report)
        self.assertIn("| 반복 일관성 | 갈림 1/1문항 | - |", report)
        self.assertIn("0.001320 USD", report)
        self.assertIn("| 합계 | 1 | 1 | 1/1 (100.0%) |", report)
        self.assertIn("| dev-hr-01 | cloud | 2 | 신청·변경·조회를", report)
        self.assertIn("| 사람 |", report)
        self.assertIn("P1 호출 경로", report)
        self.assertIn("out-1", report)  # UNSUPPORTED 질문에 LLM이 답해 P1 실패

    def test_report_before_judge_and_human_check(self):
        report = self.render(run_records(), {})
        self.assertIn("판정 전 2", report)
        self.assertIn("(사람 확인 전이다.", report)
        self.assertIn("단가 파일(`--prices`)을 주면", report)
        self.assertIn("심판 판정 전", report)


if __name__ == "__main__":
    unittest.main()
