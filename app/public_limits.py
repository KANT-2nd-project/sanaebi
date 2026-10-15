"""Admission limits and a persistent daily budget for the public demo."""

from __future__ import annotations

import math
import os
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from time import monotonic

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.settings import PROJECT_ROOT

KST = timezone(timedelta(hours=9), name="Asia/Seoul")
DEFAULT_DAILY_GENERATION_LIMIT = 1_000
DEFAULT_MAX_INFLIGHT_ASKS = 2


class GenerationBudgetExceeded(Exception):
    """The public demo has used today's allowed provider calls."""

    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)
        super().__init__("daily generation budget exhausted")


class GenerationBudgetUnavailable(Exception):
    """The service could not safely check or reserve the generation budget."""


def is_public_demo_enabled() -> bool:
    return os.getenv("SANAEBI_PUBLIC_DEMO") == "1"


def get_daily_generation_limit() -> int:
    value = os.getenv("SANAEBI_DAILY_GENERATION_LIMIT")
    limit = DEFAULT_DAILY_GENERATION_LIMIT if value is None else int(value)
    if limit < 1:
        raise ValueError("SANAEBI_DAILY_GENERATION_LIMIT must be at least 1")
    return limit


def get_generation_budget_path() -> Path:
    value = os.getenv("SANAEBI_GENERATION_BUDGET_DB")
    path = (
        Path(value).expanduser()
        if value
        else PROJECT_ROOT / "var" / "generation-budget.sqlite3"
    )
    return path if path.is_absolute() else PROJECT_ROOT / path


def get_max_inflight_asks() -> int:
    value = os.getenv("SANAEBI_MAX_INFLIGHT_ASKS")
    maximum = DEFAULT_MAX_INFLIGHT_ASKS if value is None else int(value)
    if maximum < 1 or maximum > DEFAULT_MAX_INFLIGHT_ASKS:
        raise ValueError("SANAEBI_MAX_INFLIGHT_ASKS must be 1 or 2")
    return maximum


class DailyGenerationBudget:
    """Atomically reserve a provider attempt against a KST calendar day."""

    def __init__(
        self,
        database_path: Path,
        daily_limit: int = DEFAULT_DAILY_GENERATION_LIMIT,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        if daily_limit < 1:
            raise ValueError("daily_limit must be at least 1")
        self.database_path = Path(database_path)
        self.daily_limit = daily_limit
        self._clock = clock or (lambda: datetime.now(UTC))

    def initialize(self) -> None:
        connection = None
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_path, timeout=5)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_budget (
                    budget_date TEXT PRIMARY KEY,
                    reserved_calls INTEGER NOT NULL CHECK (reserved_calls >= 0)
                )
                """
            )
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise GenerationBudgetUnavailable("generation budget unavailable") from exc
        finally:
            if connection is not None:
                connection.close()

    def reserve(self) -> None:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        now_kst = now.astimezone(KST)
        budget_date = now_kst.date().isoformat()
        retry_after = _seconds_until_kst_midnight(now_kst)
        connection = None
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.database_path, timeout=5, isolation_level=None
            )
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT reserved_calls FROM generation_budget WHERE budget_date = ?",
                (budget_date,),
            ).fetchone()
            reserved = row[0] if row else 0
            if reserved >= self.daily_limit:
                connection.rollback()
                raise GenerationBudgetExceeded(retry_after)
            if row:
                connection.execute(
                    "UPDATE generation_budget SET reserved_calls = ? WHERE budget_date = ?",
                    (reserved + 1, budget_date),
                )
            else:
                connection.execute(
                    "INSERT INTO generation_budget (budget_date, reserved_calls) VALUES (?, 1)",
                    (budget_date,),
                )
            connection.commit()
        except GenerationBudgetExceeded:
            raise
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.rollback()
            raise GenerationBudgetUnavailable("generation budget unavailable") from exc
        finally:
            if connection is not None:
                connection.close()


def _seconds_until_kst_midnight(now_kst: datetime) -> int:
    next_day = date.fromordinal(now_kst.date().toordinal() + 1)
    tomorrow = datetime.combine(next_day, time.min, tzinfo=KST)
    return max(1, math.ceil((tomorrow - now_kst).total_seconds()))


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    """Thread-safe per-key token buckets with a bounded number of IP entries."""

    def __init__(self, *, clock: Callable[[], float] = monotonic):
        self._clock = clock
        self._buckets: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    def consume(
        self, category: str, client_ip: str, *, per_minute: int, burst: int
    ) -> int | None:
        now = self._clock()
        refill_per_second = per_minute / 60
        key = (category, client_ip)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(burst), updated_at=now)
            else:
                bucket.tokens = min(
                    float(burst),
                    bucket.tokens
                    + max(0.0, now - bucket.updated_at) * refill_per_second,
                )
                bucket.updated_at = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                retry_after = None
            else:
                retry_after = max(1, math.ceil((1 - bucket.tokens) / refill_per_second))

            self._buckets[key] = bucket
            self._buckets.move_to_end(key)
            while len(self._buckets) > 10_000:
                self._buckets.popitem(last=False)
            return retry_after


class PublicDemoRateLimitMiddleware:
    """Apply per-IP request buckets only when public-demo mode is enabled."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.limiter = TokenBucketLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_public_demo_enabled():
            await self.app(scope, receive, send)
            return

        limit = _request_limit(scope.get("path", ""), scope.get("method", ""))
        if limit is None:
            await self.app(scope, receive, send)
            return

        category, per_minute, burst = limit
        client = scope.get("client")
        client_ip = str(client[0]) if client else "unknown"
        retry_after = self.limiter.consume(
            category, client_ip, per_minute=per_minute, burst=burst
        )
        if retry_after is None:
            await self.app(scope, receive, send)
            return

        if category == "ask":
            response = JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "text": "",
                    "reason": "요청이 많습니다. 잠시 후 다시 시도해주세요.",
                },
                headers={
                    "Retry-After": str(retry_after),
                    "Cache-Control": "no-store",
                },
            )
        elif scope["path"] == "/regist-docs":
            response = JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "text": "",
                    "reason": "문서 요청이 많습니다. 잠시 후 다시 시도해주세요.",
                },
                headers={
                    "Retry-After": str(retry_after),
                    "Cache-Control": "no-store",
                },
            )
        else:
            response = JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "error": {
                        "code": "rate_limited",
                        "message": "문서 요청이 많습니다. 잠시 후 다시 시도해주세요.",
                    },
                },
                headers={
                    "Retry-After": str(retry_after),
                    "Cache-Control": "no-store",
                },
            )
        await response(scope, receive, send)


def _request_limit(path: str, method: str) -> tuple[str, int, int] | None:
    if path == "/ask" and method == "POST":
        return "ask", 6, 3
    if path == "/regist-docs" and method == "POST":
        return "document", 12, 5
    if (path == "/documents" or path.startswith("/documents/")) and method in {
        "POST",
        "PATCH",
        "PUT",
        "DELETE",
    }:
        return "document", 12, 5
    return None
