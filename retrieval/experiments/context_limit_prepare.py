"""Prepare the independently reviewed 12-case context-limit comparison."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from generation.documents import render_document
from generation.profiles import build_profile_prompt
from retrieval.experiments.answers import _runtime_settings
from retrieval.experiments.calibration_answers import validate_inputs

ROOT = Path(__file__).resolve().parents[2]
CASE_IDS = (
    "R01",
    "R05",
    "R08",
    "R11",
    "R14",
    "R16",
    "D07",
    "D19",
    "D20",
    "U01",
    "U03",
    "U04",
)
VARIANTS = ("A_existing", "B_tokens_only", "C_unlimited")


def prepare(qrels_path, selection_path, search_path, output):
    if output.exists():
        raise ValueError("Preserve existing frozen inputs")
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    selection = json.loads(selection_path.read_text())
    qrels = json.loads(qrels_path.read_text())
    search = json.loads(search_path.read_text())
    if (
        selection["status"] != "frozen_independent_ai_reviewed"
        or tuple(selection["case_ids"]) != CASE_IDS
        or selection["qrels_sha"] != digest(qrels_path)
        or search["qrels_sha"] != digest(qrels_path)
    ):
        raise ValueError("Reviewed selection and search provenance must match")
    by_id = {c["case_id"]: c for c in qrels["cases"]}
    rows = {(r["case_id"], r["variant_id"]): r for r in search["rows"]}
    settings = _runtime_settings(ROOT)
    cases = []
    for cid in CASE_IDS:
        case = by_id[cid]
        variants = []
        for name in VARIANTS:
            row = rows[cid, name]
            documents = [
                "[현재 게시 문서의 발췌 근거]\n"
                + render_document(
                    e["knowledge_id"], e["title"], e["text"], e["revision"]
                )
                for e in row["evidence"]
            ]
            if documents:
                variant = {
                    "variant_id": name,
                    "prompt": asdict(
                        build_profile_prompt(
                            case["question"], documents, settings.prompt_profile
                        )
                    ),
                }
            else:
                variant = {
                    "variant_id": name,
                    "prompt": None,
                    "skipped_reason": "empty_evidence",
                    "fixed_response": "관련 문서에서 답변에 필요한 근거를 찾지 못했습니다.",
                }
            variants.append(variant)
        cases.append(
            {
                "case_id": cid,
                "question": case["question"],
                "answerability": case["answerability"],
                "answerable": case["answerability"] == "answerable",
                "variants": variants,
            }
        )
    result = {
        "schema_version": 1,
        "phase": "quick_context",
        "repeats": 1,
        "identifiers": {
            "provider": "openai",
            "model_name": "gpt-6-luna",
            "prompt_profile": "examples_answer_scope_v5",
            "reasoning_effort": "xhigh",
            "max_output_tokens": 16384,
            "output_mode": "prompt_json",
            "runtime_config": asdict(settings.config),
            "qrels_sha": digest(qrels_path),
            "selection_sha": digest(selection_path),
            "search_sha": digest(search_path),
            "snapshot_fingerprint": search["snapshot_fingerprint"],
            "model_revision": search["model_revision"],
        },
        "cases": cases,
    }
    validate_inputs(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["qrels", "selection", "search", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.qrels, args.selection, args.search, args.output)
