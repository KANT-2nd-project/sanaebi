"""Staged minimal-prompt comparison; no retries or automatic promotion."""

import argparse
import asyncio
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from generation.config import GenerationOutputMode
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.providers import build_managed_model_call, to_messages
from generation_evaluation.budget import actual_cost, reserve_cost
from generation_evaluation.reporting import run_to_dict
from generation_evaluation.runner import run_case

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = HERE.parent / "answer-grounding-20261015"
spec = importlib.util.spec_from_file_location("previous_experiment", OLD / "run.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["focus", "strict", "broad"], required=True)
    parser.add_argument(
        "--mode", choices=["prompt_json", "strict_json_schema"], default="prompt_json"
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "focus" and args.mode != "prompt_json":
        parser.error("focus compares prompt_json only")
    if args.stage == "strict" and args.mode != "strict_json_schema":
        parser.error("strict requires strict_json_schema")
    load_dotenv(args.env_file)
    args.output.mkdir(parents=True, exist_ok=True)
    config = load_runtime_settings(ROOT).config
    corpus_path = ROOT / "data/company-knowledge/documents.jsonl"
    assert (
        helpers.digest(corpus_path.read_bytes())
        == "84b44e6592e3a6bd883b7890239aada11382cbef9a369ebb0aca3b15defddfe4"
    )
    corpus = helpers.render(
        [json.loads(line) for line in corpus_path.read_text().splitlines()]
    )
    regression_path = (
        ROOT / "generation_evaluation/benchmarks/luna-reference-followup-v1/dev.json"
    )
    regression = json.loads(regression_path.read_text())
    new = json.loads((OLD / "cases.json").read_text())
    variants = json.loads((OLD / "holdout.json").read_text())
    cases = {c["case_id"]: c for c in [*regression, *new, *variants]}
    protocol = json.loads((HERE / "protocol.json").read_text())
    baseline, candidate = protocol["baseline"], protocol["candidate"]

    def documents(case):
        return helpers.render(case["documents"]) if "documents" in case else corpus

    jobs = []
    if args.stage in ("focus", "strict"):
        for cid in protocol["focus"]:
            for repeat in (1, 2):
                profiles = (
                    [baseline, candidate] if args.stage == "focus" else [candidate]
                )
                for profile in profiles:
                    jobs.append((cases[cid], repeat, profile, args.mode))
    else:
        for case in regression:
            jobs.extend(
                [(case, 1, baseline, "prompt_json"), (case, 1, candidate, args.mode)]
            )
        for case in new:
            if case["case_id"] not in ["G02", "G04", "G09", "G11"]:
                jobs.extend((case, repeat, candidate, args.mode) for repeat in (1, 2))
        for case in variants:
            jobs.extend((case, repeat, candidate, args.mode) for repeat in (1, 2))
    files = [
        HERE / "run.py",
        HERE / "protocol.json",
        OLD / "cases.json",
        OLD / "holdout.json",
        OLD / "run.py",
        ROOT / "generation/profiles.py",
        ROOT / "generation/prompts.py",
        ROOT / "generation/models.json",
        ROOT / "uv.lock",
        corpus_path,
        regression_path,
    ]
    manifest = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }
    manifest_path = args.output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("Refusing changed inputs/code")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    ledger = helpers.ledger_at(args.output)
    clients = {}
    try:
        for case, repeat, profile, mode in jobs:
            request_id = f"{args.stage}-{case['case_id']}-{profile}-{mode}-r{repeat}"
            target = args.output / f"{request_id}.json"
            if target.exists():
                continue
            chosen = replace(config, output_mode=GenerationOutputMode(mode))
            if mode not in clients:
                clients[mode] = build_managed_model_call(chosen)
            docs = documents(case)
            prompt = build_profile_prompt(case["question"], docs, profile)
            ledger.reserve(
                request_id,
                "final",
                reserve_cost(to_messages(prompt), chosen.max_output_tokens),
            )
            run = run_case(
                case["case_id"],
                chosen,
                case["question"],
                docs,
                clients[mode],
                prompt_profile=profile,
            )
            result = run.result
            cost = (
                actual_cost(
                    {
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                    },
                    {},
                )
                if result
                else None
            )
            ledger.settle(request_id, cost)
            record = run_to_dict(run)
            record.update(
                phase=args.stage,
                repeat=repeat,
                question=case["question"],
                estimated_dollars=cost,
            )
            with target.open("x") as file:
                file.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            print(
                request_id,
                result.status.value if result else run.error_type,
                flush=True,
            )
    finally:

        async def close():
            for client in clients.values():
                await client.aclose()

        asyncio.run(close())


if __name__ == "__main__":
    main()
