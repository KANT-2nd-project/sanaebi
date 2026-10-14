"""학습 실행 조립. 학습 → 저장 → 별도 평가 프로세스 정책을 이 계층에서 결정한다."""

import argparse
import subprocess
import sys
from functools import partial
from pathlib import Path
from time import perf_counter

from contracts.classification import LABELS

from .. import artifacts, dataset
from ..models import tfidf, transformer
from ..workflows.train import train


def print_preview(data):
    print("분할 시드:", data.record["seed"])
    for name, split in data.record["splits"].items():
        print(name, split["count"], "개", split["label_counts"])
    texts, ids = dataset.texts_and_ids(data.rows["train"])
    print("첫 번째 학습 입력:\n", texts[0], sep="")
    print("첫 번째 정답 번호:", ids[0])
    print("첫 번째 정답 라벨:", LABELS[ids[0]])


def run_report(kind, dataset_path, model_dir, result_dir):
    subprocess.run(
        [
            sys.executable,
            str(artifacts.ROOT / "model_report.py"),
            kind,
            "--dataset",
            str(dataset_path),
            "--model-dir",
            str(model_dir),
            "--result-dir",
            str(result_dir),
        ],
        check=True,
    )


def run_training(
    config,
    fit,
    *,
    kind,
    model_path,
    summary_path,
    include_test,
    dataset_path,
    model_dir,
    result_dir,
):
    started = perf_counter()
    data = dataset.prepare_data(dataset_path, config.seed)
    print_preview(data)
    result = train(data, fit, started_at=started)
    summary = artifacts.training_summary(result, data, include_test=include_test)
    artifacts.save_training(result, summary, model_path, summary_path)
    print("테스트 정확도:", round(result.test_scores["accuracy"], 4))
    print("테스트 Macro F1:", round(result.test_scores["macro_f1"], 4))
    print("모델 저장 위치:", model_path)
    run_report(kind, dataset_path, model_dir, result_dir)
    return summary


def run_transformer(
    config,
    *,
    dataset_path=dataset.DATASET_PATH,
    model_dir=artifacts.MODEL_DIR,
    result_dir=artifacts.RESULT_DIR,
):
    # 예제 설정은 데이터 준비나 다운로드 전에 안내한다.
    if (
        config.model_name == "모델명 입력"
        or config.model_folder == "결과 저장 폴더 명 입력"
    ):
        raise ValueError("예제의 model_name과 model_folder를 실제 값으로 설정하세요.")
    output = model_dir / config.model_folder
    return run_training(
        config,
        partial(transformer.fit, config=config),
        kind=config.model_folder,
        model_path=output,
        summary_path=output / "training_summary.json",
        include_test=True,
        dataset_path=dataset_path,
        model_dir=model_dir,
        result_dir=result_dir,
    )


def run_tfidf(
    config,
    *,
    dataset_path=dataset.DATASET_PATH,
    model_dir=artifacts.MODEL_DIR,
    result_dir=artifacts.RESULT_DIR,
):
    output = model_dir / "tf-idf/tfidf_logistic_regression.joblib"
    return run_training(
        config,
        partial(tfidf.fit, config=config),
        kind="tfidf_lr",
        model_path=output,
        summary_path=output.with_suffix(".json"),
        include_test=False,
        dataset_path=dataset_path,
        model_dir=model_dir,
        result_dir=result_dir,
    )


def training_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--preview-questions",
        "--preview-documents",
        dest="preview_questions",
        action="store_true",
    )
    parser.add_argument("--dataset", type=Path, default=dataset.DATASET_PATH)
    parser.add_argument("--model-dir", type=Path, default=artifacts.MODEL_DIR)
    parser.add_argument("--result-dir", type=Path, default=artifacts.RESULT_DIR)
    return parser


def _main(config, run, argv, description):
    args = training_parser(description).parse_args(argv)
    if args.preview_questions:
        print_preview(dataset.prepare_data(args.dataset, config.seed))
        return
    run(
        config,
        dataset_path=args.dataset,
        model_dir=args.model_dir,
        result_dir=args.result_dir,
    )


def transformer_main(config, argv=None):
    _main(config, run_transformer, argv, "요청 처리 Transformer 분류 학습")


def tfidf_main(config, argv=None):
    _main(config, run_tfidf, argv, "TF-IDF + 로지스틱 회귀 학습")
