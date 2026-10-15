"""Budgeted, resumable development and final-selection experiments."""

import argparse
import fcntl
import hashlib
import json
import os
import signal
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from langchain_ollama import ChatOllama

from generation.documents import load_documents
from generation.profiles import build_profile_prompt
from generation.providers import (
    build_openai_model,
    invoke_model,
    invoke_openai_message,
    to_messages,
)
from generation_evaluation.strategies import execute_strategy
from generation_evaluation.budget import (
    BudgetExceeded,
    BudgetLedger,
    actual_cost,
    reserve_cost,
)
from generation_evaluation.reporting import config_from_dict

DEFAULT_BUDGET_LIMITS = {
    "total_dollars": 5.0,
    "dev_dollars": 3.0,
    "total_seconds": 7200.0,
    "dev_seconds": 4200.0,
}
FOLLOWUP_MAX_CALLS = 166
MANIFEST_SOURCE_PATHS = (
    "generation/prompts.py",
    "generation/providers.py",
    "generation/service.py",
    "generation/config.py",
    "generation/types.py",
    "generation/validation.py",
    "generation/profiles.py",
    "generation_evaluation/strategies.py",
    "generation/output_schema.py",
    "generation_evaluation/selection.py",
    "generation_evaluation/budget.py",
    "generation_evaluation/types.py",
    "generation_evaluation/reporting.py",
    "generation_evaluation/metrics.py",
    "uv.lock",
)


def _budget_limits(args):
    if getattr(args, "unlimited_budget", False):
        explicit_caps = [getattr(args, name, None) for name in DEFAULT_BUDGET_LIMITS]
        if any(value is not None for value in explicit_caps):
            raise ValueError(
                "--unlimited-budget과 개별 금액·시간 한도는 함께 사용할 수 없습니다."
            )
        limits = dict.fromkeys(DEFAULT_BUDGET_LIMITS)
    else:
        limits = {
            name: (
                getattr(args, name, None)
                if getattr(args, name, None) is not None
                else default
            )
            for name, default in DEFAULT_BUDGET_LIMITS.items()
        }
    limits["max_calls"] = getattr(args, "max_calls", None)
    return limits


def _budget_ledger(args):
    return BudgetLedger(args.ledger, **_budget_limits(args))


def _sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_code_hashes():
    return {
        name: _sha256_file(Path(name)) if Path(name).is_file() else None
        for name in MANIFEST_SOURCE_PATHS
    }


def _validate_cases(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases는 하나 이상의 평가 문항 목록이어야 합니다.")
    case_ids = []
    for case in cases:
        if not isinstance(case, dict):
            raise TypeError("각 평가 문항은 JSON 객체여야 합니다.")
        case_id = case.get("case_id")
        question = case.get("question")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("모든 평가 문항에는 비어 있지 않은 case_id가 필요합니다.")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{case_id}의 question이 비어 있습니다.")
        case_ids.append(case_id)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Duplicate case_id")
    return set(case_ids)


def _validate_rubric(path, cases, *, required):
    if path is None:
        if required:
            raise ValueError("이 후보에는 --rubric이 필요합니다.")
        return None

    try:
        raw = path.read_bytes()
        rubric = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("rubric 파일을 읽을 수 없거나 JSON 형식이 아닙니다.") from exc
    if not isinstance(rubric, dict) or not rubric:
        raise ValueError("rubric은 비어 있지 않은 JSON 객체여야 합니다.")
    if "response_contract" in rubric and not isinstance(
        rubric["response_contract"], dict
    ):
        raise ValueError("rubric.response_contract는 JSON 객체여야 합니다.")
    if "dimensions" in rubric and not isinstance(rubric["dimensions"], list):
        raise ValueError("rubric.dimensions는 목록이어야 합니다.")

    requested_ids = {case["case_id"] for case in cases}
    declared_ids = rubric.get("case_ids")
    rubric_cases = rubric.get("cases")
    if declared_ids is None:
        if isinstance(rubric_cases, dict):
            declared_ids = list(rubric_cases)
        elif isinstance(rubric_cases, list):
            declared_ids = [
                item["case_id"]
                for item in rubric_cases
                if isinstance(item, dict) and isinstance(item.get("case_id"), str)
            ]
    if declared_ids is not None:
        if (
            not isinstance(declared_ids, list)
            or any(
                not isinstance(item, str) or not item.strip() for item in declared_ids
            )
            or len(declared_ids) != len(set(declared_ids))
        ):
            raise ValueError("rubric.case_ids는 중복 없는 문자열 목록이어야 합니다.")
        missing_ids = requested_ids - set(declared_ids)
        if missing_ids:
            raise ValueError(
                "rubric에 평가 문항이 없습니다: " + ", ".join(sorted(missing_ids))
            )
    elif required:
        raise ValueError("후속 실험 rubric에는 case_ids가 필요합니다.")

    if rubric_cases is not None:
        if isinstance(rubric_cases, list):
            rubric_cases = {
                item.get("case_id"): item
                for item in rubric_cases
                if isinstance(item, dict) and isinstance(item.get("case_id"), str)
            }
        if not isinstance(rubric_cases, dict):
            raise ValueError("rubric.cases는 case_id를 키로 가진 객체여야 합니다.")
        if declared_ids is not None and set(rubric_cases) - set(declared_ids):
            raise ValueError("rubric.cases에 선언되지 않은 case_id가 있습니다.")
        for case in cases:
            details = rubric_cases.get(case["case_id"])
            if details is None:
                continue
            if not isinstance(details, dict):
                raise TypeError(
                    f"rubric.cases.{case['case_id']}는 JSON 객체여야 합니다."
                )
            if (
                "evidence" in details
                and "evidence" in case
                and details["evidence"] != case["evidence"]
            ):
                raise ValueError(
                    f"rubric와 평가 문항의 근거가 다릅니다: {case['case_id']}"
                )
    return hashlib.sha256(raw).hexdigest()


def _manifest_matches(stored, expected, budget_limits):
    stored_without_identity = dict(stored)
    stored_without_identity.pop("ledger_identity", None)
    expected_without_identity = dict(expected)
    expected_without_identity.pop("ledger_identity", None)
    if stored_without_identity == expected_without_identity:
        return True
    if (
        "budget_limits" not in stored_without_identity
        and budget_limits == DEFAULT_BUDGET_LIMITS
    ):
        stored_without_identity.pop("budget_limits", None)
        expected_without_identity.pop("budget_limits", None)
        return stored_without_identity == expected_without_identity
    return False


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def format_check(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(value, dict)
        and set(value) == {"answer"}
        and isinstance(value["answer"], str)
        and bool(value["answer"].strip())
    )


def append_record(path, record):
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        file.flush()

        os.fsync(file.fileno())


def read_records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def completed_keys(records):
    keys = [(r["case_id"], r["repeat"]) for r in records]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate completed case/repeat")
    return set(keys)


def _validate_prior_reservations(records, ledger, *, require_legacy_history=False):
    request_ids = []
    for record in records:
        calls = record.get("calls")
        if not isinstance(calls, list) or (require_legacy_history and not calls):
            raise ValueError(
                "Resume history does not contain verifiable prior reservations"
            )
        for call in calls:
            request_id = call.get("request_id") if isinstance(call, dict) else None
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError(
                    "Resume history does not contain verifiable prior reservations"
                )
            request_ids.append(request_id)

    if require_legacy_history and not request_ids:
        raise ValueError(
            "Resume history does not contain verifiable prior reservations"
        )
    known_ids = ledger.snapshot()["reservations"]
    if set(request_ids) - known_ids.keys():
        raise ValueError(
            "Resume ledger is missing prior reservations; use the original ledger"
        )


@contextmanager
def deadline(seconds):
    def expire(_signum, _frame):
        raise TimeoutError("Experiment call deadline exceeded")

    old = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def run(args):
    # Validate configured limits before creating any run files.
    ledger = _budget_ledger(args)
    candidates = json.loads(args.candidates.read_text())
    candidate = candidates[args.candidate]
    cases = json.loads(args.cases.read_text())
    documents = load_documents(args.documents)
    case_ids = _validate_cases(cases)
    requires_rubric = bool(candidate.get("requires_rubric", False))
    max_calls = getattr(args, "max_calls", None)
    if requires_rubric and max_calls != FOLLOWUP_MAX_CALLS:
        raise ValueError(
            f"후속 실험은 --max-calls {FOLLOWUP_MAX_CALLS}를 고정해야 합니다."
        )
    if requires_rubric and not getattr(args, "unlimited_budget", False):
        raise ValueError("후속 실험은 --unlimited-budget으로 실행해야 합니다.")
    rubric_sha256 = _validate_rubric(
        getattr(args, "rubric", None), cases, required=requires_rubric
    )
    profile = candidate.get("profile", "baseline")
    strategy = candidate.get("strategy", "single")
    # Validate the profile before creating files or making paid calls.
    build_profile_prompt(cases[0]["question"], documents, profile)
    if strategy not in ("single", "evidence_first"):
        raise ValueError("Unknown strategy")
    ledger.bind_limits()
    budget_limits = {
        "total_dollars": ledger.total_dollars,
        "dev_dollars": ledger.dev_dollars,
        "total_seconds": ledger.total_seconds,
        "dev_seconds": ledger.dev_seconds,
    }
    if ledger.max_calls is not None:
        budget_limits["max_calls"] = ledger.max_calls
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 2,
        "code_sha256": _manifest_code_hashes(),
        "candidate_id": args.candidate,
        "candidate": candidate,
        "phase": args.phase,
        "budget_limits": budget_limits,
        "repeats": args.repeats,
        "start_repeat": args.start_repeat,
        "cases_sha256": digest(cases),
        "case_ids": sorted(case_ids),
        "rubric_sha256": rubric_sha256,
        "documents_sha256": digest(documents),
        "document_count": len(documents),
    }
    manifest_path = args.output / "manifest.json"
    result_path = args.output / "runs.jsonl"
    events_path = args.output / "events.jsonl"
    result_records = read_records(result_path)
    event_records = read_records(events_path)
    done = completed_keys(result_records)
    begun = {(e["case_id"], e["repeat"]) for e in event_records}
    if begun - done:
        raise ValueError(
            "Uncertain interrupted requests require manual reconciliation; not rerunning"
        )
    if manifest_path.exists():
        stored_manifest = json.loads(manifest_path.read_text())
        if not isinstance(stored_manifest, dict):
            raise ValueError("Resume manifest differs; use a new run directory")
        stored_identity = stored_manifest.get("ledger_identity")
        if stored_identity is None:
            if not _manifest_matches(stored_manifest, manifest, budget_limits):
                raise ValueError("Resume manifest differs; use a new run directory")
            _validate_prior_reservations(
                result_records, ledger, require_legacy_history=True
            )
            ledger_identity = ledger.ensure_identity()
        else:
            if not _manifest_matches(stored_manifest, manifest, budget_limits):
                raise ValueError("Resume manifest differs; use a new run directory")
            if ledger.get_identity() != stored_identity:
                raise ValueError(
                    "Resume ledger identity differs; use the original ledger"
                )
            _validate_prior_reservations(result_records, ledger)
            ledger_identity = stored_identity
        manifest["ledger_identity"] = ledger_identity
        if (
            stored_manifest.get("ledger_identity") is None
            or "budget_limits" not in stored_manifest
        ):
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
            )
    else:
        if result_path.exists() or events_path.exists():
            raise ValueError(
                "Resume manifest is missing for existing run records; use a new run directory"
            )
        manifest["ledger_identity"] = ledger.ensure_identity()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
    provider = candidate["config"]["provider"]
    for repeat in range(args.start_repeat, args.start_repeat + args.repeats):
        for case in cases:
            key = (case["case_id"], repeat)
            if key in done:
                continue
            if ledger.remaining_seconds(args.phase) <= 0:
                raise BudgetExceeded("Time budget exhausted")
            append_record(
                events_path,
                {"case_id": key[0], "repeat": repeat, "started_at": time.time()},
            )
            calls = []
            prompt = build_profile_prompt(case["question"], documents, profile)
            record = {
                "case_id": key[0],
                "repeat": repeat,
                "question": case["question"],
                "candidate_id": args.candidate,
                "profile": profile,
                "strategy": strategy,
                "documents_sha256": manifest["documents_sha256"],
                "prompt_sha256": digest(asdict(prompt)),
                "config": candidate["config"],
                "result": None,
                "error_type": None,
                "document_count": len(documents),
            }

            def model_call(stage_prompt, key=key, repeat=repeat, calls=calls):
                request_id = f"{args.output.resolve()}:{key[0]}:{repeat}:{len(calls)}"
                messages = to_messages(stage_prompt)
                max_output = candidate["config"]["max_output_tokens"]
                bound = (
                    reserve_cost(messages, max_output) if provider == "openai" else 0.0
                )
                ledger.reserve(request_id, args.phase, bound)
                remaining = ledger.remaining_seconds(args.phase)
                if remaining <= 0:
                    ledger.settle(request_id, 0.0)
                    raise BudgetExceeded("Time budget exhausted before invocation")
                timeout = min(float(candidate["config"]["timeout_seconds"]), remaining)
                config = dict(candidate["config"], timeout_seconds=timeout)
                stage = {
                    "request_id": request_id,
                    "prompt_sha256": digest(asdict(stage_prompt)),
                    "reserved_dollars": bound,
                    "effective_config": config,
                }
                start = time.perf_counter()
                estimate = None
                try:
                    if provider == "openai":
                        model = build_openai_model(config_from_dict(config))
                    else:
                        model = ChatOllama(
                            base_url="http://127.0.0.1:11435",
                            model=config["model_name"],
                            num_ctx=config["context_window"],
                            num_predict=max_output,
                            temperature=config.get("temperature", 0),
                            seed=candidate.get("seed", 42),
                            keep_alive="30m",
                            client_kwargs={"timeout": timeout},
                        )

                    def invoke(messages):
                        if provider == "openai":
                            response = invoke_openai_message(
                                config_from_dict(config), model, messages
                            )
                        else:
                            response = model.invoke(messages)
                        stage.update(
                            raw_text=response.content,
                            usage=response.usage_metadata,
                            metadata=response.response_metadata,
                        )
                        additional_kwargs = getattr(response, "additional_kwargs", {})
                        if isinstance(additional_kwargs, dict):
                            refusal = additional_kwargs.get("refusal")
                            if refusal is not None:
                                stage["additional_kwargs"] = {"refusal": refusal}
                        return response

                    with deadline(timeout):
                        response = invoke_model(stage_prompt, invoke)
                    estimate = (
                        actual_cost(
                            stage.get("usage") or {}, stage.get("metadata") or {}
                        )
                        if provider == "openai"
                        else 0.0
                    )
                    stage["response"] = asdict(response)
                    return response
                except Exception as exc:
                    stage.update(
                        error_type=type(exc).__name__,
                        status_code=getattr(exc, "status_code", None),
                    )
                    raise
                finally:
                    stage["elapsed_seconds"] = time.perf_counter() - start
                    stage["estimated_dollars"] = estimate
                    ledger.settle(request_id, estimate if provider == "openai" else 0.0)
                    calls.append(stage)

            start = time.perf_counter()
            stop = False
            try:
                outcome = execute_strategy(
                    case["question"],
                    documents,
                    model_call,
                    profile=profile,
                    strategy=strategy,
                )
                record.update(
                    result=asdict(outcome["result"]), stages=outcome["stages"]
                )
                record["format_pass"] = format_check(outcome["result"].raw_text)
            except Exception as exc:  # noqa: BLE001 - persist provider failure without secrets
                record.update(error_type=type(exc).__name__, format_pass=False)
                stop = isinstance(exc, BudgetExceeded) or getattr(
                    exc, "status_code", None
                ) in (401, 403, 429)
            record.update(elapsed_seconds=time.perf_counter() - start, calls=calls)
            append_record(result_path, record)
            done.add(key)
            print(
                json.dumps(
                    {
                        "candidate": args.candidate,
                        "case_id": key[0],
                        "repeat": repeat,
                        "status": (record.get("result") or {}).get(
                            "status", record.get("error_type")
                        ),
                        "seconds": record["elapsed_seconds"],
                    }
                ),
                flush=True,
            )
            if stop:
                return 2
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--phase", choices=["dev", "final"], required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--start-repeat", type=int, default=1)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--unlimited-budget", action="store_true")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--total-dollars", type=float)
    parser.add_argument("--dev-dollars", type=float)
    parser.add_argument("--total-seconds", type=float)
    parser.add_argument("--dev-seconds", type=float)
    args = parser.parse_args()
    if args.repeats < 1 or args.start_repeat < 1:
        parser.error("repeats must be positive")
    try:
        _budget_ledger(args)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
