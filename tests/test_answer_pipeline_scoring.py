"""사람 확인표, 지침별 최종 판정, 사람·심판 일치율, 반복 일관성이 기준대로 나오는지 본다."""

import csv
import tempfile
import unittest
from pathlib import Path

from archive.answering_v1.answer_pipeline.checks import (
    JUDGE_GUIDELINES,
    evaluate_record,
)
from archive.answering_v1.answer_pipeline.run import record_key
from archive.answering_v1.answer_pipeline.scoring import (
    CHECK_KEY,
    CHECK_SHEET,
    agreement,
    final_verdicts,
    guideline_summary,
    load_human_checks,
    verdicts_by_key,
    write_check_sheet,
)
from tests.answer_pipeline_support import (
    GOOD_ANSWER_TEXT,
    LEAVE_DOC,
    case,
    llm_record,
    structured,
)


def compliant(provider="openai", repeat=1, test_case=None):
    return llm_record(
        test_case,
        provider=provider,
        repeat=repeat,
        text="",
        structured_response=structured(GOOD_ANSWER_TEXT, [LEAVE_DOC["title"]]),
    )


def judgment(record, *failed):
    verdicts = {
        key: {"ok": key not in failed, "reason": f"{key} 이유"}
        for key in JUDGE_GUIDELINES
    }
    return {
        "case_id": record["case_id"],
        "model_name": record["model_name"],
        "repeat": record["repeat"],
        "judge_model": "judge-test",
        "verdicts": verdicts,
    }


def judgments_for(records, failed=None):
    failed = failed or {}
    return {record_key(r): judgment(r, *failed.get(record_key(r), ())) for r in records}


class CheckSheetTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.dir = Path(temp_dir.name)

    def read(self, name):
        with (self.dir / name).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def write(self, rows):
        with (self.dir / CHECK_SHEET).open("w", encoding="utf-8-sig", newline="") as s:
            writer = csv.DictWriter(s, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_sheet_has_all_failures_and_some_passes_without_model_names(self):
        records = [compliant(repeat=i) for i in range(1, 11)]
        failing = records[0]
        judgments = judgments_for(
            records, {record_key(failing): ("company_data_only",)}
        )
        rows = write_check_sheet(records, judgments, self.dir, sample_rate=0.2)
        # 실패 1건 전부 + 통과 9건의 20%(올림 2건)
        self.assertEqual(rows, 3)
        sheet = self.read(CHECK_SHEET)
        self.assertNotIn("model_name", sheet[0])
        self.assertNotIn("cloud", " ".join(" ".join(r.values()) for r in sheet))
        self.assertEqual(sheet[0]["human_company_data_only"], "")
        keys = {r["check_id"]: r for r in self.read(CHECK_KEY)}
        failed_rows = [r for r in sheet if r["judge_company_data_only"] == "실패"]
        self.assertEqual(len(failed_rows), 1)
        self.assertEqual(keys[failed_rows[0]["check_id"]]["repeat"], "1")

        with self.assertRaises(FileExistsError):
            write_check_sheet(records, judgments, self.dir)

    def test_human_checks_round_trip_and_reject_unknown_values(self):
        records = [compliant()]
        write_check_sheet(records, judgments_for(records), self.dir, sample_rate=1)
        sheet = self.read(CHECK_SHEET)
        sheet[0]["human_tone_template"] = "실패"
        self.write(sheet)
        self.assertEqual(
            load_human_checks(self.dir),
            {record_key(records[0]): {"tone_template": False}},
        )

        sheet[0]["human_tone_template"] = "보류"
        self.write(sheet)
        with self.assertRaises(ValueError):
            load_human_checks(self.dir)

    def test_no_sheet_means_no_human_checks(self):
        self.assertEqual(load_human_checks(self.dir), {})


class VerdictTests(unittest.TestCase):
    def test_code_judge_and_human_sources(self):
        record = compliant()
        evaluation = evaluate_record(record)
        pending = final_verdicts(evaluation)
        self.assertEqual(pending["json_format"]["by"], "code")
        self.assertEqual(pending["tone_template"]["by"], "pending")

        verdicts = final_verdicts(
            evaluation,
            judgment(record, "tone_template"),
            {"company_data_only": False},
        )
        self.assertEqual(
            (verdicts["tone_template"]["ok"], verdicts["tone_template"]["by"]),
            (False, "judge"),
        )
        # 사람 판정이 있으면 사람 판정을 쓴다
        self.assertEqual(
            (verdicts["company_data_only"]["ok"], verdicts["company_data_only"]["by"]),
            (False, "human"),
        )

    def test_empty_answer_is_not_judged(self):
        record = llm_record(text="", structured_response=structured(""))
        verdicts = final_verdicts(evaluate_record(record))
        self.assertIs(verdicts["json_format"]["ok"], False)
        self.assertEqual(verdicts["answers_question"]["by"], "n/a")

    def test_summary_counts_and_repeat_consistency(self):
        records = [
            compliant(repeat=1),
            compliant(repeat=2),
            compliant(test_case=case("dev-hr-02"), repeat=1),
            compliant(test_case=case("dev-hr-02"), repeat=2),
            compliant(provider="ollama"),
        ]
        judgments = judgments_for(
            records[:4], {record_key(records[1]): ("answers_question",)}
        )
        evaluations = [evaluate_record(r) for r in records]
        summary = guideline_summary(verdicts_by_key(evaluations, judgments, {}))

        cloud = summary["cloud"]
        self.assertEqual(cloud["targets"], 4)
        self.assertEqual(
            cloud["guidelines"]["answers_question"],
            {"passed": 3, "judged": 4, "pending": 0},
        )
        self.assertEqual(
            cloud["guidelines"]["json_format"], {"passed": 4, "judged": 4, "pending": 0}
        )
        # dev-hr-01만 반복 사이에 '지침을 모두 지켰는가'가 갈렸다
        self.assertEqual((cloud["repeat_split_cases"], cloud["repeat_cases"]), (1, 2))
        local = summary["local"]["guidelines"]["tone_template"]
        self.assertEqual(local, {"passed": 0, "judged": 0, "pending": 1})

    def test_agreement_counts_checked_judgments(self):
        records = [compliant(repeat=1), compliant(repeat=2)]
        judgments = judgments_for(records, {record_key(records[0]): ("tone_template",)})
        human = {
            record_key(records[0]): {"tone_template": True},
            record_key(records[1]): {"tone_template": True, "answers_question": True},
        }
        result = agreement(judgments, human)
        self.assertEqual(result["tone_template"], {"checked": 2, "same": 1})
        self.assertEqual(result["answers_question"], {"checked": 1, "same": 1})
        self.assertEqual(result["company_data_only"], {"checked": 0, "same": 0})


if __name__ == "__main__":
    unittest.main()
