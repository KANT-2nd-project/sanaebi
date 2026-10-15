import json
from pathlib import Path

from generation.config import config_from_dict
from generation.types import GenerationResult, GenerationStatus
from generation_evaluation.types import GenerationRun

__all__ = [
    "config_from_dict",
    "read_runs_jsonl",
    "result_from_dict",
    "run_from_dict",
    "run_to_dict",
    "save_runs_jsonl",
]


def run_to_dict(run: GenerationRun) -> dict[str, object]:
    result_data = None

    if run.result:
        result_data = {
            "status": run.result.status.value,
            "raw_text": run.result.raw_text,
            "answer": run.result.answer,
            "input_tokens": run.result.input_tokens,
            "output_tokens": run.result.output_tokens,
            "finish_reason": run.result.finish_reason,
            "refusal": run.result.refusal,
        }

    return {
        "case_id": run.case_id,
        "config": {
            "provider": run.config.provider.value,
            "model_name": run.config.model_name,
            "timeout_seconds": run.config.timeout_seconds,
            "context_window": run.config.context_window,
            "max_output_tokens": run.config.max_output_tokens,
            "reasoning_effort": run.config.reasoning_effort,
            "temperature": run.config.temperature,
            "output_mode": run.config.output_mode.value,
        },
        "result": result_data,
        "elapsed_seconds": run.elapsed_seconds,
        "error_type": run.error_type,
        "documents_sha256": run.documents_sha256,
        "document_count": run.document_count,
        "prompt_sha256": run.prompt_sha256,
        "prompt_profile": run.prompt_profile,
    }


def save_runs_jsonl(path: Path, runs: list[GenerationRun]) -> None:
    lines = []

    for run in runs:
        json_str = json.dumps(run_to_dict(run), ensure_ascii=False, allow_nan=False)
        json_str += "\n"
        lines.append(json_str)

    content = "".join(lines)

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("x", encoding="utf-8") as file:
        file.write(content)


def read_runs_jsonl(path: Path) -> list[dict[str, object]]:
    records = []

    with path.open("r", encoding="utf-8") as file:
        for i, line in enumerate(file, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{i}번째 줄의 JSON 형식이 잘못되었습니다: {exc.msg}"
                ) from exc

            if type(row) != dict:
                raise ValueError(f"{i}번째 줄은 JSON 객체여야 합니다.")

            records.append(row)

    return records


def result_from_dict(data: dict[str, object] | None) -> GenerationResult | None:
    if data is None:
        return None

    if not isinstance(data, dict):
        raise TypeError("result는 객체 또는 None이어야 합니다.")

    for field in ("status", "raw_text", "answer"):
        if field not in data:
            raise ValueError(f"result에 {field} 필드가 없습니다.")

    status = data["status"]
    raw_text = data["raw_text"]
    answer = data["answer"]
    refusal = data.get("refusal")

    if not isinstance(status, str):
        raise TypeError("status는 문자열이어야 합니다.")

    if raw_text is not None and not isinstance(raw_text, str):
        raise TypeError("raw_text는 문자열 또는 None이어야 합니다.")

    if answer is not None and not isinstance(answer, str):
        raise TypeError("answer는 문자열 또는 None이어야 합니다.")
    if refusal is not None and not isinstance(refusal, str):
        raise TypeError("refusal은 문자열 또는 None이어야 합니다.")

    for field in ("input_tokens", "output_tokens"):
        value = data.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field}는 정수 또는 None이어야 합니다.")
            if value < 0:
                raise ValueError(f"{field}는 0 이상이어야 합니다.")
    if data.get("finish_reason") is not None and not isinstance(
        data["finish_reason"], str
    ):
        raise TypeError("finish_reason은 문자열 또는 None이어야 합니다.")

    return GenerationResult(
        status=GenerationStatus(status),
        raw_text=raw_text,
        answer=answer,
        input_tokens=data.get("input_tokens"),
        output_tokens=data.get("output_tokens"),
        finish_reason=data.get("finish_reason"),
        refusal=refusal,
    )


def run_from_dict(data: dict[str, object]) -> GenerationRun:
    if not isinstance(data, dict):
        raise TypeError("실행 기록은 객체여야 합니다.")
    for field in ("case_id", "config", "result", "elapsed_seconds", "error_type"):
        if field not in data:
            raise ValueError(f"실행 기록에 {field} 필드가 없습니다.")

    case_id = data["case_id"]
    config_data = data["config"]
    result_data = data["result"]
    elapsed_seconds = data["elapsed_seconds"]
    error_type = data["error_type"]

    if not isinstance(case_id, str):
        raise TypeError("case_id는 문자열이어야 합니다.")

    if not isinstance(config_data, dict):
        raise TypeError("config는 객체여야 합니다.")

    if result_data is not None and not isinstance(result_data, dict):
        raise TypeError("result는 객체 또는 None이어야 합니다.")

    if isinstance(elapsed_seconds, bool) or not isinstance(
        elapsed_seconds, (int, float)
    ):
        raise TypeError("elapsed_seconds는 숫자여야 합니다.")

    if error_type is not None and not isinstance(error_type, str):
        raise TypeError("error_type은 문자열 또는 None이어야 합니다.")

    return GenerationRun(
        case_id=case_id,
        config=config_from_dict(config_data),
        result=result_from_dict(result_data),
        elapsed_seconds=elapsed_seconds,
        error_type=error_type,
        documents_sha256=data.get("documents_sha256"),
        document_count=data.get("document_count"),
        prompt_sha256=data.get("prompt_sha256"),
        prompt_profile=data.get("prompt_profile"),
    )
