"""Framework-independent, session-local conversation transitions."""

from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from uuid import uuid4

TIMEOUT = 35.0
IDLE_TTL = 1800.0
TIMEOUT_MESSAGE = "응답 시간이 초과되었습니다. 질문을 확인하고 다시 시도해주세요."


@dataclass
class Turn:
    question: str
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "pending"
    answer: str = ""
    error: str = ""


class ChatSession:
    def __init__(self):
        self.turns: list[Turn] = []
        self.draft = ""
        self.error = ""
        self.generation = 0
        self.request_id: str | None = None
        self.pending: Turn | None = None
        self.deadline = 0.0
        self.touched = monotonic()
        self.retry = False
        self.lock = RLock()

    def __deepcopy__(self, memo):
        # gr.State initializes each browser session with a fresh value.
        return ChatSession()

    @property
    def busy(self):
        return self.request_id is not None

    def begin(self, question: str, *, retry_id=None, now=None):
        now = monotonic() if now is None else now
        with self.lock:
            self.expire_idle(now=now)
            if self.busy:
                return None
            self.draft = question
            turn = next((t for t in self.turns if t.id == retry_id), None)
            if retry_id and (turn is None or turn.status != "error"):
                return None
            text = turn.question if turn else question.strip()
            if not text:
                self.error = "질문을 입력해주세요"
                return None
            if turn is None:
                turn = next(
                    (
                        t
                        for t in reversed(self.turns)
                        if t.status == "error" and t.question == text
                    ),
                    None,
                )
            if turn is None:
                turn = Turn(text)
                self.turns.append(turn)
            turn.status, turn.answer, turn.error = "pending", "", ""
            self.retry = retry_id is not None
            self.error = ""
            self.request_id = uuid4().hex
            self.pending = turn
            self.deadline = now + TIMEOUT
            self.touched = now
            return self.generation, self.request_id

    def matches(self, token):
        return token is not None and token == (self.generation, self.request_id)

    def finish(self, token, *, answer="", error="", now=None):
        with self.lock:
            if not self.matches(token) or self.pending is None:
                return False
            self.pending.status = "error" if error else "success"
            self.pending.answer, self.pending.error = answer, error
            self.error = error
            if not error and not self.retry:
                self.draft = ""
            self.pending = None
            self.request_id = None
            self.touched = monotonic() if now is None else now
            return True

    def expire(self, *, now=None):
        now = monotonic() if now is None else now
        with self.lock:
            if not self.busy or now < self.deadline:
                return False
            return self.finish(
                (self.generation, self.request_id), error=TIMEOUT_MESSAGE, now=now
            )

    def clear(self):
        with self.lock:
            self.generation += 1
            self.request_id = None
            self.pending = None
            self.turns.clear()
            self.draft = self.error = ""
            self.touched = monotonic()

    def expire_idle(self, *, now=None):
        now = monotonic() if now is None else now
        with self.lock:
            if not self.busy and now - self.touched >= IDLE_TTL:
                self.clear()
                return True
            return False

    def messages(self):
        result = []
        for turn in self.turns:
            result.append({"role": "user", "content": turn.question})
            if turn.status == "success":
                result.append({"role": "assistant", "content": turn.answer})
        return result
