"""LangChain callback rows for a single traced request."""

import hashlib
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .sink import _full_prompt, clip_text, to_record
from .stages import _safe_stage_metadata

GENERATION_STAGE = "생성 판정"
_GENERATION_FIELDS = frozenset(
    {
        "model",
        "profile",
        "snapshot_fingerprint",
        "prompt_sha256",
        "prompt_roles_sha256",
        "config",
        "status",
        "seconds",
        "input_tokens",
        "output_tokens",
        "error_type",
        "finish_reason",
        "evidence_state",
    }
)
_GENERATION_ALIASES = {
    "model_name": "model",
    "prompt_profile": "profile",
    "snapshot_sha256": "snapshot_fingerprint",
    "generation_status": "status",
    "elapsed_seconds": "seconds",
    "generation_seconds": "seconds",
}
_ROUTING_FIELDS = frozenset(
    {
        "routing_mode",
        "label_source",
        "classification_status",
        "classification_elapsed_seconds",
        "processing_path",
        "generation_attempted",
    }
)
_ROUTING_MODES = frozenset({"gate", "shadow", "advisory"})
_LABEL_SOURCES = frozenset({"model", "client"})
_CLASSIFICATION_STATUSES = frozenset(
    {
        "running",
        "ok",
        "provided",
        "not_run",
        "unavailable",
        "inference_error",
        "unexpected_error",
        "invalid_label",
    }
)
_PROCESSING_PATHS = frozenset(
    {
        "classification",
        "classification_failed",
        "classification_error_shadow",
        "classification_error_advisory",
        "upstream_failure",
        "invalid_label",
        "clarify",
        "unsupported",
        "document_lookup",
        "retrieval",
        "empty_retrieval",
        "empty_documents",
        "generation",
    }
)

ROOT_STAGE = "실행기 전체"
MODEL_STAGE = "모델 호출"
StageResolver = Callable[[str | None, Any, str | None], tuple[str, bool]]


def _error_record(error: BaseException) -> str:
    """Return only the exception type; messages may contain prompt inputs."""
    return type(error).__name__


def stage_of(name: str | None, tags, parent_stage: str | None) -> tuple[str, bool]:
    """Return a generic stage label and whether the node only wraps child runs."""
    name = name or ""
    if parent_stage is None:
        return ROOT_STAGE, False
    if name in {"PromptTemplate", "ChatPromptTemplate"}:
        return "프롬프트 만들기", False
    if name in {
        "RunnableAssign",
        "RunnableBranch",
        "RunnableParallel",
        "RunnableSequence",
    }:
        return name, True
    return name or "알 수 없음", False


class TraceCallback(BaseCallbackHandler):
    """요청 1건 동안 LangChain 단계를 이름 붙은 행(시작·끝을 합친 1행)으로 모은다."""

    run_inline = True

    def __init__(self, stage_resolver: StageResolver | None = None):
        self.trace_id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self._stage_resolver = stage_resolver or stage_of
        self._runs: dict[str, dict] = {}
        self._classification_label: str | None = None
        self._classification_seconds: float | None = None
        self._generation: dict[str, Any] | None = None
        self._routing: dict[str, Any] = {}
        self._retrieval: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.perf_counter() - self.started

    def record_classification(self, label: str) -> None:
        """실제 분류 라벨과 분류 완료 시점만 보관한다."""
        with self._lock:
            self._classification_label = str(label)
            self._classification_seconds = round(self._now(), 3)

    def record_generation(self, fields: Mapping[str, Any]) -> None:
        """모델 호출 결과와 구분되는 안전한 생성 판정 메타데이터를 보관한다."""
        safe: dict[str, Any] = {}
        for key, value in fields.items():
            normalized_key = _GENERATION_ALIASES.get(key, key)
            if normalized_key not in _GENERATION_FIELDS:
                continue
            if normalized_key == "evidence_state" and (
                value is not None
                and (
                    not isinstance(value, str)
                    or value
                    not in {"available", "no_matches", "no_published_documents"}
                )
            ):
                continue
            if normalized_key == "config":
                if not isinstance(value, dict):
                    continue
                allowed = {
                    "provider",
                    "model_name",
                    "timeout_seconds",
                    "context_window",
                    "max_output_tokens",
                    "reasoning_effort",
                    "temperature",
                    "output_mode",
                }
                value = {
                    k: v
                    for k, v in value.items()
                    if k in allowed and (v is None or isinstance(v, str | int | float))
                }
            elif normalized_key == "error_type":
                # 호출자는 예외 객체가 아닌 형식 이름만 전달해야 한다.
                if isinstance(value, type) and issubclass(value, BaseException):
                    value = value.__name__
                elif isinstance(value, BaseException):
                    value = type(value).__name__
                elif value is not None and not isinstance(value, str):
                    continue
            elif normalized_key in {"seconds", "input_tokens", "output_tokens"}:
                if value is not None and not isinstance(value, int | float):
                    continue
            elif value is not None and not isinstance(value, str):
                enum_value = getattr(value, "value", None)
                if isinstance(enum_value, str):
                    value = enum_value
                else:
                    continue
            safe[normalized_key] = value

        with self._lock:
            self._generation = safe

    def record_routing(self, fields: Mapping[str, Any]) -> None:
        """Record allowlisted routing state without request or exception text."""
        safe: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in _ROUTING_FIELDS:
                continue
            if key == "routing_mode" and value not in _ROUTING_MODES:
                continue
            if key == "label_source" and value not in _LABEL_SOURCES:
                continue
            if key == "classification_status" and value not in _CLASSIFICATION_STATUSES:
                continue
            if key == "classification_elapsed_seconds":
                if value is not None and not isinstance(value, int | float):
                    continue
                if value is not None:
                    value = round(max(float(value), 0.0), 3)
            if key == "processing_path" and value not in _PROCESSING_PATHS:
                continue
            if key == "generation_attempted" and not isinstance(value, bool):
                continue
            safe[key] = value
        with self._lock:
            self._routing.update(safe)

    def record_retrieval(self, fields: Mapping[str, Any]) -> None:
        """Store the retrieval event after its public adapter validates fields."""
        with self._lock:
            self._retrieval = _safe_stage_metadata(fields)

    def _start(
        self,
        run_id,
        parent_run_id,
        *,
        name,
        tags=None,
        model_call=False,
        trace_stage=None,
        trace_role=None,
        **fields,
    ):
        run_id = str(run_id)
        parent_run_id = str(parent_run_id) if parent_run_id else None
        with self._lock:
            parent = self._runs.get(parent_run_id)
            if trace_stage is not None:
                stage, wrapper = trace_stage, trace_role == "wrapper"
            elif model_call:
                stage, wrapper = MODEL_STAGE, False
            else:
                parent_stage = parent["stage"] if parent else None
                if parent is None and parent_run_id:
                    parent_stage = "알 수 없음"
                stage, wrapper = self._stage_resolver(name, tags, parent_stage)
            # 부모가 없는 실행이 체인 실행 1번(모델 1개)의 시작이고, 자식은 그 시작을 물려받는다
            root_run_id = parent["root_run_id"] if parent else (parent_run_id or run_id)
            self._runs[run_id] = {
                "stage": stage,
                "wrapper": wrapper,
                "status": "running",
                "started": self._now(),
                "fields": fields,
                "name": name,
                "role": trace_role,
                "root_run_id": root_run_id,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
            }

    def _finish(self, run_id, status: str, **fields):
        with self._lock:
            run = self._runs.get(str(run_id))
            if run is None:
                return
            run["status"] = status
            run["seconds"] = round(self._now() - run["started"], 3)
            run["fields"].update(fields)

    def _chain_input_record(self, inputs: Any) -> dict[str, Any]:
        """Project generic Runnable inputs onto safe diagnostic fields."""
        return _safe_stage_metadata(inputs)

    def _chain_output_record(self, outputs: Any) -> dict[str, Any]:
        """Project generic Runnable outputs onto safe diagnostic fields."""
        return _safe_stage_metadata(outputs)

    def on_chain_start(
        self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs
    ):
        name = kwargs.get("name") or (serialized or {}).get("name")
        run_metadata = kwargs.get("metadata") or {}
        is_named_stage = run_metadata.get("sanaebi_trace_run_name") == name
        self._start(
            run_id,
            parent_run_id,
            name=name,
            tags=kwargs.get("tags"),
            trace_stage=(
                run_metadata.get("sanaebi_trace_stage") if is_named_stage else None
            ),
            trace_role=(
                run_metadata.get("sanaebi_trace_role") if is_named_stage else None
            ),
            metadata=_safe_stage_metadata(run_metadata),
            input=self._chain_input_record(inputs),
        )

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "ok", output=self._chain_output_record(outputs))

    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "error", error=_error_record(error))

    def on_chat_model_start(
        self, serialized, messages, *, run_id, parent_run_id=None, **kwargs
    ):
        metadata = kwargs.get("metadata") or {}
        prompt = "\n".join(str(message.content) for message in messages[0])
        name = kwargs.get("name") or (serialized or {}).get("name")
        is_named_stage = metadata.get("sanaebi_trace_run_name") == name
        self._start(
            run_id,
            parent_run_id,
            name=name,
            tags=kwargs.get("tags"),
            model_call=True,
            trace_stage=(
                metadata.get("sanaebi_trace_stage") if is_named_stage else None
            ),
            trace_role=(metadata.get("sanaebi_trace_role") if is_named_stage else None),
            input=prompt if _full_prompt() else clip_text(prompt),
            provider=metadata.get("ls_provider"),
            model_name=metadata.get("ls_model_name"),
            prompt_chars=len(prompt),
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        generation = response.generations[0][0] if response.generations else None
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}
        self._finish(
            run_id,
            "ok",
            output=to_record(getattr(generation, "text", None)),
            served_model=metadata.get("model_name") or metadata.get("model"),
            # Ollama는 done_reason, OpenAI는 finish_reason으로 끝난 이유를 준다
            finish_reason=metadata.get("done_reason") or metadata.get("finish_reason"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            tool_calls=to_record(getattr(message, "tool_calls", None) or []),
        )

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "error", error=_error_record(error))

    def stage_rows(self) -> list[dict]:
        """기록할 단계 행. 감싸기만 하는 실행은 빼되, 안쪽에 오류가 안 남은 오류는 남긴다."""
        with self._lock:
            runs = list(self._runs.values())
        providers: dict[str, str] = {}
        failed_inside: set[str] = set()
        for run in runs:
            if run["stage"] == MODEL_STAGE and run["fields"].get("provider"):
                providers.setdefault(run["root_run_id"], run["fields"]["provider"])
            if run["status"] == "error":
                parent = run["parent_run_id"]
                while parent and parent not in failed_inside:
                    failed_inside.add(parent)
                    parent = self._runs.get(parent, {}).get("parent_run_id")

        rows = []
        for run in runs:
            if run["wrapper"] and (
                run["status"] != "error" or run["run_id"] in failed_inside
            ):
                continue
            fields = dict(run["fields"])
            rows.append(
                {
                    "trace_id": self.trace_id,
                    "seq": len(rows) + 1,
                    "model": providers.get(run["root_run_id"]),
                    "stage": run["stage"],
                    "status": run["status"],
                    "at_seconds": round(run["started"], 3),
                    "seconds": run.get("seconds"),
                    "input": fields.pop("input", None),
                    "output": fields.pop("output", None),
                    "error": fields.pop("error", None),
                    **fields,
                    "name": run["name"],
                    "role": run["role"],
                    "root_run_id": run["root_run_id"],
                    "run_id": run["run_id"],
                    "parent_run_id": run["parent_run_id"],
                }
            )
        return rows

    def record_rows(self, path: str, request: Any, status: int | None) -> list[dict]:
        """기록할 steps: 맨 앞 분류 행 + LangChain 단계 행."""
        rows = self.stage_rows()
        roots = [row for row in rows if row["parent_run_id"] is None]
        with self._lock:
            label = self._classification_label
            classification_seconds = self._classification_seconds
            generation = (
                dict(self._generation) if self._generation is not None else None
            )
            routing = dict(self._routing)
            retrieval = dict(self._retrieval) if self._retrieval is not None else None
        if label is None and roots and isinstance(roots[0]["input"], dict):
            label = roots[0]["input"].get("classification_label")
        stopped = label is None and not roots and (status or 0) >= 400
        classification_status = routing.get("classification_status")
        classification_step_status = (
            "skipped"
            if classification_status == "not_run"
            else "error"
            if classification_status
            in {"unavailable", "inference_error", "unexpected_error", "invalid_label"}
            else "error"
            if stopped
            else "ok"
        )
        classification = {
            "trace_id": self.trace_id,
            "seq": None,
            "model": None,
            "stage": "분류",
            "status": classification_step_status,
            "at_seconds": 0.0,
            # 새 경로는 분류기가 직접 완료 시점을 기록한다. 과거 체인에서는
            # 첫 체인 시작 시점을 분류 시간의 근사치로 사용한다.
            "seconds": (
                classification_seconds
                if classification_seconds is not None
                else roots[0]["at_seconds"]
                if roots
                else None
            ),
            "input": _question_text(request),
            "output": label,
            "error": f"LangChain 전에 멈춤 (HTTP {status})" if stopped else None,
            "source": (
                "분류기"
                if routing.get("label_source", "model" if path == "/ask" else "client")
                == "model"
                else "요청 값"
            ),
            **routing,
        }
        result_rows = [classification, *rows]
        if retrieval is not None:
            result_rows.append(
                {
                    "trace_id": self.trace_id,
                    "seq": None,
                    "stage": "검색",
                    "input": None,
                    "output": None,
                    "error": None,
                    **retrieval,
                }
            )
        if generation is not None:
            seconds = generation.get("seconds")
            result_rows.append(
                {
                    "trace_id": self.trace_id,
                    "seq": None,
                    "model": generation.get("model"),
                    "stage": GENERATION_STAGE,
                    # 이는 on_llm_end의 finish_reason과 별개인 검증 결과다.
                    "status": generation.get("status", "unknown"),
                    "at_seconds": (
                        round(max(self._now() - seconds, 0), 3)
                        if isinstance(seconds, int | float)
                        else None
                    ),
                    "seconds": seconds,
                    "input": None,
                    "output": None,
                    "error": None,
                    **generation,
                }
            )
        return _numbered(result_rows)


def _numbered(rows: list[dict]) -> list[dict]:
    for seq, row in enumerate(rows, start=1):
        row["seq"] = seq
    return rows


def _question_text(request: Any) -> Any:
    """/ask는 question, /assistant는 response.text에 질문이 있다."""
    if not isinstance(request, dict):
        return None
    if "question" in request:
        return request["question"]
    response = request.get("response")
    return response.get("text") if isinstance(response, dict) else None
