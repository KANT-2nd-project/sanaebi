"""Generate one answer from an explicit exported document file."""

import argparse
import json
from pathlib import Path

from generation.documents import load_documents
from generation.presets import DEFAULT_EXPERIMENT, DEFAULT_MODEL, load_preset
from generation.providers import build_model_call
from generation.types import GenerationStatus
from generation_evaluation.reporting import run_to_dict
from generation_evaluation.runner import run_case


def main() -> int:
    parser = argparse.ArgumentParser(description="사내비 문서 기반 답변 생성")
    parser.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    parser.add_argument("--model", default=DEFAULT_MODEL)  # 실제 모델명이 아닌 별칭
    parser.add_argument("--question", required=True)
    args = parser.parse_args()

    question = args.question.strip()
    if not question:
        parser.error("--question은 비어 있을 수 없습니다.")

    generation_dir = Path(__file__).resolve().parent
    project_root = generation_dir.parent

    try:
        preset = load_preset(project_root, args.experiment, args.model)
    except ValueError as exc:
        parser.error(str(exc))
    config = preset.config
    documents_path = preset.documents_path
    documents = load_documents(documents_path)
    model_call = build_model_call(config)
    run = run_case(
        case_id="manual",
        config=config,
        question=question,
        documents=documents,
        model_call=model_call,
        prompt_profile=preset.prompt_profile,
    )
    record = run_to_dict(run)
    record["experiment"] = args.experiment
    record["model_alias"] = args.model
    record["question"] = question

    print(json.dumps(record, ensure_ascii=False, indent=2))

    if run.result is None:
        return 1

    return 0 if run.result.status is GenerationStatus.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
