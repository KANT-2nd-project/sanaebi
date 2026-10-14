"""Run existing knowledge-routing questions against a fixed document snapshot."""

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

from generation.documents import load_documents
from generation.providers import build_model_call
from generation.types import GenerationStatus
from generation_evaluation.reporting import config_from_dict, run_to_dict
from generation_evaluation.runner import run_case


def main() -> int:
    parser = argparse.ArgumentParser(description="SEARCH_KNOWLEDGE 질문 배치 생성")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit은 양의 정수여야 합니다.")

    root = Path(__file__).resolve().parent.parent
    generation_dir = root / "generation"
    models = json.loads((generation_dir / "models.json").read_text(encoding="utf-8"))
    experiments = json.loads(
        (generation_dir / "experiments.json").read_text(encoding="utf-8")
    )
    if args.experiment not in experiments:
        parser.error(f"등록되지 않은 실험입니다: {args.experiment}")
    experiment = experiments[args.experiment]
    if args.model not in models or args.model not in experiment["models"]:
        parser.error(f"실험에 등록되지 않은 모델입니다: {args.model}")
    settings = models[args.model]
    config = config_from_dict(settings)

    dataset_bytes = (root / "data/dataset.csv").read_bytes()
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    reader = csv.DictReader(io.StringIO(dataset_bytes.decode("utf-8-sig"), newline=""))
    required = {"question_id", "question", "label"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("질문 CSV에 question_id, question, label 열이 필요합니다.")
    cases = []
    ids = set()
    for row in reader:
        if row["label"] != "SEARCH_KNOWLEDGE":
            continue
        for field in ("question_id", "question"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"CSV {reader.line_num}줄의 {field}가 비어 있습니다.")
        if row["question_id"] in ids:
            raise ValueError(f"중복 question_id: {row['question_id']}")
        ids.add(row["question_id"])
        cases.append(row)
    if not cases:
        raise ValueError("SEARCH_KNOWLEDGE 질문이 없습니다.")
    cases.sort(key=lambda row: row["question_id"])
    available = len(cases)
    if args.limit is not None:
        cases = cases[: args.limit]

    documents = load_documents(root / experiment["documents"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed = 0
    # Reserve the destination before client creation or inference. Never append to
    # an existing run; an interrupted output remains available for inspection.
    with args.output.open("x", encoding="utf-8") as output:
        model_call = build_model_call(config)
        for index, row in enumerate(cases, start=1):
            run = run_case(
                case_id=row["question_id"],
                config=config,
                question=row["question"],
                documents=documents,
                model_call=model_call,
            )
            record = run_to_dict(run)
            record.update(
                experiment=args.experiment,
                model_alias=args.model,
                question=row["question"],
                dataset_sha256=dataset_sha256,
                selection_label="SEARCH_KNOWLEDGE",
                available_cases=available,
                planned_cases=len(cases),
                attempt_index=index,
            )
            output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            output.flush()
            if (
                run.result is not None
                and run.result.status is GenerationStatus.COMPLETED
            ):
                completed += 1
            print(f"[{index}/{len(cases)}] {run.case_id}", file=sys.stderr)

    print(
        json.dumps(
            {
                "output": str(args.output),
                "available": available,
                "attempted": len(cases),
                "completed": completed,
                "failed": len(cases) - completed,
            },
            ensure_ascii=False,
        )
    )
    return 0 if completed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
