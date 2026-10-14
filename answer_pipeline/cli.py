"""명령줄 실행. 저장소 루트에서 실행한다 (PowerShell 예시).

  uv run python -m answer_pipeline.cli run    --eval-set EVAL.jsonl --documents DOCS.jsonl --models MODELS.json --run-dir RUN
                                              [--split dev] [--repeats 2] [--dry-run]
  (RUN\\human_scores_blind.csv 채점)
  uv run python -m answer_pipeline.cli report --run-dir RUN [--prices PRICES.json]

run은 평가 세트를 회사 문서와 대조한 뒤 질문을 main의 LangChain 실행기(sanaebi_assistant.py)로
모델마다 실행하고, 모델 이름을 가린 채점표를 만든다. --dry-run은 대조와 호출 수 확인만 한다.
report는 자동 점검, 사람 채점 반영, 역순 디버깅, 비교 보고서를 만든다. 채점표를 채울 때마다 다시 실행한다.
openai는 요금이 발생한다. OPENAI_API_KEY가 없으면 실행할 때 입력받는다 (화면에 표시하지 않음).
"""

import argparse
import getpass
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import sanaebi_assistant as assistant
from app.company_knowledge import PROJECT_ROOT

from .checks import evaluate_records, summarize
from .report import debug_records, estimate_costs, load_prices, render_report
from .run import (
    ANSWER_ROUTE,
    SPLITS,
    applied_conditions,
    check_eval_set,
    load_documents,
    load_eval_set,
    load_model_configs,
    read_jsonl,
    run_comparison,
    write_jsonl,
)
from .scoring import load_human_scores, usable_summary, write_blind_sheet

# docs/generation-evaluation.md C-4의 OpenAI 호출 상한 (제안값)
DEFAULT_MAX_OPENAI_CALLS = 120
DEFAULT_EVALUATION_DOCUMENTS_PATH = (
    PROJECT_ROOT / "data/archive/company-knowledge-v0/ieum_works.jsonl"
)
DEFAULT_EVAL_SET_PATH = DEFAULT_EVALUATION_DOCUMENTS_PATH.parent / "eval_set_dev.jsonl"


def show(path):
    path = Path(path)
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return str(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_commit():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(assistant.__file__).resolve().parent,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def executor_info(documents, documents_path=None):
    """실행기 파일·프롬프트·문서가 바뀌었는지 나중에 확인할 수 있게 지문을 남긴다."""
    documents_path = Path(documents_path or assistant.DOCUMENTS_PATH)
    prompt = assistant.ANSWER_PROMPT.template + json.dumps(
        assistant.CLASSIFICATION_INSTRUCTIONS, ensure_ascii=False, sort_keys=True
    )
    return {
        "file": show(assistant.__file__),
        "sha256": sha256(assistant.__file__),
        "git_commit": git_commit(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "documents_path": show(documents_path),
        "documents_sha256": sha256(documents_path),
        "documents": len(documents),
    }


def ask_openai_key():
    if os.getenv("OPENAI_API_KEY"):
        return
    key = getpass.getpass("OpenAI API 키 (입력 숨김): ").strip()
    if not key:
        raise SystemExit("OpenAI API 키가 없어 실행하지 않습니다.")
    os.environ["OPENAI_API_KEY"] = key


def cmd_run(args):
    if args.repeats < 1:
        raise SystemExit("--repeats는 1 이상이어야 합니다.")
    eval_set_path = Path(args.eval_set)
    if (
        args.documents is None
        and eval_set_path.resolve() != DEFAULT_EVAL_SET_PATH.resolve()
    ):
        raise SystemExit(
            "기본 평가 세트가 아니면 같은 버전의 회사 문서를 --documents로 지정하세요."
        )
    # 보관 평가를 새 정책이나 IEUM_WORKS_PATH의 다른 문서와 자동 연결하지 않는다.
    documents_path = Path(args.documents or DEFAULT_EVALUATION_DOCUMENTS_PATH)
    # 대조와 실행 프롬프트가 같은 문서 JSONL을 사용한다.
    rows = load_eval_set(eval_set_path)
    documents = load_documents(documents_path)
    errors, warnings = check_eval_set(rows, documents)
    print(
        f"평가 세트 {show(args.eval_set)} {len(rows)}건 · 회사 문서 "
        f"{show(documents_path)} {len(documents)}건 · "
        f"오류 {len(errors)}건, 경고 {len(warnings)}건"
    )
    for line in errors:
        print("  [오류]", line)
    for line in warnings:
        print("  [경고]", line)
    cases = [row for row in rows if args.split is None or row["split"] == args.split]
    if not cases:
        raise SystemExit(f"실행할 질문이 없습니다 (split={args.split}).")
    if errors:
        raise SystemExit("평가 세트에 오류가 있어 호출하지 않습니다.")
    configs = load_model_configs(args.models)

    calls = len(cases) * args.repeats
    answer_cases = sum(case["expected_route"] == ANSWER_ROUTE for case in cases)
    print(
        f"질문 {len(cases)}건 (SEARCH_KNOWLEDGE {answer_cases}건) × 반복 {args.repeats}회"
        f" × 모델 {len(configs)}개 → 모델당 {calls}회"
    )
    for config in configs:
        print(f"  {config.name}: {applied_conditions(config)}")
    openai_calls = calls * sum(config.provider == "openai" for config in configs)
    if openai_calls:
        print(
            f"  OpenAI 호출 {openai_calls}회 · 요금 발생 (상한 {args.max_openai_calls}회)"
        )
    if openai_calls > args.max_openai_calls:
        raise SystemExit(
            f"OpenAI 호출 {openai_calls}회가 상한 {args.max_openai_calls}회를 넘어 실행하지 않습니다."
        )
    if args.dry_run:
        print("[dry-run] 모델을 부르지 않았습니다.")
        return

    run_dir = Path(args.run_dir)
    if (run_dir / "results.jsonl").exists():
        raise SystemExit(
            f"이미 실행 기록이 있습니다. 다른 --run-dir을 쓰세요: {show(run_dir)}"
        )
    if openai_calls:
        ask_openai_key()
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "eval_set_path": show(eval_set_path),
        "eval_set_sha256": sha256(eval_set_path),
        "splits": sorted({case["split"] for case in cases}),
        "cases": len(cases),
        "repeats": args.repeats,
        "models": [applied_conditions(config) for config in configs],
        "executor": executor_info(documents, documents_path),
        "input": "평가 세트의 expected_route를 classification_label로 고정 입력",
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    records = run_comparison(
        cases,
        run_dir,
        configs,
        args.repeats,
        documents,
        documents_path=documents_path,
    )
    sheet_rows = write_blind_sheet(records, run_dir)
    for config in configs:
        subset = [r for r in records if r["model_name"] == config.name]
        failed = sum(r["error"] is not None for r in subset)
        print(f"  {config.name}: 호출 {len(subset)}, 오류 {failed}")
    print(
        f"기록: {show(run_dir / 'results.jsonl')} · 채점표 {sheet_rows}행: "
        f"{show(run_dir / 'human_scores_blind.csv')}"
    )


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def cmd_report(args):
    run_dir = Path(args.run_dir)
    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        raise SystemExit(f"실행 기록이 없습니다: {show(results_path)}")
    meta_path = run_dir / "meta.json"
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    )
    records = read_jsonl(results_path)

    evaluations = evaluate_records(records)
    summary = summarize(records, evaluations)
    if args.prices:
        summary["costs"] = estimate_costs(summary, records, load_prices(args.prices))
    human = load_human_scores(run_dir)
    usable = usable_summary(records, evaluations, human)
    traces = debug_records(records, evaluations, human)
    comparison = {
        name: {k: v for k, v in stats.items() if k != "verdicts"}
        for name, stats in usable.items()
    }
    write_jsonl(run_dir / "checks.jsonl", evaluations)
    write_jsonl(run_dir / "debug_trace.jsonl", traces)
    write_json(run_dir / "evaluation_summary.json", summary)
    write_json(run_dir / "comparison.json", comparison)
    report = render_report(run_dir.name, records, summary, traces, human, usable, meta)
    (run_dir / "report.md").write_text(report, encoding="utf-8")

    flagged = sum(t["flagged"] for t in traces)
    print(
        f"[보고] 기록 {len(records)}개 · 이상한 답변 {flagged}개 · 사람 채점 {len(human)}행 반영"
    )
    for name, stats in comparison.items():
        ratio = stats["usable_ratio"]
        status = (
            f"채점 대기 {stats['pending']}건"
            if ratio is None
            else f"{stats['usable']}/{stats['calls']} ({ratio:.1%})"
        )
        print(f"  {name} 사용 가능 답변: {status}")
    print(f"보고서: {show(run_dir / 'report.md')}")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m answer_pipeline.cli",
        description="평가 세트를 LangChain 실행기로 모델마다 실행하고 채점·비교한다.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="실행기로 모델별 실행, 채점표 만들기")
    p.add_argument(
        "--eval-set",
        default=DEFAULT_EVAL_SET_PATH,
        help="평가 세트 JSONL (기본: 보관된 v0 문서의 개발 평가 세트)",
    )
    p.add_argument(
        "--documents",
        type=Path,
        help="평가와 같은 버전의 문서 (기본: v0 보관본; 별도 평가 세트는 필수)",
    )
    p.add_argument("--models", required=True, help="비교할 모델 설정 JSON")
    p.add_argument(
        "--split", choices=SPLITS, help="평가 세트에서 이 구분의 질문만 쓴다"
    )
    p.add_argument("--run-dir", required=True, help="실행 기록 폴더 (실행마다 새 이름)")
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument(
        "--max-openai-calls",
        type=int,
        default=DEFAULT_MAX_OPENAI_CALLS,
        help=f"OpenAI 호출 상한 (기본 {DEFAULT_MAX_OPENAI_CALLS})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="평가 세트 대조와 호출 수 확인만 하고 모델은 부르지 않음",
    )

    p = sub.add_parser(
        "report", help="자동 점검, 사용 가능 답변 비율, 역순 디버깅, 보고서"
    )
    p.add_argument("--run-dir", required=True, help="results.jsonl이 있는 폴더")
    p.add_argument("--prices", help="단가 JSON (주면 추정 비용 계산)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    {"run": cmd_run, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
