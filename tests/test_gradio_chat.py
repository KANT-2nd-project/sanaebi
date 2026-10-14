"""Gradio mounting and real controller boundaries."""

import asyncio
import threading
import unittest
from time import monotonic
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.answer_text import LLMResponseError
from app.fastapi_main import app
from app.ui.chat_state import ChatSession
from app.ui.gradio_chat import ChatController
from app.ui.question_adapter import answer_question


class AdapterTests(unittest.TestCase):
    def test_echo_and_invalid_answer(self):
        self.assertEqual(answer_question("  휴가\n "), "휴가")
        with (
            patch("app.ui.question_adapter.generate_answer", return_value={"text": ""}),
            self.assertRaises(LLMResponseError),
        ):
            answer_question("질문")

    def test_mount_and_rest_contract(self):
        with TestClient(app) as client:
            response = client.get("/chat/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("noindex", response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("noindex", response.headers["x-robots-tag"])
            self.assertIn("사내비", response.text)
            self.assertEqual(
                client.post("/ask", json={"question": "질문"}).json(),
                {"ok": True, "text": "질문", "reason": ""},
            )
            self.assertEqual(
                client.post("/ask", json={"question": " "}).status_code, 422
            )
            self.assertNotIn("/chat", client.get("/openapi.json").json()["paths"])


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_echo_error_and_manual_retry(self):
        state = ChatSession()
        controller = ChatController(
            lambda _: (_ for _ in ()).throw(LLMResponseError("private"))
        )
        token = state.begin("질문")
        await controller.execute(state, token)
        self.assertEqual(state.draft, "질문")
        self.assertNotIn("private", state.error)
        controller.answer = lambda q: q
        token = state.begin("질문")
        await controller.execute(state, token)
        self.assertEqual(len(state.turns), 1)
        self.assertEqual(state.turns[0].answer, "질문")

    async def test_cancelled_worker_does_not_admit_second_worker(self):
        entered, release = threading.Event(), threading.Event()

        def slow(q):
            entered.set()
            release.wait(2)
            return q

        controller = ChatController(slow)
        state = ChatSession()
        token = state.begin("이전")
        task = asyncio.create_task(controller.execute(state, token))
        await asyncio.to_thread(entered.wait, 1)
        state.clear()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(controller.slot.acquire(blocking=False))
        release.set()
        await asyncio.sleep(0.05)
        self.assertEqual(state.turns, [])
        self.assertTrue(controller.slot.acquire(blocking=False))
        controller.slot.release()

    async def test_clear_between_admission_and_execution_skips_answer(self):
        calls = []
        controller = ChatController(lambda q: calls.append(q) or q)
        state = ChatSession()
        token = state.begin("clear before worker")
        state.clear()
        self.assertFalse(await controller.execute(state, token))
        self.assertEqual(calls, [])

    async def test_waiting_timeout_never_calls_answer(self):
        calls = []
        controller = ChatController(lambda q: calls.append(q) or q)
        controller.slot.acquire()
        state = ChatSession()
        token = state.begin("대기")
        state.deadline = monotonic() + 0.01
        await controller.execute(state, token)
        controller.slot.release()
        self.assertEqual(calls, [])
        self.assertIn("초과", state.error)
        self.assertEqual(state.draft, "대기")
