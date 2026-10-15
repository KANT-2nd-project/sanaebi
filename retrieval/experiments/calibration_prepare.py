"""Freeze reviewed retrieval contexts into existing v5 generation prompts."""

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from generation.documents import render_document
from generation.profiles import build_profile_prompt
from retrieval.experiments.answers import _runtime_settings
from retrieval.experiments.calibration_answers import validate_inputs

ROOT = Path(__file__).resolve().parents[2]


def prepare(qrels_path, confirmation_path, search_path, variants, phase, output):
    if output.exists():
        raise ValueError("Output exists; preserve frozen inputs")
    qrels = json.loads(qrels_path.read_text())
    confirmation = json.loads(confirmation_path.read_text())
    for data in (qrels, confirmation):
        if data["status"] != "frozen_independent_ai_reviewed":
            raise ValueError(
                "Both development and new confirmation must be reviewed and frozen"
            )
    active_path = qrels_path if phase == "development" else confirmation_path
    active_cases = qrels if phase == "development" else confirmation
    search = json.loads(search_path.read_text())
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if search["qrels_sha"] != digest(active_path):
        raise ValueError("Search results belong to different qrels")
    rows = {(r["case_id"], r["variant_id"]): r for r in search["rows"]}
    settings = _runtime_settings(ROOT)
    cases = []
    for case in active_cases["cases"]:
        selected = []
        for variant in variants:
            row = rows[case["case_id"], variant]
            documents = [
                "[현재 게시 문서의 발췌 근거]\n"
                + render_document(
                    e["knowledge_id"], e["title"], e["text"], e["revision"]
                )
                for e in row["evidence"]
            ]
            if documents:
                entry = {
                    "variant_id": variant,
                    "prompt": asdict(
                        build_profile_prompt(
                            case["question"], documents, settings.prompt_profile
                        )
                    ),
                }
            else:
                entry = {
                    "variant_id": variant,
                    "prompt": None,
                    "skipped_reason": "empty_evidence",
                    "fixed_response": "관련 문서에서 답변에 필요한 근거를 찾지 못했습니다.",
                }
            selected.append(entry)
        cases.append(
            {
                "case_id": case["case_id"],
                "question": case["question"],
                "answerability": case["answerability"],
                "answerable": case["answerability"] == "answerable",
                "variants": selected,
            }
        )
    payload = {
        "schema_version": 1,
        "phase": phase,
        "repeats": 2,
        "identifiers": {
            "provider": "openai",
            "model_name": "gpt-6-luna",
            "prompt_profile": "examples_answer_scope_v5",
            "reasoning_effort": "xhigh",
            "max_output_tokens": 16384,
            "output_mode": "prompt_json",
            "runtime_config": asdict(settings.config),
            "qrels_sha": digest(active_path),
            "development_qrels_sha": digest(qrels_path),
            "confirmation_sha": digest(confirmation_path),
            "search_sha": digest(search_path),
            "snapshot_fingerprint": search["snapshot_fingerprint"],
            "model_revision": search["model_revision"],
            "code_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
        },
        "cases": cases,
    }
    validate_inputs(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", required=True)
    parser.add_argument(
        "--phase", choices=["development", "confirmation"], required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(
        args.qrels,
        args.confirmation,
        args.search,
        args.variants,
        args.phase,
        args.output,
    )
