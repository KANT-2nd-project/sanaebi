"""Generate one answer from an explicit exported document file."""

import argparse
import json
from pathlib import Path

from generation.config import GenerationConfig, GenerationProvider
from generation.documents import load_documents
from generation.providers import build_model_call
from generation.types import GenerationStatus
from generation_evaluation.reporting import run_to_dict
from generation_evaluation.runner import run_case


def main() -> int:
    parser = argparse.ArgumentParser(description="사내비 문서 기반 답변 생성")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--model", required=True)  # 실제 모델명이 아닌 별칭
    parser.add_argument("--question", required=True)
    args = parser.parse_args()

    question = args.question.strip()
    if not question:
        parser.error("--question은 비어 있을 수 없습니다.")

    generation_dir = Path(__file__).resolve().parent
    project_root = generation_dir.parent

    models = json.loads((generation_dir / "models.json").read_text(encoding="utf-8"))
    experiments = json.loads(
        (generation_dir / "experiments.json").read_text(encoding="utf-8")
    )

    if args.experiment not in experiments:
        parser.error(f"등록되지 않은 실험입니다: {args.experiment}")
    experiment = experiments[args.experiment]

    if args.model not in models:
        parser.error(f"등록되지 않은 모델입니다: {args.model}")

    if args.model not in experiment["models"]:
        parser.error(f"{args.experiment} 실험에 등록되지 않은 모델입니다: {args.model}")
    model_settings = models[args.model]

    config = GenerationConfig(
        provider=GenerationProvider(model_settings["provider"]),
        model_name=model_settings["model_name"],
        timeout_seconds=model_settings["timeout_seconds"],
        context_window=model_settings.get("context_window"),
        max_output_tokens=model_settings.get("max_output_tokens"),
    )

    documents_path = project_root / experiment["documents"]
    documents = load_documents(documents_path)

    model_call = build_model_call(config)
    run = run_case(
        case_id="manual",
        config=config,
        question=question,
        documents=documents,
        model_call=model_call,
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
