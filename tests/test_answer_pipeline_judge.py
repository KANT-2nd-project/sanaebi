"""심판 LLM 프롬프트, 응답 검사, 판정 쌓기가 기준대로 되는지 본다. 심판은 가짜 함수로 바꾼다."""

import tempfile
import threading
import unittest
from pathlib import Path

from answer_pipeline.checks import JUDGE_GUIDELINES
from answer_pipeline.judge import (
    JudgeResult,
    build_prompt,
    judge_record,
    judge_targets,
    load_judgments,
    model_instructions,
    run_judge,
)
from answer_pipeline.run import record_key
from tests.answer_pipeline_support import (
    GOOD_ANSWER_TEXT,
    LEAVE_DOC,
    ROOM_DOC,
    case,
    llm_record,
    structured,
    unsupported_case,
)


def passing(reason="문서대로 답함"):
    return {key: {"passed": True, "reason": reason} for key in JUDGE_GUIDELINES}


class FakeJudge:
    """받은 프롬프트를 남기고 정해 둔 응답을 차례로 돌려준다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []
        self.lock = threading.Lock()

    def __call__(self, prompt):
        with self.lock:
            self.prompts.append(prompt)
            response = self.responses.pop(0) if self.responses else passing()
        if isinstance(response, Exception):
            raise response
        return response


class PromptTests(unittest.TestCase):
    def test_result_fields_match_judge_guidelines(self):
        self.assertEqual(tuple(JudgeResult.model_fields), JUDGE_GUIDELINES)

    def test_prompt_hides_model_and_excerpts_documents(self):
        record = llm_record(
            provider="ollama",
            structured_response=structured(GOOD_ANSWER_TEXT, [LEAVE_DOC["title"]]),
        )
        prompt = build_prompt(record)
        self.assertNotIn("local", prompt)
        self.assertNotIn("ollama", prompt)
        self.assertIn(GOOD_ANSWER_TEXT, prompt)
        self.assertIn(LEAVE_DOC["text"], prompt)  # 정답 근거 문서
        self.assertNotIn(ROOM_DOC["text"], prompt)  # 관련 없는 문서는 넣지 않는다
        self.assertIn("그루", prompt)  # 평가 세트의 핵심 정보
        for key in JUDGE_GUIDELINES:
            self.assertIn(key, prompt)

    def test_documents_named_by_answer_are_included(self):
        record = llm_record(
            case(expected_document_ids=()),
            structured_response=structured(
                "회의실 문서만 있어요.", [ROOM_DOC["title"]]
            ),
        )
        prompt = build_prompt(record)
        self.assertIn(ROOM_DOC["text"], prompt)
        self.assertIn("회사 문서에 답이 없는 질문", prompt)

    def test_instructions_stop_before_document_data(self):
        record = {"prompt": "역할\n지침\n<문서 데이터: 제목>\n제목: A\n본문"}
        self.assertEqual(model_instructions(record), "역할\n지침")
        # 표시가 없으면 문서 본문만 지운다
        record = {
            "prompt": f"지침\n{LEAVE_DOC['text']}",
            "evidence": [LEAVE_DOC],
        }
        self.assertEqual(model_instructions(record), "지침")


class JudgeRecordTests(unittest.TestCase):
    def test_returns_verdict_per_guideline(self):
        response = passing()
        response["no_false_completion"] = {"passed": False, "reason": "신청했다고 말함"}
        verdicts = judge_record(llm_record(), FakeJudge(response))
        self.assertEqual(list(verdicts), list(JUDGE_GUIDELINES))
        self.assertEqual(
            verdicts["no_false_completion"], {"ok": False, "reason": "신청했다고 말함"}
        )

    def test_retries_once_then_fails_without_message(self):
        judge = FakeJudge({"company_data_only": "통과"}, passing())
        self.assertTrue(judge_record(llm_record(), judge)["company_data_only"]["ok"])
        self.assertEqual(len(judge.prompts), 2)

        judge = FakeJudge(ValueError("sk-secret"), ValueError("sk-secret"))
        with self.assertRaises(RuntimeError) as raised:
            judge_record(llm_record(), judge)
        self.assertNotIn("sk-secret", str(raised.exception))


class RunJudgeTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.dir = Path(temp_dir.name)

    def test_targets_answered_search_records_only(self):
        records = [
            llm_record(),
            llm_record(unsupported_case()),
            llm_record(repeat=2, error="ReadTimeout", text=""),
            llm_record(repeat=3, text="", structured_response=structured("")),
        ]
        self.assertEqual(judge_targets(records), records[:1])

    def test_appends_and_skips_judged_records(self):
        records = [llm_record(), llm_record(repeat=2), llm_record(provider="ollama")]
        judge = FakeJudge(passing(), RuntimeError("x"), RuntimeError("x"))
        logs = []
        result = run_judge(
            records, self.dir, judge, "judge-test", log=logs.append, workers=1
        )
        self.assertEqual(result, {"targets": 3, "judged": 2, "failed": 1})
        self.assertEqual(len(logs), 1)

        judge = FakeJudge()
        result = run_judge(records, self.dir, judge, "judge-test", workers=1)
        self.assertEqual(result, {"targets": 3, "judged": 1, "failed": 0})
        self.assertEqual(len(judge.prompts), 1)
        judgments = load_judgments(self.dir)
        self.assertEqual(set(judgments), {record_key(r) for r in records})
        row = judgments[record_key(records[0])]
        self.assertEqual(row["judge_model"], "judge-test")


if __name__ == "__main__":
    unittest.main()
