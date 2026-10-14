"""현행 저장 모델의 명시적 단일 분할 평가와 CLI."""

import argparse
from pathlib import Path
from time import perf_counter

from .. import artifacts, dataset
from ..evaluation import reporting
from ..evaluation.comparison import refresh_comparison
from ..evaluation.metrics import memory_mib
from ..legacy.evaluate import evaluate_saved_model
from ..types import MeasurementPolicy
from ..workflows.evaluate import evaluate_questions
from .jev import evaluate_jev, jev_main, prepare_jev_data

__all__ = [
    "evaluate_current",
    "evaluate_jev",
    "evaluate_saved_model",
    "jev_main",
    "prepare_jev_data",
    "refresh_comparison",
]

LOCAL_MEASUREMENT = MeasurementPolicy("repeated", warmup=3, repeats=3, cpu_threads=4)


def main(argv=None):
    from ..models.presets import CONFIGS
    from ..storage import DEFAULT_ROOT
    from .main import boundary

    parser = argparse.ArgumentParser(
        description="저장 모델 평가. 권장: sanaebi eval MODEL"
    )
    parser.add_argument("kind", help="모델 이름 (과거 tfidf_lr 별칭 지원)")
    parser.add_argument("--dataset", type=Path, default=dataset.DATASET_PATH)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument(
        "--split",
        choices=("validation", "test"),
        default=None,
        help="현행 평가 분할 (기본 validation)",
    )
    parser.add_argument(
        "--model-dir", type=Path, help="과거 저장 형식을 읽을 때만 사용"
    )
    parser.add_argument(
        "--result-dir", type=Path, help="과거 결과/저장된 API 보고서 경로"
    )
    args = parser.parse_args(argv)
    if args.artifact_root is not None and (
        args.model_dir is not None or args.result_dir is not None
    ):
        parser.error("--artifact-root와 과거 경로 옵션은 함께 사용할 수 없습니다.")
    name = "tfidf" if args.kind == "tfidf_lr" else args.kind
    if name in CONFIGS and args.model_dir is None and args.result_dir is None:
        boundary(
            lambda: evaluate_current(
                name,
                artifact_root=(args.artifact_root or DEFAULT_ROOT).resolve(),
                dataset_path=args.dataset,
                split=args.split or "validation",
            )
        )
    else:
        if args.split is not None:
            parser.error("--split은 현행 저장소 평가에서만 지원합니다.")
        if args.artifact_root is not None:
            parser.error("새 저장소에는 등록된 로컬 모델 이름을 사용하세요.")
        boundary(
            lambda: evaluate_saved_model(
                args.kind,
                dataset_path=args.dataset,
                model_dir=args.model_dir or artifacts.MODEL_DIR,
                result_dir=args.result_dir or artifacts.RESULT_DIR,
            )
        )


def evaluate_current(
    name, *, artifact_root, dataset_path=dataset.DATASET_PATH, split="validation"
):
    """고정 모델 저장소를 검증하고 선택한 분할만 CPU에서 평가한다."""
    if split not in {"validation", "test"}:
        raise ValueError("평가 분할은 validation 또는 test여야 합니다.")
    import shutil
    from dataclasses import asdict

    from .. import storage
    from ..models.presets import load_bundle
    from .main import command_hint

    with storage.lock(artifact_root, name):
        storage.recover(artifact_root, "models", name)
        storage.recover(artifact_root, "results", name)
        storage.recover(artifact_root, "results", f"{name}/{split}")
        bundle = artifact_root / "models" / name
        try:
            manifest = storage.validate_bundle(bundle, name)
        except ValueError as error:
            raise ValueError(
                f"{error}\n학습 안내: "
                + command_hint(
                    "train", name, artifact_root, dataset_path, force=bundle.exists()
                )
            ) from error
        settings = artifacts.read_json(bundle / "training_summary.json")
        if not artifacts.is_current_report({"settings": settings}):
            raise ValueError("저장 모델의 라벨·입력 계약이 현재 질문 3분류와 다릅니다.")
        data = dataset.restore_data(settings["data_split"], dataset_path)
        started = perf_counter()
        predict = load_bundle(name, bundle, settings)
        load_seconds = perf_counter() - started
        result = evaluate_questions(data.rows, predict, LOCAL_MEASUREMENT, split=split)
        report = artifacts.evaluation_report(
            result,
            data,
            title=f"{name.upper()} · 요청 처리 분류",
            settings={
                key: value
                for key, value in settings.items()
                if not key.startswith("test_")
            },
            model_size=artifacts.model_size_mib(bundle),
            load_seconds=load_seconds,
            rss=memory_mib(),
        )
        report.update(
            model_id=manifest["model_id"],
            schema_version=2,
            evaluated_split=split,
            evaluation_purpose="개발 비교"
            if split == "validation"
            else "명시적 test 평가 (미열람 최종 평가 보증 없음)",
            data_review="미기록",
            test_exposure="미기록",
            evaluation_environment={
                **storage.environment(),
                "device": "cpu",
                "cpu_threads": 4,
            },
            measurement_policy=asdict(LOCAL_MEASUREMENT),
        )
        if (
            data.record["dataset_sha256"]
            == "a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98"
        ):
            report.update(
                data_review="합성 질문 · AI 검수 · 사람 승인 0건",
                test_exposure="이미 열람한 개발 평가 자료",
            )
        temporary = storage.stage(artifact_root, "eval-" + name + "-" + split)
        try:
            artifacts.save_json(temporary / "metrics.json", report)
            artifacts.save_json(temporary / "predictions.json", result.predictions)
            artifacts.save_html(
                temporary / "report.html", reporting.render_report(report)
            )
            storage.publish(artifact_root, "results", f"{name}/{split}", temporary)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    refresh_comparison(artifact_root)
    print("HTML 보고서:", artifact_root / "results" / name / split / "report.html")
    return report
