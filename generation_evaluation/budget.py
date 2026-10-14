"""Process-safe reservation ledger and conservative OpenAI cost estimates."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import BaseMessage


class BudgetExceeded(RuntimeError):
    """Raised when a reservation would exceed a configured experiment limit."""


class BudgetLedger:
    """Persist cost reservations and wall-clock deadlines across processes."""

    def __init__(
        self,
        path: Path,
        total_dollars: float = 5,
        dev_dollars: float = 3,
        total_seconds: float = 7200,
        dev_seconds: float = 4200,
    ) -> None:
        self.path = Path(path)
        for name, value in (
            ("total_dollars", total_dollars),
            ("dev_dollars", dev_dollars),
            ("total_seconds", total_seconds),
            ("dev_seconds", dev_seconds),
        ):
            self._validate_amount(value, name)
        if dev_dollars > total_dollars or dev_seconds > total_seconds:
            raise ValueError("개발 한도는 전체 한도 이하여야 합니다.")
        self.total_dollars = float(total_dollars)
        self.dev_dollars = float(dev_dollars)
        self.total_seconds = float(total_seconds)
        self.dev_seconds = float(dev_seconds)

    @staticmethod
    def _validate_amount(value: float, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name}은 유한한 0 이상의 숫자여야 합니다.")
        if not isfinite(value) or value < 0:
            raise ValueError(f"{name}은 유한한 0 이상의 숫자여야 합니다.")

    @property
    def _lock_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.lock")

    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self._lock_path.open("a+b")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return lock_file

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"started_at": None, "reservations": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("예산 ledger를 읽을 수 없습니다.") from exc
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("reservations"), dict)
            or (
                data.get("started_at") is not None
                and not isinstance(data["started_at"], (int, float))
            )
        ):
            raise RuntimeError("예산 ledger 형식이 올바르지 않습니다.")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _charged(reservation: dict[str, Any]) -> float:
        if reservation["status"] == "reserved":
            return float(reservation["reserved_dollars"])
        actual = reservation.get("actual_dollars")
        return float(reservation["reserved_dollars"] if actual is None else actual)

    def reserve(
        self, request_id: str, phase: Literal["dev", "final"], dollars: float
    ) -> None:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id는 비어 있을 수 없습니다.")
        if phase not in ("dev", "final"):
            raise ValueError("phase는 dev 또는 final이어야 합니다.")
        self._validate_amount(dollars, "dollars")
        lock_file = self._locked()
        try:
            data = self._read()
            reservations = data["reservations"]
            if request_id in reservations:
                raise BudgetExceeded(
                    "이미 사용된 request_id입니다. 자동 재실행을 거부했습니다."
                )

            dev_charged = sum(
                self._charged(item)
                for item in reservations.values()
                if item["phase"] == "dev"
            )
            total_charged = sum(self._charged(item) for item in reservations.values())
            if phase == "dev" and dev_charged + dollars > self.dev_dollars + 1e-12:
                raise BudgetExceeded("개발 단계 비용 예약이 한도를 초과합니다.")
            if total_charged + dollars > self.total_dollars + 1e-12:
                raise BudgetExceeded("전체 비용 예약이 한도를 초과합니다.")

            now = time.time()
            if data["started_at"] is None:
                data["started_at"] = now
            elapsed = max(0.0, now - float(data["started_at"]))
            total_remaining = max(0.0, self.total_seconds - elapsed)
            dev_remaining = min(total_remaining, max(0.0, self.dev_seconds - elapsed))
            if total_remaining <= 0 or (phase == "dev" and dev_remaining <= 0):
                raise BudgetExceeded("실험 시간 한도가 만료되어 예약할 수 없습니다.")

            reservations[request_id] = {
                "phase": phase,
                "status": "reserved",
                "reserved_dollars": float(dollars),
                "actual_dollars": None,
                "charged_dollars": float(dollars),
                "reserved_at": now,
            }
            self._write(data)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def settle(self, request_id: str, actual_dollars: float | None) -> None:
        if actual_dollars is not None:
            self._validate_amount(actual_dollars, "actual_dollars")
        lock_file = self._locked()
        try:
            data = self._read()
            reservation = data["reservations"].get(request_id)
            if reservation is None:
                raise KeyError(f"예약이 없습니다: {request_id}")
            if reservation["status"] == "settled":
                if reservation.get("actual_dollars") == actual_dollars:
                    return
                raise ValueError("정산된 예약은 같은 금액으로만 재호출할 수 있습니다.")
            reserved = float(reservation["reserved_dollars"])
            charged = reserved if actual_dollars is None else float(actual_dollars)
            reservation.update(
                status="settled",
                actual_dollars=actual_dollars,
                charged_dollars=charged,
                settled_at=time.time(),
            )
            self._write(data)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def remaining_seconds(self, phase: Literal["dev", "final"]) -> float:
        if phase not in ("dev", "final"):
            raise ValueError("phase는 dev 또는 final이어야 합니다.")
        lock_file = self._locked()
        try:
            started_at = self._read()["started_at"]
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        if started_at is None:
            return self.dev_seconds if phase == "dev" else self.total_seconds
        elapsed = max(0.0, time.time() - float(started_at))
        if phase == "dev":
            return min(
                max(0.0, self.total_seconds - elapsed),
                max(0.0, self.dev_seconds - elapsed),
            )
        return max(0.0, self.total_seconds - elapsed)

    def snapshot(self) -> dict[str, Any]:
        lock_file = self._locked()
        try:
            return self._read()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()


_LONG_INPUT = 0.20
_LONG_CACHED_INPUT = 0.02
_LONG_CACHE_WRITE = 0.25
_LONG_OUTPUT = 0.75
_PER_MILLION = 1_000_000


def _estimate_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)


def reserve_cost(messages: list[BaseMessage], max_output: int) -> float:
    """Return a conservative upper bound for one GPT-6 Luna API request.

    Long-tier rates are used for every request until the provider's pricing
    threshold is verified, keeping preflight and settlement estimates aligned.
    """
    if isinstance(max_output, bool) or not isinstance(max_output, int):
        raise TypeError("max_output은 정수여야 합니다.")
    if max_output < 0:
        raise ValueError("max_output은 0 이상이어야 합니다.")
    if not isinstance(messages, list) or any(
        not isinstance(m, BaseMessage) for m in messages
    ):
        raise TypeError("messages는 BaseMessage 목록이어야 합니다.")
    input_upper_tokens = sum(
        len(_estimate_text(message.content).encode("utf-8")) + 256
        for message in messages
    )
    return (
        input_upper_tokens * _LONG_CACHE_WRITE + max_output * _LONG_OUTPUT
    ) / _PER_MILLION


def actual_cost(usage: dict[str, Any], metadata: dict[str, Any]) -> float | None:
    """Estimate observed usage cost conservatively, or return None if unknown.

    The long-context price tier is used for every observed request until the
    provider's token threshold is verified, avoiding an understated spend cap.
    """
    if not isinstance(usage, dict) or not isinstance(metadata, dict):
        raise TypeError("usage와 metadata는 dict여야 합니다.")

    candidates = [usage, metadata]
    for key in ("token_usage", "usage", "usage_metadata"):
        nested = metadata.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)

    def first_int(keys: tuple[str, ...]) -> int | None:
        for candidate in candidates:
            for key in keys:
                value = candidate.get(key)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    return value
        return None

    prompt_tokens = first_int(("prompt_tokens", "input_tokens"))
    output_tokens = first_int(("completion_tokens", "output_tokens"))
    if prompt_tokens is None or output_tokens is None:
        return None

    detail_sources: list[dict[str, Any]] = []
    for candidate in candidates:
        for key in (
            "prompt_tokens_details",
            "input_tokens_details",
            "input_token_details",
            "prompt_token_details",
        ):
            details = candidate.get(key)
            if isinstance(details, dict):
                detail_sources.append(details)

    def first_detail(keys: tuple[str, ...]) -> int | None:
        for details in detail_sources:
            for key in keys:
                value = details.get(key)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    return value
        return None

    cached_tokens = (
        first_detail(("cached_tokens", "cache_read_tokens", "cache_read")) or 0
    )
    cache_write_tokens = first_detail(
        (
            "cache_write_tokens",
            "cache_creation_tokens",
            "cache_creation_input_tokens",
            "cache_creation",
        )
    )
    if cached_tokens + (cache_write_tokens or 0) > prompt_tokens:
        return None

    input_rate = _LONG_INPUT
    cached_rate = _LONG_CACHED_INPUT
    cache_write_rate = _LONG_CACHE_WRITE
    uncategorized = prompt_tokens - cached_tokens - (cache_write_tokens or 0)
    # When cache-write usage is omitted, classify the remainder at the higher
    # cache-write rate rather than assuming it was ordinary uncached input.
    if cache_write_tokens is None:
        cache_write_tokens = uncategorized
        uncategorized = 0
    total = (
        uncategorized * input_rate
        + cached_tokens * cached_rate
        + cache_write_tokens * cache_write_rate
        + output_tokens * _LONG_OUTPUT
    )
    return total / _PER_MILLION
