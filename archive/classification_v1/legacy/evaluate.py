"""구형 저장 형식 평가. 현행 CLI와 분리된 호환 경계."""

import shutil
from pathlib import Path
from time import perf_counter

from .. import artifacts, dataset, storage, tracking
from ..evaluation import reporting
from ..evaluation.metrics import memory_mib
from ..models import tfidf, transformer
from ..types import MeasurementPolicy
from ..workflows.evaluate import evaluate_legacy_questions as evaluate_questions

LOCAL_MEASUREMENT = MeasurementPolicy("repeated", warmup=3, repeats=3, cpu_threads=4)


def render_reports(kind, report, result_dir, *, cpu_threads=4):
    output = artifacts.report_dir(kind, result_dir) / "report.html"
    artifacts.save_html(
        output, reporting.render_report(report, cpu_threads=cpu_threads)
    )
    artifacts.save_html(
        result_dir / "comparison.html",
        reporting.render_comparison(artifacts.read_reports(result_dir)),
    )
    print("HTML 보고서:", output)
    return output


def evaluate_saved_model(
    kind,
    *,
    dataset_path=dataset.DATASET_PATH,
    model_dir=artifacts.MODEL_DIR,
    result_dir=artifacts.RESULT_DIR,
):
    if Path(kind).name != kind or kind in {".", ".."}:
        raise ValueError("모델 폴더 이름만 입력하세요.")
    metrics_path = artifacts.report_dir(kind, result_dir) / "metrics.json"
    if metrics_path.is_file():
        saved = artifacts.read_json(metrics_path)
        if saved["benchmark"].get("mode") == "api":
            render_reports(kind, saved, result_dir)
            return saved
    # 모델 종류 선택은 실행 조립에만 둔다. workflow는 predict만 받는다.
    if kind == "tfidf_lr":
        model_path = model_dir / "tf-idf/tfidf_logistic_regression.joblib"
        summary_path = model_path.with_suffix(".json")
        load = tfidf.load
        title = "TF-IDF + 로지스틱 회귀 · 요청 처리 분류"
    else:
        model_path = model_dir / kind
        summary_path = model_path / "training_summary.json"
        load = transformer.load
        title = f"{kind.upper()} · 요청 처리 분류"
    if not model_path.exists():
        raise FileNotFoundError(f"저장된 모델이 없습니다: {model_path}")
    settings = artifacts.read_json(summary_path) if summary_path.is_file() else {}
    if not artifacts.is_current_report({"settings": settings}):
        raise ValueError("현재 질문 3분류 모델로 다시 학습한 결과가 필요합니다.")
    data = dataset.restore_data(settings["data_split"], dataset_path)
    root = result_dir.resolve().parent
    with storage.lock(root, kind):
        storage.check_pending(root, kind)
        with tracking.start_run(root, kind, "eval_legacy", data, split="both") as run:
            started = perf_counter()
            predict = load(model_path, settings)
            load_seconds = perf_counter() - started
            result = evaluate_questions(data.rows, predict, LOCAL_MEASUREMENT)
            report = artifacts.evaluation_report(
                result,
                data,
                title=title,
                settings=settings,
                model_size=artifacts.model_size_mib(model_path),
                load_seconds=load_seconds,
                rss=memory_mib(),
            )
            report.update(tracking_run_id=run.run_id, evaluated_split="both")
            temporary = storage.stage(root, kind)
            folder = "tf-idf" if kind == "tfidf_lr" else kind
            try:
                artifacts.save_json(temporary / "metrics.json", report)
                artifacts.save_json(temporary / "predictions.json", result.predictions)
                storage.publish(root, result_dir.name, folder, temporary)
                run.saved_path = result_dir / folder
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            run.evaluation(report, result.predictions)
            print("구형 모델 평가 결과:", run.saved_path)
    return report
