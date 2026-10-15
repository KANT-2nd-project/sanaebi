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
from generation.providers import build_openai_model, invoke_model, to_messages
from generation.strategies import execute_strategy
from generation_evaluation.budget import (
    BudgetExceeded,
    BudgetLedger,
    actual_cost,
    reserve_cost,
)
from generation_evaluation.reporting import config_from_dict


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
    candidates = json.loads(args.candidates.read_text())
    candidate = candidates[args.candidate]
    cases = json.loads(args.cases.read_text())
    documents = load_documents(args.documents)
    profile = candidate.get("profile", "baseline")
    strategy = candidate.get("strategy", "single")
    # Validate the profile before creating files or making paid calls.
    build_profile_prompt(cases[0]["question"], documents, profile)
    if strategy not in ("single", "evidence_first"):
        raise ValueError("Unknown strategy")
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case_id")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "code_sha256": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in (
                "generation/prompts.py",
                "generation/providers.py",
                "generation/service.py",
                "generation_evaluation/selection.py",
                "generation_evaluation/budget.py",
            )
        },
        "candidate_id": args.candidate,
        "candidate": candidate,
        "phase": args.phase,
        "repeats": args.repeats,
        "start_repeat": args.start_repeat,
        "cases_sha256": digest(cases),
        "documents_sha256": digest(documents),
        "document_count": len(documents),
        "profile_code_sha256": hashlib.sha256(
            Path("generation/profiles.py").read_bytes()
        ).hexdigest(),
        "strategy_code_sha256": hashlib.sha256(
            Path("generation/strategies.py").read_bytes()
        ).hexdigest(),
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
    ledger = BudgetLedger(args.ledger)
    if manifest_path.exists():
        stored_manifest = json.loads(manifest_path.read_text())
        if not isinstance(stored_manifest, dict):
            raise ValueError("Resume manifest differs; use a new run directory")
        stored_identity = stored_manifest.get("ledger_identity")
        if stored_identity is None:
            if stored_manifest != manifest:
                raise ValueError("Resume manifest differs; use a new run directory")
            _validate_prior_reservations(
                result_records, ledger, require_legacy_history=True
            )
            ledger_identity = ledger.ensure_identity()
        else:
            current_manifest = dict(stored_manifest)
            del current_manifest["ledger_identity"]
            if current_manifest != manifest:
                raise ValueError("Resume manifest differs; use a new run directory")
            if ledger.get_identity() != stored_identity:
                raise ValueError(
                    "Resume ledger identity differs; use the original ledger"
                )
            _validate_prior_reservations(result_records, ledger)
            ledger_identity = stored_identity
        manifest["ledger_identity"] = ledger_identity
        if stored_manifest.get("ledger_identity") is None:
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
                        response = model.invoke(messages)
                        stage.update(
                            raw_text=response.content,
                            usage=response.usage_metadata,
                            metadata=response.response_metadata,
                        )
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
    args = parser.parse_args()
    if args.repeats < 1 or args.start_repeat < 1:
        parser.error("repeats must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
