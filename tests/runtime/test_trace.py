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
)
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda

from app import fastapi_main
from app.dependencies import get_assistant_handler
from app.diagnostics import trace
from app.documents.context import DocumentContextSnapshot
from app.questions.service import handle_classified_question

LABEL = "SEARCH_KNOWLEDGE"
DOCUMENTS = "연차 문서 " * 400  # 기본 2000자 제한을 넘는 문서 문맥


def fake_generate(response, category, provider=None, document_provider=None):
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
    # 실행기처럼 분류 라벨을 체인 입력에 함께 넣는다
    message = chain.invoke({**response, "classification_label": category})
    return {"ollama": {"answer": message.content}}


def fake_answer(question, snapshot=None, *, classification_context=None):
    return fake_generate({"text": question}, LABEL)["ollama"]["answer"]


def model_rows(record):
    return [s for s in record["steps"] if s["stage"] == trace.MODEL_STAGE]


class TraceTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.trace_dir = directory / "trace"
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "SANAEBI_DOCUMENT_DB": str(directory / "managed.sqlite3"),
                    "SANAEBI_RETRIEVAL_MODE": "full",
                },
            )
        )
        os.environ.pop("TRACE_DIR", None)
        os.environ.pop("TRACE_FULL_PROMPT", None)
        self.answer_impl = fake_answer
        self._original_overrides = fastapi_main.app.dependency_overrides.copy()
        fastapi_main.app.dependency_overrides[get_assistant_handler] = lambda: (
            self._handle_assistant
        )
        self.addCleanup(self._restore_dependency_overrides)
        self.client = self.enterContext(
            TestClient(fastapi_main.app, raise_server_exceptions=False)
        )

    def _restore_dependency_overrides(self):
        fastapi_main.app.dependency_overrides.clear()
        fastapi_main.app.dependency_overrides.update(self._original_overrides)

    def _handle_assistant(self, question, label):
        return handle_classified_question(
            question,
            label,
            read_documents=lambda: DocumentContextSnapshot((object(),)),
            answer=self.answer_impl,
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

    def test_active_stage_resolver_does_not_assume_legacy_chain_names(self):
        self.assertEqual(
            trace.stage_of("prepare_input", (), trace.ROOT_STAGE),
            ("prepare_input", False),
        )
        self.assertEqual(
            trace.stage_of("RunnableBranch", (), trace.ROOT_STAGE),
            ("RunnableBranch", True),
        )
        self.assertEqual(
            trace.stage_of("RunnableLambda", ("condition:legacy",), "RunnableBranch"),
            ("RunnableLambda", False),
        )

    def test_no_trace_dir_writes_nothing_and_keeps_response(self):
        response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "가상 답변", "reason": ""}
        )
        self.assertFalse(self.trace_dir.exists())

    def test_request_steps_prompt_and_response_go_to_one_line(self):
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
            response = self.ask()

        self.assertEqual(
            response.json(), {"ok": True, "text": "가상 답변", "reason": ""}
        )
        [record] = self.records()
        self.assertEqual(record["path"], "/assistant")
        self.assertEqual(record["request"]["response"]["text"], "연차는 어디서 신청해?")
        self.assertEqual(record["status"], 200)
        self.assertEqual(
            record["response"], {"ok": True, "text": "가상 답변", "reason": ""}
        )
        self.assertIsNone(record["error"])

        steps = record["steps"]
        self.assertEqual([s["seq"] for s in steps], list(range(1, len(steps) + 1)))
        self.assertEqual({s["status"] for s in steps}, {"ok"})
        self.assertTrue(all(s["seconds"] is not None for s in steps))

        # 분류 라벨과 질문은 첫 단계(실행기 전체) 입력에 그대로 남는다
        # 맨 앞은 분류 행: /assistant는 요청에 들어온 라벨을 쓴다
        self.assertEqual(steps[0]["stage"], "분류")
        self.assertEqual(steps[0]["output"], LABEL)
        self.assertEqual(steps[0]["source"], "요청 값")
        self.assertEqual(steps[0]["input"], "연차는 어디서 신청해?")
        self.assertEqual(steps[1]["stage"], trace.ROOT_STAGE)
        self.assertEqual(steps[1]["input"]["text"], "연차는 어디서 신청해?")

        # 모델 호출은 시작·끝이 한 행: 입력은 프롬프트, 출력은 원문 응답
        [model] = model_rows(record)
        self.assertIn(f"라벨: {LABEL}", model["input"]["head"])
        self.assertGreater(model["prompt_chars"], trace.DEFAULT_MAX_CHARS)
        self.assertEqual(len(model["input"]["head"]), trace.DEFAULT_MAX_CHARS)
        self.assertEqual(model["output"], "가상 답변")

    def test_active_trace_keeps_generic_runnable_names(self):
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
            self.ask()

        [record] = self.records()
        stages = [step["stage"] for step in record["steps"]]
        self.assertEqual(stages[1], trace.ROOT_STAGE)
        self.assertIn("RunnableLambda", stages)
        self.assertIn("프롬프트 만들기", stages)
        self.assertNotIn("문서 문맥 추가", stages)
        self.assertNotIn("입력 정리", stages)
        self.assertNotIn("경로 선택", stages)

    def test_two_model_calls_share_trace_id_and_split_by_root_run(self):
        def generate_twice(question, snapshot=None):
            # 실행기처럼 한 요청에서 두 모델을 차례로 부른다
            fake_generate({"text": question}, LABEL)
            fake_generate({"text": question}, LABEL)
            return "가상 답변"

        self.answer_impl = generate_twice
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
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
                if s.get("root_run_id") == root and s.get("parent_run_id") is None
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

        def generate_with_broken_model(question, snapshot=None):
            chain = PromptTemplate.from_template("질문: {text}") | BrokenModel(
                responses=["사용 안 함"]
            )
            return chain.invoke({"text": question}).content

        self.answer_impl = generate_with_broken_model
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
            response = self.ask()
        self.assertEqual(response.status_code, 500)
        [record] = self.records()
        [model] = model_rows(record)
        self.assertEqual(model["status"], "error")
        self.assertEqual(model["error"], "ConnectionError: 모델 서버 없음")
        # 같은 오류를 이어받은 바깥 단계(실행기 전체)도 error로 남는다
        self.assertEqual(record["steps"][1]["status"], "error")

    def test_concurrent_requests_do_not_mix_steps(self):
        barrier = threading.Barrier(2)

        def generate_after_both_started(question, snapshot=None):
            barrier.wait(timeout=5)  # 두 요청이 동시에 실행기 안에 있게 한다
            return fake_answer(question, snapshot)

        questions = ["첫 번째 질문", "두 번째 질문"]
        self.answer_impl = generate_after_both_started
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
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
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
            patch.object(
                fastapi_main.app.state.classifier, "predict", return_value=LABEL
            ),
            patch.object(
                fastapi_main.app.state.document_provider,
                "snapshot",
                return_value=DocumentContextSnapshot((object(),)),
            ),
            patch.object(
                fastapi_main.app.state.answerer, "answer", side_effect=fake_answer
            ),
        ):
            response = self.client.post("/ask", json={"question": "연차 신청"})
        self.assertEqual(response.json()["text"], "가상 답변")
        [record] = self.records()
        self.assertEqual(record["path"], "/ask")
        self.assertEqual(record["request"], {"question": "연차 신청"})
        [model] = model_rows(record)
        self.assertIn("질문: 연차 신청", model["input"]["head"])
        self.assertEqual(record["steps"][0]["source"], "분류기")
        self.assertEqual(record["steps"][0]["output"], LABEL)
        self.assertEqual(record["steps"][0]["routing_mode"], "advisory")

    def test_untraced_path_is_not_recorded(self):
        with patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}):
            self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.records(), [])

    def test_endpoint_error_is_recorded_and_response_unchanged(self):
        def fail_answer(question, snapshot=None):
            raise RuntimeError("실행기 실패")

        self.answer_impl = fail_answer
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
        ):
            response = self.ask()
        self.assertEqual(response.status_code, 500)
        [record] = self.records()
        self.assertEqual(record["error"], "RuntimeError: 실행기 실패")
        self.assertEqual(record["status"], 500)
        [classification] = record["steps"]
        self.assertEqual(classification["stage"], "분류")
        self.assertEqual(classification["status"], "ok")

    def test_write_failure_does_not_break_request(self):
        blocked = self.trace_dir.parent / "not-a-directory"
        blocked.write_text("파일", encoding="utf-8")
        self.answer_impl = fake_answer
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(blocked)}),
            self.assertLogs(trace.logger, level="WARNING"),
        ):
            response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "text": "가상 답변", "reason": ""}
        )

    def test_generation_metadata_is_safe_and_distinct_from_model_stop(self):
        callback = trace.TraceCallback()
        callback.record_classification(LABEL)
        callback._start(
            "model-run",
            None,
            name="ChatOpenAI",
            model_call=True,
            provider="openai",
            model_name="gpt-6-luna",
        )
        callback._finish(
            "model-run",
            "ok",
            finish_reason="stop",
            input_tokens=120,
            output_tokens=16,
        )
        callback.record_generation(
            {
                "model": "gpt-6-luna",
                "profile": "examples_answer_scope_v1",
                "snapshot_fingerprint": "snapshot-hash",
                "prompt_sha256": "prompt-hash",
                "status": "parse_error",
                "seconds": 1.25,
                "input_tokens": 120,
                "output_tokens": 16,
                "error_type": "JSONDecodeError",
                "question": "PRIVATE QUESTION",
                "documents": "PRIVATE DOCUMENT",
                "answer": "PRIVATE ANSWER",
                "api_key": "sk-private",
                "exception": "private exception body",
            }
        )

        rows = callback.record_rows("/ask", {"question": "trace request"}, 502)
        [model] = model_rows({"steps": rows})
        generation = next(row for row in rows if row["stage"] == trace.GENERATION_STAGE)
        self.assertEqual(model["status"], "ok")
        self.assertEqual(model["finish_reason"], "stop")
        self.assertEqual(generation["status"], "parse_error")
        self.assertEqual(generation["profile"], "examples_answer_scope_v1")
        self.assertEqual(generation["snapshot_fingerprint"], "snapshot-hash")
        self.assertEqual(generation["input_tokens"], 120)
        self.assertNotIn("finish_reason", generation)
        self.assertIsNone(generation["output"])
        self.assertIsNone(generation["error"])
        serialized = json.dumps(rows, ensure_ascii=False)
        for private_value in (
            "PRIVATE QUESTION",
            "PRIVATE DOCUMENT",
            "PRIVATE ANSWER",
            "sk-private",
            "private exception body",
        ):
            self.assertNotIn(private_value, serialized)

    def test_generation_metadata_context_is_request_local(self):
        barrier = threading.Barrier(2)

        def answer_with_metadata(question, snapshot=None):
            trace.record_generation(
                {
                    "model": "gpt-6-luna",
                    "profile": "examples_answer_scope_v1",
                    "snapshot_fingerprint": question,
                    "status": "completed",
                    "seconds": 0.01,
                    "input_tokens": 2,
                    "output_tokens": 3,
                }
            )
            barrier.wait(timeout=5)
            return question

        self.answer_impl = answer_with_metadata
        questions = ["첫 번째 질문", "두 번째 질문"]
        with (
            patch.dict(os.environ, {"TRACE_DIR": str(self.trace_dir)}),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            responses = list(pool.map(self.ask, questions))

        self.assertEqual([response.status_code for response in responses], [200, 200])
        records = {
            record["request"]["response"]["text"]: record for record in self.records()
        }
        for question in questions:
            generation = next(
                row
                for row in records[question]["steps"]
                if row["stage"] == trace.GENERATION_STAGE
            )
            self.assertEqual(generation["snapshot_fingerprint"], question)
            self.assertEqual(generation["status"], "completed")


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
