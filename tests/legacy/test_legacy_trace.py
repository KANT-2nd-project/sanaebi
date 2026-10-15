import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.diagnostics import trace
from archive.answering_v1 import assistant as sanaebi_assistant

LABEL = "SEARCH_KNOWLEDGE"


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

    def test_record_rows_start_with_classification(self):
        callback = trace.TraceCallback()
        with (
            patch.object(
                sanaebi_assistant,
                "create_chat_model",
                return_value=ToolAnswerModel(responses=[tool_answer()]),
            ),
            patch.object(
                sanaebi_assistant, "load_document_context", return_value="연차 문서"
            ),
        ):
            sanaebi_assistant.create_chain("openai").invoke(
                {
                    "response": {"ok": True, "text": "연차는 어디서 신청해?"},
                    "classification_label": LABEL,
                },
                config={"callbacks": [callback]},
            )
        rows = callback.record_rows("/ask", {"question": "연차는 어디서 신청해?"}, 200)
        self.assertEqual([row["seq"] for row in rows], list(range(1, 10)))
        self.assertEqual(
            (rows[0]["stage"], rows[0]["output"], rows[0]["source"]),
            ("분류", LABEL, "분류기"),
        )
        self.assertEqual(rows[1]["stage"], trace.ROOT_STAGE)

    def test_failed_input_path_has_its_own_stage(self):
        rows = self.run_chain(
            {"ok": False, "text": "", "reason": "질문이 비었습니다"},
            ToolAnswerModel(responses=[tool_answer()]),
        )
        self.assertEqual(
            [row["stage"] for row in rows],
            [trace.ROOT_STAGE, "입력 정리", "경로 선택", "입력 오류 응답"],
        )
