"""Run one fixed, sequential v5/v6 readability comparison (maximum 16 calls)."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from generation.documents import render_document
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.providers import build_managed_model_call
from generation_evaluation.reporting import run_to_dict
from generation_evaluation.runner import run_case

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PROFILES = ("examples_answer_scope_v5", "examples_answer_scope_v6")
MAX_CALLS = 16
INPUT_USD_PER_MILLION = 0.25
OUTPUT_USD_PER_MILLION = 0.75
INPUT_OVERHEAD_TOKENS = 512


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def load_snapshot(path: Path) -> tuple[dict, list[str]]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    required = {"fingerprint", "documents", "document_count"}
    if not isinstance(snapshot, dict) or not required.issubset(snapshot):
        raise ValueError(
            "Snapshot에 fingerprint, document_count, documents가 필요합니다."
        )
    rows = snapshot["documents"]
    if (
        not isinstance(rows, list)
        or not rows
        or len(rows) != snapshot["document_count"]
    ):
        raise ValueError("Snapshot 문서 수가 비었거나 document_count와 다릅니다.")

    entries = []
    rendered = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Snapshot 문서는 객체여야 합니다.")
        for field in ("id", "revision_id", "title", "body", "content_hash"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Snapshot 문서의 {field} 값이 잘못되었습니다.")
        revision = row.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("Snapshot 문서 revision은 1 이상의 정수여야 합니다.")
        if digest_bytes(row["body"].encode("utf-8")) != row["content_hash"]:
            raise ValueError(f"Snapshot 본문 해시가 맞지 않습니다: {row['id']}")
        entries.append(
            (row["id"], row["revision_id"], row["title"], row["content_hash"])
        )
        rendered.append(render_document(row["id"], row["title"], row["body"], revision))

    expected_fingerprint = digest_bytes(
        json.dumps(entries, ensure_ascii=False).encode("utf-8")
    )
    if expected_fingerprint != snapshot["fingerprint"]:
        raise ValueError("Snapshot fingerprint와 문서 내용이 일치하지 않습니다.")
    return snapshot, rendered


def load_cases() -> list[dict]:
    data = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or len(cases) != 8:
        raise ValueError("고정 cases.json에는 8개 문항이 있어야 합니다.")
    if len({case.get("id") for case in cases}) != len(cases):
        raise ValueError("문항 ID가 중복되었습니다.")
    if len(PROFILES) * len(cases) != MAX_CALLS:
        raise ValueError("프로필·문항 수가 고정 최대 호출 수와 맞지 않습니다.")
    return cases


def ordered_slots(cases: list[dict]) -> list[tuple[dict, str]]:
    slots = []
    for index, case in enumerate(cases):
        profiles = PROFILES if index % 2 == 0 else PROFILES[::-1]
        slots.extend((case, profile) for profile in profiles)
    return slots


def cost_bound(input_bytes: int, max_output_tokens: int) -> tuple[int, float]:
    input_token_reservation = input_bytes + INPUT_OVERHEAD_TOKENS
    estimate = (
        input_token_reservation * INPUT_USD_PER_MILLION
        + max_output_tokens * OUTPUT_USD_PER_MILLION
    ) / 1_000_000
    return input_token_reservation, estimate


def prepare(
    root: Path, snapshot_path: Path
) -> tuple[dict, list[dict], list[str], object]:
    snapshot, documents = load_snapshot(snapshot_path)
    cases = load_cases()
    settings = load_runtime_settings(root)
    config = settings.config
    expected = {
        "model_name": "gpt-6-luna",
        "reasoning_effort": "xhigh",
        "max_output_tokens": 16384,
        "timeout_seconds": 180,
        "temperature": None,
        "output_mode": "prompt_json",
    }
    actual = {
        "model_name": config.model_name,
        "reasoning_effort": config.reasoning_effort,
        "max_output_tokens": config.max_output_tokens,
        "timeout_seconds": config.timeout_seconds,
        "temperature": config.temperature,
        "output_mode": config.output_mode.value,
    }
    if actual != expected:
        raise ValueError(f"모델 설정이 고정 실험 설정과 다릅니다: {actual}")

    for profile in PROFILES:
        build_profile_prompt("설정 검사", [], profile)
    return snapshot, cases, documents, settings


def build_manifest(
    snapshot_path: Path,
    snapshot: dict,
    cases: list[dict],
    documents: list[str],
    settings,
) -> tuple[dict, list[tuple[dict, str, str, float]]]:
    slots = []
    prompt_hashes = {}
    reserved_total = 0.0
    for case, profile in ordered_slots(cases):
        prompt = build_profile_prompt(case["question"], documents, profile)
        prompt_bytes = json.dumps(
            {"system": prompt.system, "user": prompt.user},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        prompt_hash = digest_bytes(prompt_bytes)
        _input_tokens, reserved_usd = cost_bound(
            len(prompt_bytes), settings.config.max_output_tokens
        )
        slot = f"{case['id']}:{profile}"
        prompt_hashes[slot] = prompt_hash
        slots.append((case, profile, prompt_hash, reserved_usd))
        reserved_total += reserved_usd

    source_paths = (
        "generation/profiles.py",
        "generation/prompts.py",
        "generation/documents.py",
        "generation/service.py",
        "generation/validation.py",
        "generation/providers.py",
        "generation/presets.py",
        "generation/models.json",
        "generation/experiments.json",
        "generation_evaluation/runner.py",
        "generation_evaluation/reporting.py",
        "uv.lock",
    )
    config = settings.config
    manifest = {
        "experiment_id": "readability-v6-20261015",
        "maximum_generation_attempts": MAX_CALLS,
        "profiles": list(PROFILES),
        "model_configuration": {
            "provider": config.provider.value,
            "model_name": config.model_name,
            "reasoning_effort": config.reasoning_effort,
            "max_output_tokens": config.max_output_tokens,
            "timeout_seconds": config.timeout_seconds,
            "temperature": config.temperature,
            "output_mode": config.output_mode.value,
        },
        "case_count": len(cases),
        "run_order": "Sequential; alternate v5/v6 order within each case.",
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": digest_file(snapshot_path),
        "snapshot_fingerprint": snapshot["fingerprint"],
        "snapshot_document_count": snapshot["document_count"],
        "snapshot_source": {
            key: snapshot[key]
            for key in (
                "captured_at_utc",
                "source_database",
                "source_database_sha256_before",
                "source_database_wal_sha256_before",
            )
            if key in snapshot
        },
        "cases_sha256": digest_file(HERE / "cases.json"),
        "code_sha256": {name: digest_file(ROOT / name) for name in source_paths},
        "runner_sha256": digest_file(Path(__file__)),
        "slot_prompt_sha256": prompt_hashes,
        "pricing_source": "https://developers.openai.com/api/docs/pricing",
        "pricing_checked_on": "2026-10-15",
        "pricing_method": "Conservative Standard long-context cache-write input upper bound $0.25/M (normal input is $0.20/M) and output $0.75/M; no cache discount; estimates are not invoices. Input reservation uses UTF-8 prompt bytes plus 512 tokens as a conservative estimate, not a tokenizer-proven ceiling.",
        "reserved_upper_usd": reserved_total,
        "usage_missing_cost_rule": "If either input or output usage is absent, record the full slot reservation instead of zero.",
        "retry_or_resume": False,
        "rubric_sent_to_model": False,
        "scope": "Generation run_case with one frozen published SQLite snapshot; no HTTP, classifier, browser, retries, or resume.",
    }
    return manifest, slots


def fsync_jsonl(file, item: dict) -> None:
    file.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
    file.flush()
    os.fsync(file.fileno())


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate hashes/settings and estimate the fixed 16-call ceiling without creating a client or calling the API.",
    )
    args = parser.parse_args()

    snapshot, cases, documents, settings = prepare(ROOT, args.snapshot)
    manifest, slots = build_manifest(
        args.snapshot, snapshot, cases, documents, settings
    )
    if len(slots) != MAX_CALLS:
        raise ValueError("계산된 요청 슬롯이 16개가 아닙니다.")
    if args.preflight_only:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for profile in PROFILES:
        prompt = build_profile_prompt("설정 검사", [], profile)
        (args.output / f"{profile}.txt").write_text(prompt.system, encoding="utf-8")

    client = build_managed_model_call(settings.config)
    try:
        with (
            (args.output / "events.jsonl").open("x", encoding="utf-8") as events,
            (args.output / "responses.jsonl").open("x", encoding="utf-8") as output,
        ):
            fsync_jsonl(
                events,
                {
                    "event": "run_started",
                    "maximum_generation_attempts": MAX_CALLS,
                    "reserved_upper_usd": manifest["reserved_upper_usd"],
                },
            )
            for attempt, (
                case,
                profile,
                expected_prompt_hash,
                reserved_usd,
            ) in enumerate(slots, start=1):
                slot = f"{case['id']}:{profile}"
                fsync_jsonl(
                    events,
                    {
                        "slot": slot,
                        "attempt": attempt,
                        "event": "started",
                        "reserved_usd": reserved_usd,
                    },
                )
                run = run_case(
                    case["id"],
                    settings.config,
                    case["question"],
                    documents,
                    client,
                    prompt_profile=profile,
                )
                record = run_to_dict(run)
                record.update(
                    {
                        "experiment_id": manifest["experiment_id"],
                        "question": case["question"],
                        "category": case["category"],
                        "slot": slot,
                        "attempt": attempt,
                        "expected_prompt_sha256": expected_prompt_hash,
                        "prompt_hash_matches_manifest": (
                            run.prompt_sha256 == expected_prompt_hash
                        ),
                    }
                )
                result = run.result
                usage_known = (
                    result is not None
                    and result.input_tokens is not None
                    and result.output_tokens is not None
                )
                record["usage_known"] = usage_known
                record["reserved_usd"] = reserved_usd
                record["cost_upper_usd"] = (
                    (
                        result.input_tokens * INPUT_USD_PER_MILLION
                        + result.output_tokens * OUTPUT_USD_PER_MILLION
                    )
                    / 1_000_000
                    if usage_known
                    else reserved_usd
                )
                fsync_jsonl(output, record)
                fsync_jsonl(
                    events,
                    {
                        "slot": slot,
                        "attempt": attempt,
                        "event": "finished",
                        "status": (
                            result.status.value
                            if result is not None
                            else run.error_type
                        ),
                        "usage_known": usage_known,
                        "cost_upper_usd": record["cost_upper_usd"],
                    },
                )
                print(
                    slot,
                    record["result"]["status"] if result else run.error_type,
                    flush=True,
                )
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
