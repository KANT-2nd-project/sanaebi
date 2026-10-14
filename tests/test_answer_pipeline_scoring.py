"""모델 이름을 가린 채점표, 채점 읽기, 사용 가능 답변 판정(B-4)을 본다."""

import csv
import tempfile
import unittest
from pathlib import Path

from answer_pipeline.checks import evaluate_record
from answer_pipeline.run import record_key
from answer_pipeline.scoring import (
    KEY_NAME,
    SHEET_NAME,
    is_usable,
    load_human_scores,
    usable_by_tag,
    usable_summary,
    write_blind_sheet,
)
from tests.answer_pipeline_support import (
    GOOD_ANSWER_TEXT,
    case,
    human,
    llm_record,
    unsupported_case,
)


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_rows(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class BlindSheetTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.run_dir = Path(temp_dir.name)

    def test_sheet_hides_model_and_scores_round_trip(self):
        records = [
            llm_record(provider="ollama"),
            llm_record(provider="openai"),
            llm_record(provider="openai", repeat=2, error="ReadTimeout", text=""),
            llm_record(unsupported_case("out-1")),
        ]
        # 호출 오류(A1 실패)와 SEARCH_KNOWLEDGE가 아닌 경로는 뺀다
        self.assertEqual(write_blind_sheet(records, self.run_dir), 2)

        sheet_path = self.run_dir / SHEET_NAME
        rows = read_rows(sheet_path)
        for hidden in ("model_name", "model", "provider", "error"):
            self.assertNotIn(hidden, rows[0])
        self.assertEqual(rows[0]["text"], GOOD_ANSWER_TEXT)  # JSON에서 text만 보여 준다
        self.assertEqual(rows[0]["question_type"], "answerable")
        self.assertEqual(
            rows[0]["evidence"], "[문서 1] [예시] 연차 신청"
        )  # 정답 문서만
        self.assertEqual(
            sorted(
                (r["model_name"], r["repeat"])
                for r in read_rows(self.run_dir / KEY_NAME)
            ),
            [("cloud", "1"), ("local", "1")],
        )
        self.assertEqual(load_human_scores(self.run_dir), {})  # 아직 빈 채점표

        rows[0].update(
            grounded="2",
            citation="NA",
            relevance="2",
            handling="1",
            required_points="2",
            clarity="0",
            critical_defects="c1, C3",
        )
        write_rows(sheet_path, rows)
        key = next(
            r
            for r in read_rows(self.run_dir / KEY_NAME)
            if r["sheet_id"] == rows[0]["sheet_id"]
        )
        scores = load_human_scores(self.run_dir)
        self.assertEqual(
            scores,
            {
                (key["case_id"], key["model_name"], 1): human(
                    2, None, 2, 1, 2, 0, "C1", "C3"
                )
            },
        )

    def test_partial_or_invalid_rows_are_rejected(self):
        write_blind_sheet([llm_record()], self.run_dir)
        sheet_path = self.run_dir / SHEET_NAME
        rows = read_rows(sheet_path)
        for values in (
            {"grounded": "2"},  # 나머지 항목이 비었다
            {
                "grounded": "NA",  # grounded는 해당 없음이 될 수 없다
                "citation": "2",
                "relevance": "2",
                "handling": "2",
                "required_points": "2",
                "clarity": "2",
            },
        ):
            with self.subTest(values=values):
                write_rows(sheet_path, [{**rows[0], **values}])
                with self.assertRaises(ValueError):
                    load_human_scores(self.run_dir)

    def test_does_not_overwrite_existing_sheet(self):
        write_blind_sheet([llm_record()], self.run_dir)
        with self.assertRaises(FileExistsError):
            write_blind_sheet([llm_record()], self.run_dir)


class UsableTests(unittest.TestCase):
    def test_usable_rule(self):
        evaluation = evaluate_record(llm_record())
        self.assertIsNone(is_usable(evaluation, None))  # 채점 전
        self.assertTrue(is_usable(evaluation, human()))
        self.assertTrue(is_usable(evaluation, human(citation=None, clarity=1)))
        self.assertFalse(is_usable(evaluation, human(grounded=1)))
        self.assertFalse(is_usable(evaluation, human(relevance=0)))
        self.assertFalse(is_usable(evaluation, human(2, 2, 2, 2, 2, 2, "C1")))
        # A3 실패면 채점과 관계없이 사용 불가
        broken = evaluate_record(llm_record(text="그루에서 신청하세요."))
        self.assertFalse(is_usable(broken, None))
        self.assertFalse(is_usable(broken, human()))

    def test_usable_ratio_and_repeat_consistency(self):
        records = [
            llm_record(provider="ollama", repeat=1),
            llm_record(provider="ollama", repeat=2),
            llm_record(case("q2", question_type="partial"), provider="ollama"),
            llm_record(provider="openai", repeat=1),
            llm_record(provider="openai", repeat=2),
            llm_record(unsupported_case(), provider="openai"),  # 비율에 넣지 않는다
        ]
        evaluations = [evaluate_record(r) for r in records]
        scores = {
            record_key(records[0]): human(),
            record_key(records[1]): human(grounded=1),
            record_key(records[2]): human(),
            record_key(records[3]): human(),
        }
        usable = usable_summary(records, evaluations, scores)

        local = usable["local"]
        self.assertEqual((local["calls"], local["usable"], local["pending"]), (3, 2, 0))
        self.assertAlmostEqual(local["usable_ratio"], 2 / 3)
        self.assertEqual((local["repeat_cases"], local["repeat_split_cases"]), (1, 1))
        self.assertEqual(local["auto_failures"], 0)

        cloud = usable["cloud"]
        self.assertEqual((cloud["calls"], cloud["pending"]), (2, 1))
        self.assertIsNone(cloud["usable_ratio"])  # 채점이 끝나지 않았다

        by_type = usable_by_tag(records, usable, "question_type")
        self.assertEqual(by_type["local"], {"answerable": [1, 2], "partial": [1, 1]})
        self.assertEqual(by_type["cloud"], {"answerable": [1, 1]})


if __name__ == "__main__":
    unittest.main()
