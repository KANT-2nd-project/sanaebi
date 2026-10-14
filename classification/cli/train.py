"""학습 조립: 준비 → 재사용 검사 → 학습 → 검증된 모델 게시."""

import shutil
from dataclasses import replace
from functools import partial
from time import perf_counter

from contracts.classification import LABELS

from .. import artifacts, dataset, storage
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
    data = dataset.prepare_data(dataset_path, config.seed)
    if preview:
        print_preview(data, config, artifact_root, name)
        print("예정 모델 위치:", artifact_root / "models" / name)
        return None
    conditions = storage.request_conditions(config, data)
    bundle = artifact_root / "models" / name
    with storage.lock(artifact_root, name):
        storage.recover(artifact_root, "models", name)
        storage.recover(artifact_root, "results", name)
        for split in ("validation", "test"):
            storage.recover(artifact_root, "results", f"{name}/{split}")
        if bundle.exists() and not force:
            try:
                manifest = storage.validate_bundle(bundle, name)
            except ValueError as error:
                raise ValueError(f"{error}\n다시 학습: {train_hint}") from error
            if manifest["fingerprint"] != storage.digest(conditions):
                changed = [
                    key
                    for key in conditions
                    if conditions[key] != manifest["conditions"].get(key)
                ]
                raise ValueError(
                    f"학습 조건이 다릅니다: {', '.join(changed)}. {train_hint} 또는 다른 --artifact-root를 사용하세요."
                )
            print("동일 조건의 정상 모델이 있어 학습을 생략했습니다:", bundle)
            if manifest["provenance"]["kind"] == "adopted":
                print(
                    "기존 모델 채택, 과거 환경 일부 미확인. 이전 시점 이후 조건을 비교했습니다."
                )
            print("모델 ID:", manifest["model_id"])
            try:
                report = artifacts.read_json(
                    artifact_root / "results" / name / "validation" / "metrics.json"
                )
                result_status = (
                    "현재 모델과 연결됨"
                    if report.get("model_id") == manifest["model_id"]
                    else "이전 모델의 결과"
                )
            except (OSError, ValueError, AttributeError):
                result_status = "없거나 읽을 수 없음"
            print("평가 결과:", result_status)
            print(f"평가: {eval_hint}")
            return artifacts.read_json(bundle / "training_summary.json")
        backup_old = True
        if bundle.exists():
            try:
                storage.validate_bundle(bundle, name)
            except ValueError:
                backup_old = (
                    False  # 손상 묶음은 staging에 보존하고 정상 백업을 유지한다.
                )
        started = perf_counter()
        if isinstance(config, transformer.TransformerConfig):
            # 새 학습 때만 revision을 조회한다. 같은 SHA로 tokenizer와 model을 읽는다.
            from huggingface_hub import HfApi

            revision = config.revision or HfApi().model_info(config.model_name).sha
            if not revision:
                raise ValueError("기반 모델 revision을 확인할 수 없습니다.")
            effective = replace(config, revision=revision)
            fit = partial(transformer.fit, config=effective)
        else:
            revision = None
            fit = partial(tfidf.fit, config=config)
        result = train(
            data.rows["train"], data.rows["validation"], fit, started_at=started
        )
        summary = artifacts.training_summary(result, data)
        temporary = storage.stage(artifact_root, name)
        try:
            model_path = temporary / "model.joblib" if name == "tfidf" else temporary
            artifacts.save_training(
                result, summary, model_path, temporary / "training_summary.json"
            )
            load_bundle(name, temporary, summary)(
                data.rows["validation"][0]["question"]
            )
            storage.complete_manifest(
                temporary,
                name,
                conditions,
                storage.provenance("trained", resolved_revision=revision),
            )
            storage.validate_bundle(temporary, name)
            storage.publish(
                artifact_root, "models", name, temporary, backup_old=backup_old
            )
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        if (artifact_root / "results" / name / "validation" / "metrics.json").exists():
            print(
                "기존 평가 결과는 이전 모델의 결과입니다. eval로 새 모델을 평가하세요."
            )
        print("모델 저장 위치:", bundle)
        print(f"저장 모델 평가: {eval_hint}")
    # 비교 페이지가 구형 모델의 점수를 현재 값으로 표시하지 않도록 갱신한다.
    from ..evaluation.comparison import refresh_comparison

    refresh_comparison(artifact_root)
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
