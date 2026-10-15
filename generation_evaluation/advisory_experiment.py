"""Frozen, bounded A/B/C/W comparison. No production DB or historical imports."""

import argparse
import asyncio
import fcntl
import json
import os
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from generation.advisory import LABELS, ClassificationContext, compose_advisory
from generation.config import config_from_dict
from generation.documents import render_document
from generation.presets import load_runtime_settings
from generation.profiles import build_profile_prompt
from generation.providers import build_managed_model_call, to_messages
from generation.service import generate
from generation_evaluation.budget import BudgetExceeded, BudgetLedger, reserve_cost
from generation_evaluation.experiment_support import digest

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ROOT
    / "generation_evaluation/experiments/classification-advisory-20261015/cases.json"
)
CODE = (
    "generation/advisory.py",
    "generation/prompts.py",
    "generation/profiles.py",
    "generation/providers.py",
    "generation/optional_providers.py",
    "generation/service.py",
    "generation/types.py",
    "generation/validation.py",
    "generation/config.py",
    "generation/presets.py",
    "generation/models.json",
    "generation/experiments.json",
    "generation/output_schema.py",
    "contracts/classification.py",
    "generation_evaluation/advisory_experiment.py",
    "generation_evaluation/budget.py",
    "generation_evaluation/experiment_support.py",
    "app/classification/predictor.py",
    "app/classification/errors.py",
    "uv.lock",
)
LIMITS = {
    "total_dollars": 5.0,
    "dev_dollars": 5.0,
    "total_seconds": 7200.0,
    "dev_seconds": 7200.0,
    "max_calls": 184,
}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def append_json(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_records(output):
    path = output / "responses.jsonl"
    rows = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    result = {row["slot"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate response slot")
    return result


def code_hashes():
    import hashlib

    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE
    }


def documents_for(case, base):
    rows = {row["document_id"]: dict(row) for row in base}
    for row in case.get("replace", []):
        if row["document_id"] not in rows:
            raise ValueError("Replacement document is missing")
        rows[row["document_id"]] = row
    for row in case.get("overlays", []):
        if row["document_id"] in rows:
            raise ValueError("Overlay overwrites an existing document")
        rows[row["document_id"]] = row
    return [
        render_document(
            r["document_id"], r["title"], r["document"], r.get("revision", 1)
        )
        for r in rows.values()
    ]


def validate_corpus(corpus):
    ids = set()
    for phase, count in (("pilot", 8), ("confirmation", 20)):
        cases = corpus[phase]
        if len(cases) != count:
            raise ValueError("Unexpected case count")
        for case in cases:
            if (
                case["id"] in ids
                or not case["question"].strip()
                or not case["required"]
            ):
                raise ValueError("Invalid or duplicate case")
            ids.add(case["id"])
    if sum(bool(c.get("stress")) for c in corpus["pilot"]) != 4:
        raise ValueError("Expected four stress cases")


def make_slots(corpus, labels):
    slots = []
    for phase in ("pilot", "confirmation"):
        for i, case in enumerate(corpus[phase]):
            for repeat in (1, 2):
                arms = ["A", "B", "C"]
                shift = i % 3
                arms = arms[shift:] + arms[:shift]
                if repeat == 2:
                    arms.reverse()
                for arm in arms:
                    slots.append(
                        {
                            "slot": f"{case['id']}:{arm}:{repeat}",
                            "case_id": case["id"],
                            "phase": phase,
                            "arm": arm,
                            "repeat": repeat,
                            "label": labels[case["id"]]["label"],
                        }
                    )
        if phase == "pilot":
            for case in corpus[phase]:
                if not case.get("stress"):
                    continue
                for label in LABELS:
                    if label != labels[case["id"]]["label"]:
                        for repeat in (1, 2):
                            slots.append(
                                {
                                    "slot": f"{case['id']}:W:{label}:{repeat}",
                                    "case_id": case["id"],
                                    "phase": "pilot",
                                    "arm": "W",
                                    "repeat": repeat,
                                    "label": label,
                                }
                            )
    return slots


def slot_prompt(slot, manifest):
    case = next(
        c
        for phase in ("pilot", "confirmation")
        for c in manifest["corpus"][phase]
        if c["id"] == slot["case_id"]
    )
    prompt = build_profile_prompt(
        case["question"],
        documents_for(case, manifest["documents"]),
        manifest["profile"],
    )
    if slot["arm"] == "A":
        return prompt
    if slot["arm"] == "B":
        return compose_advisory(prompt, control=True)
    return compose_advisory(prompt, ClassificationContext(slot["label"]))


def freeze(output, classifier_path):
    import hashlib

    from app.classification.predictor import TransformerClassifier

    corpus = json.loads(CASES.read_text())
    validate_corpus(corpus)
    settings = load_runtime_settings(ROOT)
    if (
        settings.config.model_name != "gpt-6-luna"
        or settings.config.max_output_tokens is None
    ):
        raise ValueError("This budget protocol supports the adopted Luna config only")
    documents = [
        json.loads(line)
        for line in (ROOT / "data/company-knowledge/documents.jsonl")
        .read_text()
        .splitlines()
    ]
    classifier = TransformerClassifier(classifier_path)
    labels, cache = {}, {}
    for phase in ("pilot", "confirmation"):
        for case in corpus[phase]:
            question = case["question"]
            if question not in cache:
                start = perf_counter()
                label = classifier.predict(question)
                cache[question] = {
                    "label": label,
                    "seconds": perf_counter() - start,
                    "source": "model",
                }
            labels[case["id"]] = cache[question]
    model_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(classifier_path.iterdir())
        if p.is_file()
    }
    manifest = {
        "schema_version": 1,
        "profile": settings.prompt_profile,
        "config": asdict(settings.config),
        "corpus": corpus,
        "documents": documents,
        "labels": labels,
        "classifier_model_id": classifier.model_id,
        "classifier_hashes": model_hashes,
        "code_hashes": code_hashes(),
        "limits": LIMITS,
        "pricing": {
            "source": "https://developers.openai.com/api/docs/pricing",
            "checked_on": "2026-10-15",
            "input_per_million": 0.25,
            "output_per_million": 0.75,
            "method": "Standard long-context upper rates; no cache discount; not invoice",
        },
        "provenance": "Public synthetic documents; no production DB; F09 synthetic reconstruction",
    }
    manifest["slots"] = make_slots(corpus, labels)
    manifest["prompt_hashes"] = {
        s["slot"]: digest(asdict(slot_prompt(s, manifest))) for s in manifest["slots"]
    }
    manifest["manifest_digest"] = digest(manifest)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "slots": len(manifest["slots"]),
                "profile": manifest["profile"],
                "classifier_model_id": classifier.model_id,
            }
        )
    )


def load_manifest(output):
    manifest = json.loads((output / "manifest.json").read_text())
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_digest"}
    if (
        digest(unsigned) != manifest["manifest_digest"]
        or manifest["code_hashes"] != code_hashes()
        or manifest["limits"] != LIMITS
    ):
        raise ValueError(
            "Manifest/code/budget mismatch; resume refused before model call"
        )
    if manifest["corpus"] != json.loads(CASES.read_text()):
        raise ValueError("Corpus mismatch; resume refused")
    return manifest


def pilot_decision(manifest, records, judgments):
    slots = [s for s in manifest["slots"] if s["phase"] == "pilot"]
    if any(s["slot"] not in records or s["slot"] not in judgments for s in slots):
        return {"eligible": False, "reason": "incomplete pilot"}
    for s in slots:
        j = judgments[s["slot"]]
        if j.get("grade") not in ("pass", "partial", "fail", "uncertain") or not j.get(
            "reason"
        ):
            raise ValueError("Missing semantic judgment")
        if j.get("record_sha256") != digest(records[s["slot"]]):
            raise ValueError("Judgment is not bound to this response")
    stable = {
        arm: sum(
            all(
                judgments[f"{c['id']}:{arm}:{r}"]["grade"] == "pass"
                and records[f"{c['id']}:{arm}:{r}"]["status"] == "completed"
                for r in (1, 2)
            )
            for c in manifest["corpus"]["pilot"]
        )
        for arm in ("A", "B", "C")
    }
    unsafe = any(
        judgments[s["slot"]].get("serious", True)
        or (s["arm"] == "W" and judgments[s["slot"]].get("false_rejection", True))
        for s in slots
        if s["arm"] in ("C", "W")
    )
    return {
        "eligible": not unsafe
        and stable["C"] >= stable["A"] + 1
        and stable["C"] >= stable["B"] + 1,
        "stable": stable,
        "unsafe": unsafe,
    }


def run_batch(output, through, call):
    """call is lazy; manifest and reservations are checked before any provider call."""
    if through not in (24, 48, 64, 124, 184):
        raise ValueError("Invalid checkpoint")
    with (output / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = load_manifest(output)
        records = read_records(output)
        if through > 64:
            judgments = json.loads((output / "judgments.json").read_text())
            if not pilot_decision(manifest, records, judgments)["eligible"]:
                raise ValueError("Pilot did not pass; confirmation refused")
        ledger = BudgetLedger(output / "ledger.json", **LIMITS)
        ledger.bind_limits()
        config = config_from_dict(manifest["config"])
        for slot in manifest["slots"][:through]:
            key = slot["slot"]
            if key in records:
                # Recover a crash between durable response and settlement.
                ledger.settle(key, records[key]["actual_cost_usd"])
                continue
            if key in ledger.snapshot()["reservations"]:
                raise ValueError("Uncertain prior attempt; automatic retry refused")
            prompt = slot_prompt(slot, manifest)
            if digest(asdict(prompt)) != manifest["prompt_hashes"][key]:
                raise ValueError("Prompt hash mismatch")
            bound = reserve_cost(to_messages(prompt), config.max_output_tokens)
            try:
                ledger.reserve(
                    key, "dev" if slot["phase"] == "pilot" else "final", bound
                )
            except BudgetExceeded:
                append_json(
                    output / "events.jsonl", {"slot": key, "event": "budget_stop"}
                )
                return
            append_json(
                output / "events.jsonl",
                {"slot": key, "event": "started", "reserved_usd": bound},
            )
            start = perf_counter()
            row = {
                "slot": key,
                "phase": slot["phase"],
                "arm": slot["arm"],
                "case_id": slot["case_id"],
                "repeat": slot["repeat"],
                "label": slot["label"],
                "prompt_sha256": manifest["prompt_hashes"][key],
                "reserved_usd": bound,
            }
            try:
                result = generate(prompt, call)
                row.update(asdict(result))
                row["status"] = result.status.value
                row["error_type"] = None
                row["actual_cost_usd"] = (
                    (result.input_tokens * 0.25 + result.output_tokens * 0.75) / 1e6
                    if result.input_tokens is not None
                    and result.output_tokens is not None
                    else None
                )
            except Exception as exc:  # noqa: BLE001 - persist error type, never exception text
                row.update(
                    status="execution_error",
                    raw_text=None,
                    answer=None,
                    error_type=type(exc).__name__,
                    input_tokens=None,
                    output_tokens=None,
                    actual_cost_usd=None,
                )
            row["seconds"] = perf_counter() - start
            row["charged_usd"] = (
                bound if row["actual_cost_usd"] is None else row["actual_cost_usd"]
            )
            append_json(output / "responses.jsonl", row)
            ledger.settle(key, row["actual_cost_usd"])
            append_json(output / "events.jsonl", {"slot": key, "event": "finished"})
            print(key, row["status"], flush=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--classifier", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--through", type=int, choices=(24, 48, 64, 124, 184), required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.output, args.classifier)
        return
    client = None

    def call(prompt):
        nonlocal client
        if client is None:
            client = build_managed_model_call(
                config_from_dict(load_manifest(args.output)["config"])
            )
        return client(prompt)

    try:
        run_batch(args.output, args.through, call)
    finally:
        if client is not None:
            await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
