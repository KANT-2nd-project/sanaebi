"""단계별 디버깅 기록(app/trace.py)이 응답을 바꾸지 않고 JSONL에 남는지 확인한다.

실제 분류 모델·LLM·네트워크는 쓰지 않는다. 가짜 채팅 모델로 LangChain 체인을 돌려
프롬프트와 모델 응답이 콜백으로 기록되는지 본다.
"""

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda

import sanaebi_assistant
from app import fastapi_main, trace
from app.routers import assistant, questions

LABEL = "SEARCH_KNOWLEDGE"
DOCUMENTS = "연차 문서 " * 400  # 기본 2000자 제한을 넘는 문서 문맥


def fake_generate(response, category, provider=None):
    """실행기 대신 같은 모양의 작은 체인을 실제 LangChain으로 돌린다."""
    chain = (
        RunnableLambda(
            lambda value: {**value, "document_data": DOCUMENTS, "label": category}
        )
        | PromptTemplate.from_template(
            "라벨: {label}\n질문: {text}\n문서: {document_data}"
        )
        | FakeListChatModel(responses=["가상 답변"])
    )
    message = chain.invoke(response)
    return {"ollama": {"answer": message.content}}


def model_rows(record):
    return [s for s in record["steps"] if s["stage"] == trace.MODEL_STAGE]


class ToolAnswerModel(FakeMessagesListChatModel):
    """도구 호출로 AssistantResponse를 돌려주는 가짜 모델(실제 실행기 체인 확인용)."""

    def bind_tools(self, tools, **kwargs):
        return self


def tool_answer(answer="가상 답변"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "AssistantResponse",
                "args": {
                    "answer": answer,
                    "referenced_documents": ["연차 사용 신청"],
                    "note": "",
                },
                "id": "call-1",
            }
        ],
    )


class TraceTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.trace_dir = directory / "trace"
        self.enterContext(
            patch.dict(
                os.environ,
                {"SANAEBI_DOCUMENT_DB": str(directory / "managed.sqlite3")},
            )
        )
        os.environ.pop("TRACE_DIR", None)
        os.environ.pop("TRACE_FULL_PROMPT", None)
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
        )
        self.enterContext(
            patch.object(
                assistant, "generate_assistant_response", side_effect=fake_generate
            )
        )

    def ask(self, question="연차는 어디서 신청해?"):
        body = {
            "response": {"ok": True, "text": question, "reason": ""},
            "classification_label": LABEL,
        }
        return self.client.post("/assistant", json=body)

    def records(self):
        files = sorted(self.trace_dir.glob("*.jsonl"))
        lines = [
            line for file in files for line in file.read_text("utf-8").splitlines()
        ]
        return [json.loads(line) for line in lines]

    def test_no_trace_dir_writes_nothing_and_keeps_response(self):
        response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ollama": {"answer": "가상 답변"}})
        self.assertFalse(self.trace_dir.exists())

    def test_request_steps_prompt_and_response_go_to_one_line(self):
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
            response = self.ask()

        self.assertEqual(response.json(), {"ollama": {"answer": "가상 답변"}})
        [record] = self.records()
        self.assertEqual(record["path"], "/assistant")
        self.assertEqual(record["request"]["response"]["text"], "연차는 어디서 신청해?")
        self.assertEqual(record["status"], 200)
        self.assertEqual(record["response"], {"ollama": {"answer": "가상 답변"}})
        self.assertIsNone(record["error"])

        steps = record["steps"]
        self.assertEqual([s["seq"] for s in steps], list(range(1, len(steps) + 1)))
        self.assertEqual({s["status"] for s in steps}, {"ok"})
        self.assertTrue(all(s["seconds"] is not None for s in steps))

        # 분류 라벨과 질문은 첫 단계(실행기 전체) 입력에 그대로 남는다
        self.assertEqual(steps[0]["stage"], trace.ROOT_STAGE)
        self.assertEqual(steps[0]["input"]["text"], "연차는 어디서 신청해?")

        # 모델 호출은 시작·끝이 한 행: 입력은 프롬프트, 출력은 원문 응답
        [model] = model_rows(record)
        self.assertIn(f"라벨: {LABEL}", model["input"]["head"])
        self.assertGreater(model["prompt_chars"], trace.DEFAULT_MAX_CHARS)
        self.assertEqual(len(model["input"]["head"]), trace.DEFAULT_MAX_CHARS)
        self.assertEqual(model["output"], "가상 답변")

    def test_two_model_calls_share_trace_id_and_split_by_root_run(self):
        def generate_twice(response, category, provider=None):
            # 실행기처럼 한 요청에서 두 모델을 차례로 부른다
            return {
                "ollama": fake_generate(response, category)["ollama"],
                "openai": fake_generate(response, category)["ollama"],
            }

        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
            patch.object(
                assistant, "generate_assistant_response", side_effect=generate_twice
            ),
        ):
            self.ask()

        [record] = self.records()
        steps = record["steps"]
        self.assertEqual({step["trace_id"] for step in steps}, {record["trace_id"]})
        roots = [s["root_run_id"] for s in model_rows(record)]
        self.assertEqual(len(roots), 2)
        self.assertNotEqual(roots[0], roots[1])
        # 각 모델 호출의 단계는 자기 체인 실행(root_run_id)에만 속한다
        for root in roots:
            tops = [
                s
                for s in steps
                if s["root_run_id"] == root and s["parent_run_id"] is None
            ]
            self.assertEqual(len(tops), 1)
            self.assertEqual(tops[0]["run_id"], root)
            self.assertEqual(tops[0]["stage"], trace.ROOT_STAGE)

    def test_response_header_points_to_the_trace_line(self):
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
            response = self.ask()
        [record] = self.records()
        self.assertEqual(response.headers["x-trace-id"], record["trace_id"])
        self.assertNotIn("x-trace-id", self.ask().headers)

    def test_model_error_is_recorded_as_step(self):
        class BrokenModel(FakeListChatModel):
            def _call(self, *args, **kwargs):
                raise ConnectionError("모델 서버 없음")

        def generate_with_broken_model(response, category, provider=None):
            chain = PromptTemplate.from_template("질문: {text}") | BrokenModel(
                responses=["사용 안 함"]
            )
            try:
                chain.invoke(response)
            except ConnectionError as error:
                return {"ollama": {"answer": "", "error": str(error)}}

        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
            patch.object(
                assistant,
                "generate_assistant_response",
                side_effect=generate_with_broken_model,
            ),
        ):
            response = self.ask()
        self.assertEqual(response.status_code, 200)
        [record] = self.records()
        [model] = model_rows(record)
        self.assertEqual(model["status"], "error")
        self.assertEqual(model["error"], "ConnectionError: 모델 서버 없음")
        # 같은 오류를 이어받은 바깥 단계(실행기 전체)도 error로 남는다
        self.assertEqual(record["steps"][0]["status"], "error")

    def test_concurrent_requests_do_not_mix_steps(self):
        barrier = threading.Barrier(2)

        def generate_after_both_started(response, category, provider=None):
            barrier.wait(timeout=5)  # 두 요청이 동시에 실행기 안에 있게 한다
            return fake_generate(response, category)

        questions = ["첫 번째 질문", "두 번째 질문"]
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
            patch.object(
                assistant,
                "generate_assistant_response",
                side_effect=generate_after_both_started,
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            responses = list(pool.map(self.ask, questions))

        self.assertEqual([r.status_code for r in responses], [200, 200])
        records = {r["request"]["response"]["text"]: r for r in self.records()}
        self.assertEqual(sorted(records), sorted(questions))
        for question, record in records.items():
            [model] = model_rows(record)
            self.assertIn(f"질문: {question}", model["input"]["head"])
            self.assertEqual(
                {s["trace_id"] for s in record["steps"]}, {record["trace_id"]}
            )

    def test_full_prompt_option_keeps_whole_prompt(self):
        env = {"TRACE_DIR": str(self.trace_dir), "TRACE_FULL_PROMPT": "1"}
        with patch.dict(os.environ, env):
            self.ask()
        [record] = self.records()
        [model] = model_rows(record)
        self.assertIsInstance(model["input"], str)
        self.assertEqual(len(model["input"]), model["prompt_chars"])

    def test_ask_with_classification_is_recorded(self):
        def generate_for_ask(response, category, provider=None):
            answer = fake_generate(response, category)["ollama"]["answer"]
            return {provider: {"success": True, "output": {"text": answer}}}

        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
            patch.object(questions, "classify_question", return_value=LABEL),
            patch.object(
                questions, "generate_assistant_response", side_effect=generate_for_ask
            ),
        ):
            response = self.client.post("/ask", json={"question": "연차 신청"})
        self.assertEqual(response.json()["text"], "가상 답변")
        [record] = self.records()
        self.assertEqual(record["path"], "/ask")
        self.assertEqual(record["request"], {"question": "연차 신청"})
        [model] = model_rows(record)
        self.assertIn("질문: 연차 신청", model["input"]["head"])

    def test_untraced_path_is_not_recorded(self):
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
            self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.records(), [])

    def test_endpoint_error_is_recorded_and_response_unchanged(self):
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
            patch.object(
                assistant,
                "generate_assistant_response",
                side_effect=RuntimeError("실행기 실패"),
            ),
        ):
            response = self.ask()
        self.assertEqual(response.status_code, 500)
        [record] = self.records()
        self.assertEqual(record["error"], "RuntimeError: 실행기 실패")
        self.assertEqual(record["status"], 500)

    def test_write_failure_does_not_break_request(self):
        blocked = self.trace_dir.parent / "not-a-directory"
        blocked.write_text("파일", encoding="utf-8")
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(blocked)}),
            self.assertLogs(trace.logger, level="WARNING"),
        ):
            response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ollama": {"answer": "가상 답변"}})


class RunnerStageTests(unittest.TestCase):
    """실제 실행기 체인(sanaebi_assistant.create_chain)의 단계가 이름대로 나뉘는지 본다."""

    def run_chain(self, response, model):
        callback = trace.TraceCallback()
        with (
            patch.object(sanaebi_assistant, "create_chat_model", return_value=model),
            patch.object(
                sanaebi_assistant, "load_document_context", return_value="연차 문서"
            ),
        ):
            chain = sanaebi_assistant.create_chain("openai")
            chain.invoke(
                {"response": response, "classification_label": LABEL},
                config={"callbacks": [callback]},
            )
        return callback.stage_rows()

    def test_answer_path_stages_are_named_in_order(self):
        rows = self.run_chain(
            {"ok": True, "text": "연차는 어디서 신청해?"},
            ToolAnswerModel(responses=[tool_answer()]),
        )
        self.assertEqual(
            [row["stage"] for row in rows],
            [
                trace.ROOT_STAGE,
                "입력 정리",
                "경로 선택",
                "문서 문맥 추가",
                "프롬프트 만들기",
                trace.MODEL_STAGE,
                "출력 해석",
                "출력 정리",
            ],
        )
        stages = {row["stage"]: row for row in rows}
        self.assertEqual(
            stages["문서 문맥 추가"]["output"]["document_data"], "연차 문서"
        )
        self.assertEqual(stages["출력 해석"]["output"]["answer"], "가상 답변")
        self.assertEqual(stages["출력 정리"]["output"]["document"], "연차 사용 신청")

    def test_model_error_rows_skip_wrappers(self):
        class BrokenModel(ToolAnswerModel):
            def _generate(self, *args, **kwargs):
                raise ConnectionError("입력 한도 초과")

        callback = trace.TraceCallback()
        with (
            patch.object(
                sanaebi_assistant,
                "create_chat_model",
                return_value=BrokenModel(responses=[tool_answer()]),
            ),
            patch.object(
                sanaebi_assistant, "load_document_context", return_value="연차 문서"
            ),
            self.assertRaises(ConnectionError),
        ):
            sanaebi_assistant.create_chain("openai").invoke(
                {
                    "response": {"ok": True, "text": "연차는 어디서 신청해?"},
                    "classification_label": LABEL,
                },
                config={"callbacks": [callback]},
            )
        rows = callback.stage_rows()
        self.assertEqual(
            [(row["stage"], row["status"]) for row in rows],
            [
                (trace.ROOT_STAGE, "error"),
                ("입력 정리", "ok"),
                ("경로 선택", "error"),
                ("문서 문맥 추가", "ok"),
                ("프롬프트 만들기", "ok"),
                (trace.MODEL_STAGE, "error"),
            ],
        )

    def test_failed_input_path_has_its_own_stage(self):
        rows = self.run_chain(
            {"ok": False, "text": "", "reason": "질문이 비었습니다"},
            ToolAnswerModel(responses=[tool_answer()]),
        )
        self.assertEqual(
            [row["stage"] for row in rows],
            [trace.ROOT_STAGE, "입력 정리", "경로 선택", "입력 오류 응답"],
        )


class ToRecordTests(unittest.TestCase):
    def test_long_text_keeps_head_length_and_hash(self):
        clipped = trace.clip_text("가" * 10, limit=3)
        self.assertEqual(clipped["head"], "가가가")
        self.assertEqual(clipped["chars"], 10)
        self.assertEqual(len(clipped["sha256"]), 64)

    def test_unknown_objects_become_text(self):
        self.assertEqual(trace.to_record({"a": (1, None)}), {"a": [1, None]})
        self.assertIsInstance(trace.to_record(object()), str)


if __name__ == "__main__":
    unittest.main()
