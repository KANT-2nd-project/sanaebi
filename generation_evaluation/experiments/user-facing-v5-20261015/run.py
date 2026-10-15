"""Fixed 13-question v5 verification; exclusive output and no retries/resume."""

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
PROFILES = ("examples_answer_scope_v5",)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    assert len(cases) == 13
    snapshot = json.loads(args.snapshot.read_text())
    documents = [
        render_document(d["id"], d["title"], d["body"], d["revision"])
        for d in snapshot["documents"]
    ]
    assert documents
    config = load_runtime_settings(ROOT).config
    assert config.model_name == "gpt-6-luna"
    assert config.max_output_tokens == 16384
    assert config.reasoning_effort == "xhigh" and config.timeout_seconds == 180
    assert config.temperature is None and config.output_mode.value == "prompt_json"
    slots = [
        (case, profile)
        for index, case in enumerate(cases)
        for profile in (PROFILES if index % 2 == 0 else PROFILES[::-1])
    ]

    def case_documents(case):
        overlay = case.get("snapshot_overlay")
        if overlay is None:
            return documents
        return documents + [
            render_document(
                overlay["id"], overlay["title"], overlay["body"], overlay["revision"]
            )
        ]

    bounds = []
    for case, profile in slots:
        p = build_profile_prompt(case["question"], case_documents(case), profile)
        token_upper = len((p.system + p.user).encode()) + 512
        bounds.append((token_upper * 0.25 + config.max_output_tokens * 0.75) / 1e6)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "max_calls": 13,
        "profiles": PROFILES,
        "snapshot_sha256": digest(args.snapshot),
        "snapshot_fingerprint": snapshot["fingerprint"],
        "document_count": len(documents),
        "cases_sha256": digest(HERE / "cases.json"),
        "code_sha256": {
            name: digest(ROOT / name)
            for name in (
                "generation/profiles.py",
                "generation/prompts.py",
                "generation/providers.py",
                "generation/service.py",
                "generation/validation.py",
                "generation/models.json",
                "uv.lock",
            )
        },
        "runner_sha256": digest(Path(__file__)),
        "pricing_source": "https://developers.openai.com/api/docs/pricing",
        "pricing_checked_on": "2026-10-15",
        "pricing_method": "Conservative Standard long-context cache-write input 0.25/M, output 0.75/M; no cache discount; not an invoice.",
        "reserved_upper_usd": sum(bounds),
        "scope": "generate_from_documents via run_case; frozen published snapshot; no HTTP/classifier/browser; sequential, no retries.",
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    for profile in PROFILES:
        (args.output / (profile + ".txt")).write_text(
            build_profile_prompt("질문", [], profile).system
        )
    client = build_managed_model_call(config)
    try:
        with (args.output / "events.jsonl").open("x") as events:
            for (case, profile), bound in zip(slots, bounds, strict=True):
                slot = f"{case['id']}:{profile}"
                events.write(
                    json.dumps(
                        {"slot": slot, "event": "started", "reserved_usd": bound}
                    )
                    + "\n"
                )
                events.flush()
                os.fsync(events.fileno())
                run = run_case(
                    case["id"],
                    config,
                    case["question"],
                    case_documents(case),
                    client,
                    prompt_profile=profile,
                )
                record = run_to_dict(run)
                record["question"] = case["question"]
                record["slot"] = slot
                result = run.result
                known = (
                    result is not None
                    and result.input_tokens is not None
                    and result.output_tokens is not None
                )
                record["usage_known"] = known
                record["cost_upper_usd"] = (
                    (result.input_tokens * 0.25 + result.output_tokens * 0.75) / 1e6
                    if known
                    else bound
                )
                with (args.output / "responses.jsonl").open("a") as output:
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                events.write(json.dumps({"slot": slot, "event": "finished"}) + "\n")
                events.flush()
                os.fsync(events.fileno())
                print(
                    slot, result.status.value if result else run.error_type, flush=True
                )
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
