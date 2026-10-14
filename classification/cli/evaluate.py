"""평가 실행 조립: 경로·모델·측정 정책을 결정하고 workflow 결과를 저장·표시한다."""

import argparse
from pathlib import Path
from time import perf_counter

from contracts.classification import LABELS

from .. import artifacts, dataset
from ..evaluation import reporting
from ..evaluation.metrics import memory_mib
from ..models import jev, jev_prompt, tfidf, transformer
from ..types import MeasurementPolicy
from ..workflows.evaluate import evaluate_questions

LOCAL_MEASUREMENT = MeasurementPolicy("repeated", warmup=3, repeats=3, cpu_threads=4)
REQUEST_MEASUREMENT = MeasurementPolicy("request")


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
    artifacts.save_evaluation(kind, report, result, result_dir)
    render_reports(kind, report, result_dir, cpu_threads=result.cpu_threads)
    return report


def prepare_jev_data(dataset_path=dataset.DATASET_PATH):
    data = dataset.prepare_data(dataset_path, dataset.RANDOM_SEED)
    if list(jev_prompt.CATEGORIES) != list(LABELS):
        raise ValueError("Jev 카테고리 순서가 공통 질문 라벨과 다릅니다.")
    train_by_id = {row["question_id"]: row for row in data.rows["train"]}
    for label, ids in jev_prompt.EXAMPLE_QUESTION_IDS.items():
        examples = jev_prompt.CATEGORIES[label]["examples"]
        if len(ids) != len(examples):
            raise ValueError("대표 예시 ID와 질문의 개수가 다릅니다.")
        for question_id, example in zip(ids, examples):
            row = train_by_id.get(question_id)
            if (
                row is None
                or row["label"] != label
                or row["question"] != example["question"]
            ):
                raise ValueError(
                    f"대표 예시 {question_id}가 현재 train 질문·정답과 맞지 않습니다."
                )
    return data


def evaluate_jev(
    *, dataset_path=dataset.DATASET_PATH, result_dir=artifacts.RESULT_DIR, predict=None
):
    jev.require_credentials()
    data = prepare_jev_data(dataset_path)
    count = sum(len(ids) for ids in jev_prompt.EXAMPLE_QUESTION_IDS.values())
    result = evaluate_questions(
        data.rows, jev.predict if predict is None else predict, REQUEST_MEASUREMENT
    )
    settings = {
        "requested_model": jev_prompt.MODEL_NAME,
        "training_mode": "가중치 학습 없이 train 대표 예시를 프롬프트에 제공",
        "prompt_examples_count": count,
        "prompt_example_ids": jev_prompt.EXAMPLE_QUESTION_IDS,
        "prompt_example_source": "train",
        "prompt_review_scope": jev_prompt.PROMPT_REVIEW_SCOPE,
        "test_interpretation": "프롬프트 설계 때 읽은 평가셋이며, 미열람 최종 평가셋이 아님",
        "labels": list(LABELS),
        "seed": dataset.RANDOM_SEED,
        "data_split": data.record,
        "input_condition": "question 열만 입력, 전체 질문 사용 (이전 대화 없음)",
        "resolved_models": result.resolved_models,
        "evaluation_calls": len(result.predictions),
        "input_tokens": result.input_tokens,
        "instructions": jev_prompt.INSTRUCTIONS,
        "criteria": jev_prompt.CATEGORIES,
    }
    report = artifacts.evaluation_report(
        result,
        data,
        title="JEV · API 요청 처리 분류",
        settings=settings,
        api=True,
        train_count=count,
    )
    artifacts.save_evaluation(
        jev_prompt.MODEL_FOLDER, report, result, result_dir, save_predictions=True
    )
    render_reports(jev_prompt.MODEL_FOLDER, report, result_dir)
    return report


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
            )
        )
    else:
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


def jev_main(argv=None):
    parser = argparse.ArgumentParser(description="Jev 요청 처리 질문 분류 및 평가")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument(
        "--preview-questions",
        "--preview-documents",
        dest="preview_questions",
        action="store_true",
    )
    parser.add_argument("--dataset", type=Path, default=dataset.DATASET_PATH)
    parser.add_argument("--result-dir", type=Path, default=artifacts.RESULT_DIR)
    args = parser.parse_args(argv)
    if args.preview_questions:
        data = prepare_jev_data(args.dataset)
        print("분할 시드:", dataset.RANDOM_SEED)
        for name, split in data.record["splits"].items():
            print(name, split["count"], "개", split["label_counts"])
        print(
            "Jev 평가 요청 수:", len(data.rows["validation"]) + len(data.rows["test"])
        )
        print("첫 번째 검증 입력:\n", data.rows["validation"][0]["question"], sep="")
        print("첫 번째 정답:", data.rows["validation"][0]["label"])
        print("train에서 고른 대표 예시:")
        for criteria in jev_prompt.CATEGORIES.values():
            for example in criteria["examples"]:
                print(example["question"], example["reason"])
    elif args.evaluate:
        evaluate_jev(dataset_path=args.dataset, result_dir=args.result_dir)
    else:
        prediction = jev.predict(jev_prompt.QUESTION)
        content = {
            "input_text": jev_prompt.QUESTION,
            "predicted": prediction.label,
            "confidence": prediction.confidence,
            "probabilities": prediction.probabilities,
            "model": prediction.model,
        }
        output = (
            artifacts.report_dir(jev_prompt.MODEL_FOLDER, args.result_dir)
            / "single_prediction.json"
        )
        artifacts.save_json(output, content)
        print("질문 입력:", jev_prompt.QUESTION)
        print("분류:", prediction.label)
        for label, probability in (prediction.probabilities or {}).items():
            print(f"{label}: {probability:.2%}")
        print("저장 위치:", output)


def refresh_comparison(artifact_root):
    """유효 모델에 연결된 결과만 같은 평가 조건끼리 비교한다."""
    from .. import storage

    with storage.lock(artifact_root, "comparison"):
        groups = {}
        for path in sorted((artifact_root / "results").glob("*/metrics.json")):
            try:
                report = artifacts.read_json(path)
                manifest = storage.validate_bundle(
                    artifact_root / "models" / path.parent.name, path.parent.name
                )
                if report.get("model_id") != manifest["model_id"]:
                    continue
                if not artifacts.is_current_report(report):
                    continue
                key = storage.digest(
                    {
                        "labels": report["settings"]["labels"],
                        "split": report["settings"]["data_split"],
                        **{
                            key: report.get(key)
                            for key in (
                                "data_hashes",
                                "counts",
                                "measurement_policy",
                                "evaluation_environment",
                            )
                        },
                    }
                )
                groups.setdefault(key, {})[path.parent.name] = report
            except (ValueError, OSError, KeyError):
                continue
        output = artifact_root / "results/comparison.html"
        # 각 그룹별 완전한 보고서를 별도 페이지로 만들고 인덱스에서 연결한다.
        from html import escape

        links = []
        active_pages = set()
        for key, reports in groups.items():
            name = f"comparison-{key}.html"
            active_pages.add(name)
            storage.atomic_text(
                output.parent / name, reporting.render_comparison(reports)
            )
            links.append(f'<li><a href="{name}">{escape(", ".join(reports))}</a></li>')
        storage.atomic_text(
            output,
            '<!doctype html><meta charset="utf-8"><h1>동일 조건 모델 비교</h1><p>모델과 불일치하거나 손상된 결과는 제외됩니다.</p><ul>'
            + "".join(links)
            + "</ul>",
        )

        # 이전 그룹 링크를 직접 열어도 현재 모델의 점수로 오해하지 않게 표시한다.
        for old in output.parent.glob("comparison-*.html"):
            if old.name not in active_pages:
                storage.atomic_text(
                    old,
                    '<!doctype html><meta charset="utf-8"><p>이 비교는 현재 모델·평가 조건과 달라 만료되었습니다. <a href="comparison.html">현재 비교</a></p>',
                )


def evaluate_current(name, *, artifact_root, dataset_path=dataset.DATASET_PATH):
    """고정 모델 저장소를 검증하고 매번 CPU에서 평가한다. 학습을 호출하지 않는다."""
    import shutil
    from dataclasses import asdict

    from .. import storage
    from ..models.presets import load_bundle
    from .main import command_hint

    with storage.lock(artifact_root, name):
        storage.recover(artifact_root, "models", name)
        storage.recover(artifact_root, "results", name)
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
        result = evaluate_questions(data.rows, predict, LOCAL_MEASUREMENT)
        report = artifacts.evaluation_report(
            result,
            data,
            title=f"{name.upper()} · 요청 처리 분류",
            settings=settings,
            model_size=artifacts.model_size_mib(bundle),
            load_seconds=load_seconds,
            rss=memory_mib(),
        )
        report.update(
            model_id=manifest["model_id"],
            evaluation_environment={
                **storage.environment(),
                "device": "cpu",
                "cpu_threads": 4,
            },
            measurement_policy=asdict(LOCAL_MEASUREMENT),
        )
        temporary = storage.stage(artifact_root, "eval-" + name)
        try:
            artifacts.save_json(temporary / "metrics.json", report)
            artifacts.save_json(temporary / "predictions.json", result.predictions)
            artifacts.save_html(
                temporary / "report.html", reporting.render_report(report)
            )
            storage.publish(artifact_root, "results", name, temporary)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    refresh_comparison(artifact_root)
    print("HTML 보고서:", artifact_root / "results" / name / "report.html")
    return report
