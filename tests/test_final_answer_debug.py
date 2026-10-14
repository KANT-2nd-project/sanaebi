"""LangChain 실행기를 /ask에 끼웠을 때 이상한 최종 응답의 원인 단계를 찾는다.

실행기(sanaebi_assistant.py)는 /ask에 연결되어 있다. 여기서는 연결 함수를
"실행기 체인 + 가짜 모델"로 바꿔 흐름을 재현하고, 단계마다 고장을 넣어 어느
단계에서 멈추는지 확인한다. 모델·네트워크·실제 문서 파일은 쓰지 않는다.

단계: ①입력 → ②문서 문맥 → ③프롬프트 → ④모델 호출 → ⑤출력 정리 → ⑥/ask 응답
원인 = 처음 실패한 단계. 그 뒤의 실패는 원인이 전파된 증상이다.

RUN_LIVE_LLM=1이면 로컬 Ollama로 실제 응답의 단계별 결과를 출력하는 테스트도 실행한다.
"""

import json
import os
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda

import sanaebi_assistant as assistant
from app.answering import adapter as answerer
from app.answering.output import LLM_RESPONSE_ERROR
from app.documents.context import DocumentContextSnapshot
from app.fastapi_main import app

SEARCH = assistant.SEARCH_KNOWLEDGE
CLARIFY = assistant.CLARIFY
UNSUPPORTED = assistant.UNSUPPORTED

STAGES = ("input", "documents", "prompt", "model", "output", "ask")
STAGE_LABELS = {
    "input": "①입력",
    "documents": "②문서 문맥",
    "prompt": "③프롬프트",
    "model": "④모델 호출",
    "output": "⑤출력 정리",
    "ask": "⑥/ask 응답",
}
PASS, FAIL, SKIP, NOT_REACHED = "통과", "실패", "해당 없음", "실행 안 됨"

FAILURE_BODY = {"ok": False, "text": "", "reason": LLM_RESPONSE_ERROR}
ANSWER = "인사 시스템에서 신청하세요."
QUESTION = "연차는 어디서 신청해요?"
TEST_DOCUMENTS = (
    {"title": "[테스트] 연차 신청", "document": "연차는 인사 시스템에서 신청한다."},
    {"title": "[테스트] 회의실 예약", "document": "회의실은 예약 화면에서 잡는다."},
)

LIVE_QUESTIONS = {
    SEARCH: "연차는 어떻게 신청하나요?",
    CLARIFY: "그거 어떻게 해요?",
    UNSUPPORTED: "내 연차 며칠 남았어?",
}

# 단계 도우미가 감싸기 전의 실행기 함수
ORIGINAL_PREPARE_INPUT = assistant.prepare_input
ORIGINAL_LOAD_DOCUMENTS = assistant.load_document_context
ORIGINAL_ENSURE_OLLAMA = assistant.ensure_ollama_server
ORIGINAL_CREATE_MODEL = assistant.create_chat_model


def model_returns(output):
    return lambda prompt: output


def model_raises(error):
    def call(prompt):
        raise error

    return call


def describe(error):
    return f"{type(error).__name__}: {error}"


def check_prompt(prompt, question, label, context):
    """③ 질문, 라벨별 지침, (SEARCH_KNOWLEDGE면) 문서 전체가 프롬프트에 있는지."""
    problems = []
    if assistant.normalize_text(question) not in prompt:
        problems.append("질문 원문 없음")
    if assistant.CLASSIFICATION_INSTRUCTIONS[label] not in prompt:
        problems.append("라벨별 지침 없음")
    if label == SEARCH and (not context or context not in prompt):
        problems.append("문서 문맥 없음")
    return (FAIL, ", ".join(problems)) if problems else (PASS, "")


def check_output(raw, result):
    """⑤ 모델 출력이 {"text": 답변} JSON이고, 체인 결과 text가 그 안쪽 답변인지."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return (
            FAIL,
            "모델 출력이 JSON이 아님 (형식 지시 위반 또는 출력 한도로 잘림)",
            None,
        )
    text = (
        payload.get("answer", payload.get("text"))
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(text, str) or not text.strip():
        return FAIL, "모델 출력 JSON에 답변 text가 없음", None
    answer = assistant.normalize_text(text)
    if result.get("answer", result.get("text")) != answer:
        return FAIL, "체인 결과 text가 안쪽 답변이 아니라 모델 출력 원문임", answer
    return PASS, "", answer


@dataclass
class Trace:
    steps: dict = field(
        default_factory=lambda: dict.fromkeys(STAGES, (NOT_REACHED, ""))
    )
    prompt: str | None = None
    raw_output: str | None = None
    answer: str | None = None
    model_calls: int = 0
    response: object = None

    def mark(self, stage, status, detail=""):
        self.steps[stage] = (status, detail)

    @property
    def origin(self):
        return next((s for s in STAGES if self.steps[s][0] == FAIL), None)

    def report(self):
        lines = [
            f"{STAGE_LABELS[s]:<8} {self.steps[s][0]:<6} {self.steps[s][1]}".rstrip()
            for s in STAGES
        ]
        origin = STAGE_LABELS[self.origin] if self.origin else "없음"
        return "\n".join([*lines, f"원인 단계: {origin}"])


def trace_final_answer(
    question,
    model=None,
    label=SEARCH,
    documents_file=None,
    server_error=None,
    live=False,
):
    """질문 하나를 /ask로 보내고 ①~⑥ 단계별 결과를 기록한다.

    model: 프롬프트 문자열을 받아 모델 출력 문자열을 돌려주는(또는 예외를 내는) 가짜 모델.
    live=True면 가짜 모델 대신 실행기의 실제 Ollama 모델과 실제 문서 파일을 쓴다.
    """
    trace = Trace()
    context = {}

    def prepare_input(value):
        try:
            result = ORIGINAL_PREPARE_INPUT(value)
        except (TypeError, ValueError) as error:
            trace.mark("input", FAIL, describe(error))
            raise
        trace.mark("input", PASS)
        if label != SEARCH:
            trace.mark("documents", SKIP, "문서를 쓰지 않는 라벨")
        return result

    def load_document_context():
        try:
            if documents_file is None:
                text = ORIGINAL_LOAD_DOCUMENTS()
            else:
                text = ORIGINAL_LOAD_DOCUMENTS(documents_file)
        except (OSError, TypeError, ValueError) as error:
            trace.mark("documents", FAIL, describe(error))
            raise
        context["text"] = text
        trace.mark("documents", PASS, f"문서 {text.count('제목: ')}건")
        return text

    def ensure_ollama_server():
        try:
            if server_error is not None:
                raise server_error
            if live:
                ORIGINAL_ENSURE_OLLAMA()
        except Exception as error:
            trace.mark("model", FAIL, describe(error))
            raise

    def create_chat_model(provider):
        real_model = ORIGINAL_CREATE_MODEL(provider) if live else None

        def call(prompt_value):
            prompt = prompt_value.to_string()
            trace.prompt = prompt
            trace.mark(
                "prompt", *check_prompt(prompt, question, label, context.get("text"))
            )
            trace.model_calls += 1
            try:
                message = real_model.invoke(prompt_value) if live else model(prompt)
            except Exception as error:
                trace.mark("model", FAIL, describe(error))
                raise
            trace.mark("model", PASS)
            trace.raw_output = getattr(message, "content", message)
            return message

        class TracedModel:
            def with_structured_output(self, schema):
                return RunnableLambda(call) | RunnableLambda(
                    lambda value: schema.model_validate_json(
                        getattr(value, "content", value)
                    )
                )

        return TracedModel()

    def generate_answer(text):
        try:
            result = assistant.create_chain("ollama").invoke(
                {
                    "response": {"ok": True, "text": text, "reason": ""},
                    "classification_label": label,
                }
            )
        except Exception as error:
            # 모델은 응답했는데 체인이 그 출력을 풀다 멈췄으면 ⑤출력 정리가 원인이다
            if trace.raw_output is not None and trace.steps["output"][0] == NOT_REACHED:
                trace.mark("output", FAIL, describe(error))
            raise
        status, detail, trace.answer = check_output(trace.raw_output, result)
        trace.mark("output", status, detail)
        # 연결 시나리오의 테스트 어댑터만 공개 text 계약으로 변환한다.
        return {"text": result["answer"]}

    def generate_response(response, category, *, provider, document_snapshot=None):
        try:
            output = generate_answer(response["text"])
        except (ValueError, TypeError, OSError, RuntimeError) as error:
            return {provider: {"success": False, "output": None, "error": str(error)}}
        return {provider: {"success": True, "output": output}}

    with (
        patch.object(assistant, "prepare_input", prepare_input),
        patch.object(assistant, "load_document_context", load_document_context),
        patch.object(assistant, "ensure_ollama_server", ensure_ollama_server),
        patch.object(assistant, "create_chat_model", create_chat_model),
        patch.object(answerer, "execute", generate_response),
        TestClient(app, raise_server_exceptions=False) as client,
    ):

        def classify(text):
            if label not in (SEARCH, CLARIFY, UNSUPPORTED):
                trace.mark("input", FAIL, "허용되지 않은 라벨")
            return label

        with (
            patch.object(app.state.classifier, "predict", side_effect=classify),
            patch.object(
                app.state.document_provider,
                "snapshot",
                return_value=DocumentContextSnapshot((object(),)),
            ),
        ):
            trace.response = client.post("/ask", json={"question": question})
        if label in (CLARIFY, UNSUPPORTED) and trace.response.status_code == 200:
            trace.mark("input", PASS)
            trace.mark("documents", SKIP, "문서를 쓰지 않는 라벨")
            trace.answer = trace.response.json()["text"]
    mark_ask(trace)
    return trace


def mark_ask(trace):
    """⑥ 앞 단계가 정상이면 200과 답변 문장, 실패했으면 502 안내 문구여야 한다."""
    response = trace.response
    if response.status_code == 422:
        trace.mark("input", FAIL, "/ask 요청 형식 오류")
        trace.mark("ask", PASS, "422 안내")
        return
    earlier_failed = any(trace.steps[s][0] == FAIL for s in STAGES[:-1])
    if earlier_failed:
        if response.status_code == 502 and response.json() == FAILURE_BODY:
            trace.mark("ask", PASS, "502 안내")
        else:
            trace.mark("ask", FAIL, f"앞 단계가 실패했는데 {response.status_code} 응답")
        return
    body = response.json() if response.status_code == 200 else None
    if body and body.get("text") == trace.answer:
        trace.mark("ask", PASS, "200 답변 문장")
    else:
        trace.mark("ask", FAIL, f"정상 결과인데 {response.status_code} 응답")


class DocumentsMixin:
    def write_documents(self, lines):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(directory) / "documents.jsonl"
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        return path

    def setUp(self):
        self.documents = self.write_documents(
            json.dumps(doc, ensure_ascii=False) for doc in TEST_DOCUMENTS
        )

    def trace(self, question=QUESTION, output=None, **options):
        options.setdefault("documents_file", self.documents)
        if output is not None:
            options["model"] = model_returns(output)
        return trace_final_answer(question, **options)


def answer_json(text=ANSWER):
    return json.dumps(
        {"answer": text, "referenced_documents": [], "note": "테스트 근거"},
        ensure_ascii=False,
    )


class StageOriginTests(DocumentsMixin, unittest.TestCase):
    """단계마다 고장을 하나 넣으면 그 단계를 원인으로 찾는다 (현재 main에서 통과)."""

    def test_blank_question_stops_at_input(self):
        trace = self.trace("   ", answer_json())
        self.assertEqual(trace.origin, "input")
        self.assertEqual(trace.response.status_code, 422)
        self.assertEqual(trace.model_calls, 0)

    def test_invalid_label_or_too_long_question_stops_at_input(self):
        cases = {
            "라벨 오류": {"label": "OTHER"},
            "4000자 초과": {"question": "가" * (assistant.MAX_INPUT_CHARS + 1)},
        }
        for name, options in cases.items():
            with self.subTest(name):
                trace = self.trace(output=answer_json(), **options)
                self.assertEqual(trace.origin, "input")
                self.assertEqual(trace.model_calls, 0)

    def test_document_file_problems_stop_at_documents(self):
        cases = {
            "파일 없음": self.documents.with_name("missing.jsonl"),
            "title 없는 줄": self.write_documents(['{"document": "본문"}']),
            "빈 파일": self.write_documents([]),
        }
        for name, path in cases.items():
            with self.subTest(name):
                trace = self.trace(output=answer_json(), documents_file=path)
                self.assertEqual(trace.origin, "documents")
                self.assertEqual(trace.model_calls, 0)

    def test_prompt_has_question_instruction_and_documents(self):
        trace = self.trace(output=answer_json())
        self.assertEqual(trace.steps["documents"], (PASS, "문서 2건"))
        self.assertEqual(trace.steps["prompt"], (PASS, ""))
        for doc in TEST_DOCUMENTS:
            self.assertIn(doc["document"], trace.prompt)

    def test_non_search_labels_skip_documents(self):
        # /ask 서비스는 비검색 라벨에서 고정 안내로 종료한다.
        for label in (CLARIFY, UNSUPPORTED):
            with self.subTest(label):
                trace = self.trace(output=answer_json(), label=label)
                self.assertEqual(trace.steps["documents"][0], SKIP)
                self.assertEqual(trace.steps["prompt"][0], NOT_REACHED)
                self.assertEqual(trace.model_calls, 0)
                self.assertEqual(trace.response.status_code, 200)

    def test_model_or_server_error_stops_at_model(self):
        cases = {
            "모델 호출 오류": {"model": model_raises(ConnectionError("연결 거부"))},
            "Ollama 서버 없음": {
                "model": model_returns(answer_json()),
                "server_error": RuntimeError("Ollama 서버에 연결할 수 없습니다"),
            },
        }
        for name, options in cases.items():
            with self.subTest(name):
                trace = self.trace(**options)
                self.assertEqual(trace.origin, "model")

    def test_unusable_model_output_stops_at_output(self):
        outputs = {
            "평문": ANSWER,
            "잘린 JSON": '{"text": "인사 시스템에서 신',
            "text 없는 JSON": '{"answer": "인사 시스템에서 신청하세요."}',
        }
        for name, output in outputs.items():
            with self.subTest(name):
                trace = self.trace(output=output)
                self.assertEqual(trace.origin, "output")

    def test_check_output_catches_unwrapped_model_json(self):
        raw = answer_json()
        self.assertEqual(check_output(raw, {"text": ANSWER}), (PASS, "", ANSWER))
        status, detail, _ = check_output(raw, {"text": raw})
        self.assertEqual(status, FAIL)
        self.assertIn("모델 출력 원문", detail)

    def test_process_response_records_model_error(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        trace_model = Mock()
        trace_model.with_structured_output.return_value = RunnableLambda(
            model_raises(ConnectionError("연결 거부"))
        )
        with (
            patch.object(assistant, "load_document_context", lambda: "제목: 문서"),
            patch.object(assistant, "ensure_ollama_server", lambda: None),
            patch.object(assistant, "create_chat_model", lambda provider: trace_model),
        ):
            result = assistant.process_response(
                {"ok": True, "text": QUESTION, "reason": ""},
                SEARCH,
                provider="ollama",
                document_snapshot=SimpleNamespace(
                    documents=(SimpleNamespace(title="문서", body="본문"),)
                ),
            )["ollama"]
        self.assertFalse(result["success"])
        self.assertEqual(result["answer"], "")
        self.assertEqual(result["error"], "ConnectionError: 연결 거부")


class FinalAnswerTests(DocumentsMixin, unittest.TestCase):
    """직원이 받는 /ask 응답과 실행 실패의 502 변환을 검사한다."""

    def test_valid_answer_reaches_employee_as_sentence(self):
        trace = self.trace(output=answer_json())
        self.assertIsNone(trace.origin, trace.report())
        self.assertEqual(trace.response.status_code, 200)
        self.assertEqual(trace.response.json()["text"], ANSWER)

    def test_unusable_model_output_returns_502(self):
        # 체인의 출력 오류를 실행 실패 결과로 전달하면 /ask는 502로 변환한다.
        for output in (ANSWER, '{"text": "인사 시스템에서 신'):
            with self.subTest(output=output):
                trace = self.trace(output=output)
                self.assertEqual(trace.response.status_code, 502)
                self.assertEqual(trace.response.json(), FAILURE_BODY)

    def test_chain_errors_return_502(self):
        # 실행 단계 오류도 실패 결과를 통해 공개 502 계약으로 변환한다.
        cases = {
            "모델 호출 오류": {"model": model_raises(ConnectionError("연결 거부"))},
            "4000자 초과": {
                "question": "가" * (assistant.MAX_INPUT_CHARS + 1),
                "model": model_returns(answer_json()),
            },
            "문서 파일 없음": {
                "model": model_returns(answer_json()),
                "documents_file": self.documents.with_name("missing.jsonl"),
            },
        }
        for name, options in cases.items():
            with self.subTest(name):
                trace = self.trace(**options)
                self.assertEqual(trace.response.status_code, 502)
                self.assertEqual(trace.response.json(), FAILURE_BODY)


@unittest.skipUnless(os.getenv("RUN_LIVE_LLM") == "1", "RUN_LIVE_LLM=1일 때만 실행")
class LiveOllamaTests(unittest.TestCase):
    """로컬 Ollama와 설정된 정책 문서 파일로 라벨별 응답의 단계를 출력한다.

    Ollama가 꺼져 있으면 실행기가 `ollama serve`를 시작한다. OpenAI는 부르지 않는다.
    """

    def test_live_answers_pass_input_documents_and_prompt(self):
        for label, question in LIVE_QUESTIONS.items():
            with self.subTest(label):
                trace = trace_final_answer(question, label=label, live=True)
                print(f"\n[{label}] {question}\n{trace.report()}")
                print(f"모델 출력: {trace.raw_output!r}")
                print(f"/ask 응답: {trace.response.status_code} {trace.response.text}")
                self.assertNotIn(trace.origin, ("input", "documents", "prompt"))


if __name__ == "__main__":
    unittest.main()
