"""학습 조립: 기존 폴더 확인 → 준비·학습 → 검증된 모델 게시 → 실험 기록."""

import shutil
from dataclasses import asdict, replace
from functools import partial
from time import perf_counter
from uuid import uuid4

from contracts.classification import LABELS

from .. import artifacts, dataset, storage, tracking
from ..models import tfidf, transformer
from ..models.presets import load_bundle
from ..workflows.train import train


def print_preview(data, config, artifact_root, name):
    print("입력: question / 라벨:", ", ".join(LABELS))
    print("선택 기준: validation Macro F1 / test 예측·점수 공개: 없음")
    groups = [{r["group_id"] for r in rows} for rows in data.rows.values()]
    print(
        "분할 간 그룹 중복:",
        any(a & b for i, a in enumerate(groups) for b in groups[i + 1 :]),
    )
    if isinstance(config, transformer.TransformerConfig):
        print(
            "후보 초기화 수:",
            len(config.max_lengths) * len(config.learning_rates),
            "후보별 epoch:",
            config.epochs,
        )
    else:
        print("C 후보 수:", len(config.c_candidates), "epoch: 해당 없음")
    print("모델 저장 위치:", artifact_root / "models" / name)
    print("분할 시드:", data.record["seed"])
    for split_name, split in data.record["splits"].items():
        print(split_name, split["count"], "개", split["label_counts"])
    texts, ids = dataset.texts_and_ids(data.rows["train"])
    print("첫 번째 학습 입력:\n", texts[0], sep="")
    print("첫 번째 정답 번호:", ids[0])
    print("첫 번째 정답 라벨:", LABELS[ids[0]])


def execute(
    name,
    config,
    *,
    artifact_root=storage.DEFAULT_ROOT,
    dataset_path=dataset.DATASET_PATH,
    force=False,
    preview=False,
):
    if (
        not preview
        and isinstance(config, transformer.TransformerConfig)
        and ("입력" in config.model_name or "입력" in config.model_folder)
    ):
        raise ValueError("예제의 model_name과 model_folder를 실제 값으로 설정하세요.")
    from .main import command_hint

    artifact_root = artifact_root.resolve()
    train_hint = command_hint("train", name, artifact_root, dataset_path, force=True)
    eval_hint = command_hint("eval", name, artifact_root, dataset_path)
    bundle = artifact_root / "models" / name
    if preview:
        data = dataset.prepare_data(dataset_path, config.seed)
        print_preview(data, config, artifact_root, name)
        return None
    with storage.lock(artifact_root, name):
        storage.check_pending(artifact_root, name)
        if bundle.exists() and not force:
            print(
                "기존 모델 폴더가 있어 학습을 생략합니다 (조건·무결성 미검사):", bundle
            )
            print(f"평가: {eval_hint}")
            print(f"재학습: {train_hint} 또는 다른 --artifact-root")
            return None
        data = dataset.prepare_data(dataset_path, config.seed)
        model_id = uuid4().hex
        with tracking.start_run(
            artifact_root, name, "train", data, model_id=model_id
        ) as run:
            run.params(asdict(config))
            run.tags(selection="validation Macro F1", model_path=bundle)
            started = perf_counter()
            if isinstance(config, transformer.TransformerConfig):
                from huggingface_hub import HfApi

                revision = config.revision or HfApi().model_info(config.model_name).sha
                if not revision:
                    raise ValueError("기반 모델 revision을 확인할 수 없습니다.")
                fit = partial(
                    transformer.fit, config=replace(config, revision=revision)
                )
                run.tags(resolved_revision=revision)
            else:
                fit = partial(tfidf.fit, config=config)
            result = train(
                data.rows["train"], data.rows["validation"], fit, started_at=started
            )
            summary = artifacts.training_summary(result, data)
            temporary = storage.stage(artifact_root, name)
            try:
                model_path = (
                    temporary / "model.joblib" if name == "tfidf" else temporary
                )
                artifacts.save_training(
                    result, summary, model_path, temporary / "training_summary.json"
                )
                load_bundle(name, temporary, summary)(
                    data.rows["validation"][0]["question"]
                )
                storage.complete_manifest(
                    temporary, name, model_id=model_id, training_run_id=run.run_id
                )
                storage.validate_bundle(temporary, name)
                storage.publish(artifact_root, "models", name, temporary)
                run.saved_path = bundle
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            run.tags(training_run_id=run.run_id)
            run.training(summary)
            print("모델 저장 위치:", bundle)
            print("MLflow 학습 run:", run.run_id)
            print(f"저장 모델 평가: {eval_hint}")
        return summary


def run_training(config=None, argv=None):
    """기존 모델별 실행 파일의 호환 경계. 인자는 이 경계에서 한 번만 읽는다."""
    from .main import invoke, training_parser

    parser = training_parser(compatibility=True, fixed=config is not None)
    args = parser.parse_args(argv)
    if config is not None:
        name = (
            config.model_folder
            if isinstance(config, transformer.TransformerConfig)
            else "tfidf"
        )
        return execute(
            name,
            config,
            artifact_root=args.artifact_root,
            dataset_path=args.dataset,
            force=args.force,
            preview=args.preview_questions,
        )
    return invoke(args)


def main(argv=None):
    from .main import boundary

    boundary(lambda: run_training(argv=argv))


if __name__ == "__main__":
    main()
