"""Gradio와 무관한 대화 상태 계약."""

import unittest

from app.ui.chat_state import ChatSession


class ChatStateTests(unittest.TestCase):
    def test_two_turns_accumulate_and_success_clears_submitted_draft(self):
        state = ChatSession()
        token = state.begin("휴가")
        self.assertEqual(len(state.turns), 1)
        self.assertEqual(state.draft, "휴가")
        state.finish(token, answer="휴가")
        state.begin("정산")
        self.assertEqual([t.question for t in state.turns], ["휴가", "정산"])

    def test_failure_retry_reuses_turn_but_edit_adds_turn(self):
        state = ChatSession()
        token = state.begin("휴가")
        state.finish(token, error="실패")
        self.assertEqual(state.draft, "휴가")
        turn_id = state.turns[0].id
        token = state.begin("휴가")
        self.assertEqual(state.turns[0].id, turn_id)
        self.assertEqual(len(state.turns), 1)
        state.finish(token, error="실패")
        state.begin("다른 질문")
        self.assertEqual(len(state.turns), 2)

    def test_retry_preserves_other_draft_and_uses_original_question(self):
        state = ChatSession()
        token = state.begin("원래 질문")
        state.finish(token, error="실패")
        token = state.begin("작성 중", retry_id=state.turns[0].id)
        self.assertEqual(state.pending.question, "원래 질문")
        state.finish(token, answer="답변")
        self.assertEqual(state.draft, "작성 중")

    def test_duplicate_blocked_and_clear_invalidates_late_result(self):
        state = ChatSession()
        old = state.begin("이전")
        self.assertIsNone(state.begin("중복"))
        state.clear()
        new = state.begin("새 질문")
        self.assertFalse(state.finish(old, answer="늦은 답변"))
        self.assertTrue(state.busy)
        self.assertTrue(state.finish(new, answer="새 답변"))
        self.assertEqual(len(state.turns), 1)

    def test_deadline_includes_waiting_and_invalidates_late_result(self):
        state = ChatSession()
        token = state.begin("질문", now=100)
        self.assertFalse(state.expire(now=134.9))
        self.assertTrue(state.expire(now=135))
        self.assertEqual(state.draft, "질문")
        self.assertFalse(state.finish(token, answer="늦음"))
        self.assertFalse(state.busy)

    def test_blank_and_session_isolation(self):
        first, second = ChatSession(), ChatSession()
        self.assertIsNone(first.begin(" \n "))
        self.assertEqual(first.error, "질문을 입력해주세요")
        first.begin("개인 질문")
        self.assertEqual(second.turns, [])

    def test_idle_expiry_resets_history(self):
        state = ChatSession()
        token = state.begin("기록", now=10)
        state.finish(token, answer="답변", now=11)
        self.assertFalse(state.expire_idle(now=1810))
        self.assertTrue(state.expire_idle(now=1811))
        self.assertEqual(state.turns, [])
