"""Bounded, non-retrying experiment; run from repository root with PYTHONPATH=."""

import argparse
import hashlib
import json
from pathlib import Path

from dotenv import load_dotenv

from generation.documents import render_document
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.providers import build_managed_model_call, to_messages
from generation_evaluation.budget import BudgetLedger, actual_cost, reserve_cost
from generation_evaluation.reporting import run_to_dict
from generation_evaluation.runner import run_case

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def render(rows):
    return [
        render_document(
            row["document_id"],
            row["title"],
            row["document"],
            row.get("revision_number", 1),
        )
        for row in rows
    ]


def ledger_at(output):
    ledger = BudgetLedger(
        output / "ledger.json",
        total_dollars=5,
        dev_dollars=5,
        total_seconds=None,
        dev_seconds=None,
        max_calls=90,
    )
    ledger.bind_limits()
    return ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.env_file)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings(ROOT)
    corpus_path = ROOT / "data/company-knowledge/documents.jsonl"
    assert (
        digest(corpus_path.read_bytes())
        == "84b44e6592e3a6bd883b7890239aada11382cbef9a369ebb0aca3b15defddfe4"
    )
    corpus = render([json.loads(line) for line in corpus_path.read_text().splitlines()])
    regression_path = (
        ROOT / "generation_evaluation/benchmarks/luna-reference-followup-v1/dev.json"
    )
    jobs = []
    profiles = ["examples_answer_scope_v1", "examples_answer_scope_v2"]
    for case in json.loads((HERE / "cases.json").read_text()):
        for repeat in (1, 2):
            for profile in profiles:
                jobs.append(("new", case, render(case["documents"]), repeat, profile))
    for case in json.loads(regression_path.read_text()):
        for profile in profiles:
            jobs.append(("regression", case, corpus, 1, profile))
    for case in json.loads((HERE / "holdout.json").read_text()):
        for repeat in (1, 2):
            jobs.append(
                ("holdout", case, render(case["documents"]), repeat, profiles[1])
            )
    files = [
        HERE / n for n in ("cases.json", "holdout.json", "criteria.json", "run.py")
    ]
    files += [
        ROOT / "generation/profiles.py",
        ROOT / "generation/prompts.py",
        ROOT / "generation/models.json",
        ROOT / "uv.lock",
        corpus_path,
        regression_path,
    ]
    manifest = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in files}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("Input/code drift: refusing resume")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    ledger = ledger_at(output)
    client = build_managed_model_call(settings.config)
    for phase, case, documents, repeat, profile in jobs:
        request_id = f"{phase}-{case['case_id']}-{profile}-r{repeat}"
        target = output / f"{request_id}.json"
        if target.exists():
            continue  # includes failures, never retry saved attempts
        prompt = build_profile_prompt(case["question"], documents, profile)
        ledger.reserve(
            request_id,
            "final",
            reserve_cost(to_messages(prompt), settings.config.max_output_tokens),
        )
        run = run_case(
            case["case_id"],
            settings.config,
            case["question"],
            documents,
            client,
            prompt_profile=profile,
        )
        record = run_to_dict(run)
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
        record.update(
            phase=phase,
            repeat=repeat,
            question=case["question"],
            estimated_dollars=cost,
        )
        with target.open("x") as file:
            file.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(request_id, result.status.value if result else run.error_type, flush=True)


if __name__ == "__main__":
    main()
