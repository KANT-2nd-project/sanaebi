"""Gradio presentation and session events; no model initialization."""

import asyncio
import html
import logging
import threading
from pathlib import Path
from time import monotonic

import gradio as gr
from pydantic import ValidationError

from app.answer_text import LLM_RESPONSE_ERROR, LLMResponseError
from app.ui.chat_state import IDLE_TTL, TIMEOUT_MESSAGE, ChatSession
from app.ui.question_adapter import answer_question

ASSETS = Path(__file__).parent
logger = logging.getLogger(__name__)
EXAMPLES = ["휴가 신청 절차", "비용 정산 준비", "업무용 계정 발급"]


class ChatController:
    def __init__(self, answer=answer_question):
        self.answer = answer
        self.slot = threading.BoundedSemaphore(1)

    async def execute(self, state, token):
        """A cancelled coroutine never releases a still-running worker's slot."""
        if not state.matches(token) or state.pending is None:
            return False
        question = state.pending.question
        try:
            async with asyncio.timeout(max(0, state.deadline - monotonic())):
                while not self.slot.acquire(blocking=False):
                    if not state.matches(token):
                        return False
                    await asyncio.sleep(0.05)
                if not state.matches(token):
                    self.slot.release()
                    return False

                def work():
                    try:
                        return self.answer(question)
                    finally:
                        self.slot.release()

                answer = await asyncio.to_thread(work)
            return state.finish(token, answer=answer)
        except TimeoutError:
            return state.finish(token, error=TIMEOUT_MESSAGE)
        except (LLMResponseError, ValidationError):
            return state.finish(token, error=LLM_RESPONSE_ERROR)
        except asyncio.CancelledError:
            state.finish(token, error="요청을 취소했습니다. 다시 시도할 수 있습니다.")
            raise
        except Exception:
            logger.exception("Gradio answer failed")
            return state.finish(token, error=LLM_RESPONSE_ERROR)


def create_chat(answer=answer_question):
    controller = ChatController(answer)
    with gr.Blocks(
        analytics_enabled=False, title="사내비 | 질문", fill_height=True
    ) as demo:
        state = gr.State(
            ChatSession(), time_to_live=IDLE_TTL, delete_callback=lambda s: s.clear()
        )
        with gr.Row(elem_id="chat-header"):
            gr.HTML(
                '<a href="/" class="brand">사내비</a><a href="#usage">사용 안내</a>'
            )
            clear = gr.Button("새 대화", elem_id="new-chat", size="sm", min_width=80)
        welcome = gr.HTML(
            "<h1>무엇을 도와드릴까요?</h1><p>회사 규정과 업무 절차에 대해 질문해보세요.</p>",
            elem_id="welcome",
        )
        chat = gr.Chatbot(
            label="대화",
            show_label=False,
            elem_id="conversation",
            height="100%",
            autoscroll=False,
            buttons=[],
            feedback_options=[],
            render_markdown=False,
            allow_file_downloads=False,
            layout="bubble",
            min_height=120,
        )
        gr.HTML(
            '<button type="button" id="latest-message" hidden>최신 메시지 ↓</button>'
        )
        with gr.Column(elem_id="composer"):
            question = gr.Textbox(
                label="질문",
                lines=2,
                max_lines=7,
                placeholder="궁금한 내용을 입력하세요",
                autofocus=False,
                elem_id="question",
                html_attributes={"lang": "ko"},
            )
            gr.HTML(
                '<p id="input-help">Enter 전송 · Shift+Enter 줄바꿈 · 터치 기기는 버튼으로 전송</p>'
            )
            error = gr.HTML(
                '<div id="question-error" role="status"></div>', elem_id="error-region"
            )
            gr.HTML('<p id="connection-error" role="status" hidden></p>')
            with gr.Row(elem_id="composer-actions"):
                retry_choice = gr.Dropdown(
                    label="실패한 질문",
                    choices=[],
                    visible=False,
                    elem_id="retry-choice",
                )
                retry = gr.Button(
                    "선택 질문 재시도", visible=False, elem_id="retry-question"
                )
                send = gr.Button("질문하기", variant="primary", elem_id="send-question")
        with gr.Row(elem_id="examples") as examples:
            for text in EXAMPLES:
                button = gr.Button(text, size="sm", min_width=100)
                button.click(
                    lambda text=text: text,
                    outputs=question,
                    queue=False,
                    api_visibility="private",
                )
        gr.HTML(
            '<details id="usage"><summary>사용 안내</summary>'
            "<p>현재는 입력한 질문을 그대로 돌려주는 연결 확인(echo) 단계입니다. 이전 메시지를 답변에 참조하지 않습니다.</p>"
            "<p>새로고침·새 대화·서버 재시작 시 기록이 초기화됩니다. 서버의 임시 세션 기록은 30분 동안 사용하지 않으면 만료됩니다.</p>"
            "<p>실제 신청·승인·개인 기록 조회는 지원하지 않습니다.</p></details>"
        )
        marker = gr.HTML(
            '<span data-busy="false" data-turns="0" data-generation="0"></span>',
            elem_id="chat-status",
        )
        expire = gr.Button(
            "시간 제한", elem_id="expire-question", elem_classes=["internal-control"]
        )
        clock = gr.Timer(60)
        outputs = [
            state,
            chat,
            question,
            error,
            retry_choice,
            retry,
            marker,
            examples,
            welcome,
        ]

        def view(s):
            failures = [(t.question[:40], t.id) for t in s.turns if t.status == "error"]
            message = "답변을 확인하고 있습니다." if s.busy else s.error
            return (
                s,
                s.messages(),
                gr.update(value=s.draft),
                f'<div id="question-error" role="status">{html.escape(message)}</div>',
                gr.update(
                    choices=failures,
                    value=failures[-1][1] if failures else None,
                    visible=bool(failures),
                ),
                gr.update(visible=bool(failures)),
                (
                    f'<span data-busy="{str(s.busy).lower()}" data-turns="{len(s.turns)}" '
                    f'data-generation="{s.generation}" data-error="{str(bool(s.error)).lower()}"></span>'
                ),
                gr.update(visible=not s.turns),
                gr.update(visible=not s.turns),
            )

        async def submit(text, s):
            token = s.begin(text)
            if token is None:
                if not s.busy:
                    yield view(s)
                return
            yield view(s)
            if await controller.execute(s, token):
                yield view(s)

        async def retry_submit(text, turn_id, s):
            token = s.begin(text, retry_id=turn_id)
            if token is None:
                return
            yield view(s)
            if await controller.execute(s, token):
                yield view(s)

        event_args = {
            "outputs": outputs,
            "concurrency_limit": 16,
            "concurrency_id": "chat-events",
            "api_visibility": "private",
            "show_progress": "hidden",
        }
        submit_event = send.click(submit, inputs=[question, state], **event_args)
        retry_event = retry.click(
            retry_submit, inputs=[question, retry_choice, state], **event_args
        )

        def reset(s):
            s.clear()
            return view(s)

        clear.click(
            reset,
            state,
            outputs,
            queue=False,
            cancels=[submit_event, retry_event],
            api_visibility="private",
        )

        def timeout(s):
            # The browser timer starts before Gradio admission, earlier than begin().
            if s.busy:
                s.finish((s.generation, s.request_id), error=TIMEOUT_MESSAGE)
            return view(s)

        expire.click(
            timeout,
            state,
            outputs,
            queue=False,
            cancels=[submit_event, retry_event],
            api_visibility="private",
        )

        def idle(s):
            return view(s) if s.expire_idle() else tuple(gr.skip() for _ in outputs)

        clock.tick(
            idle,
            state,
            outputs,
            queue=False,
            api_visibility="private",
            show_progress="hidden",
        )

        def edit(text, s):
            if not s.busy:
                s.draft = text
                s.touched = monotonic()
            return s

        question.input(
            edit,
            [question, state],
            outputs=state,
            queue=False,
            api_visibility="private",
            show_progress="hidden",
        )
    demo.queue(max_size=16, default_concurrency_limit=16)
    return demo


def mount_chat(app, answer=answer_question):
    theme = gr.themes.Base(
        primary_hue="emerald",
        font=["system-ui", "Malgun Gothic", "sans-serif"],
        font_mono=["monospace"],
    )
    theme.set(
        body_text_color="#172b26",
        body_background_fill="#f7f9f8",
        block_background_fill="white",
        block_label_background_fill="white",
        input_background_fill="white",
        input_text_size="16px",
    )
    tokens = theme.to_dict()["theme"]
    theme.set(
        **{
            key: tokens[key[:-5]]
            for key in tokens
            if key.endswith("_dark") and key[:-5] in tokens
        }
    )
    return gr.mount_gradio_app(
        app,
        create_chat(answer),
        path="/chat",
        ssr_mode=False,
        show_error=False,
        theme=theme,
        css_paths=[ASSETS / "gradio_chat.css"],
        js=(ASSETS / "gradio_chat.js").read_text(),
        head='<meta name="robots" content="noindex,nofollow"><meta name="color-scheme" content="light">',
        footer_links=[],
        run_history=False,
        enable_monitoring=False,
    )
