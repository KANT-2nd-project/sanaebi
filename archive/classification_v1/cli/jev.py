"""Jev 단일 질문·preview·API 평가 조립. 기존 호출 계약을 보존한다."""

import argparse
import shutil
from pathlib import Path
from uuid import uuid4

from contracts.classification import LABELS

from .. import artifacts, dataset, storage, tracking
from ..models import jev, jev_prompt
from ..types import MeasurementPolicy
from ..workflows.evaluate import evaluate_legacy_questions as evaluate_questions

REQUEST_MEASUREMENT = MeasurementPolicy("request")


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
    *,
    dataset_path=dataset.DATASET_PATH,
    result_dir=None,
    artifact_root=storage.DEFAULT_ROOT,
    predict=None,
):
    jev.require_credentials()
    data = prepare_jev_data(dataset_path)
    count = sum(len(ids) for ids in jev_prompt.EXAMPLE_QUESTION_IDS.values())
    output = (
        (Path(result_dir) / jev_prompt.MODEL_FOLDER)
        if result_dir is not None
        else (artifact_root / "results" / "jev")
    )
    model_id = uuid4().hex
    publish_root = output.parent.parent
    with storage.lock(publish_root, "jev"):
        storage.check_pending(publish_root, "jev")
        with tracking.start_run(
            artifact_root, "jev", "eval", data, split="both", model_id=model_id
        ) as run:
            result = evaluate_questions(
                data.rows,
                jev.predict if predict is None else predict,
                REQUEST_MEASUREMENT,
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
            report.update(
                model_id=model_id,
                tracking_run_id=run.run_id,
                evaluated_split="both",
                test_exposure="이미 열람한 개발 평가 자료",
                data_review="미기록",
            )
            # result-dir 호환 옵션도 같은 파일시스템의 임시 폴더에서 완성한 뒤 교체한다.
            category = output.parent.name
            temporary = storage.stage(publish_root, "jev")
            try:
                artifacts.save_json(temporary / "metrics.json", report)
                artifacts.save_json(temporary / "predictions.json", result.predictions)
                artifacts.save_probability_csv(temporary, result.predictions)
                storage.publish(publish_root, category, output.name, temporary)
                run.saved_path = output
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            run.params(
                {
                    "requested_model": jev_prompt.MODEL_NAME,
                    "prompt_examples_count": count,
                }
            )
            run.evaluation(report, result.predictions)
            print("Jev 평가 결과:", output)
            print("MLflow 평가 run:", run.run_id)
    return report


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
    parser.add_argument("--result-dir", type=Path, default=None)
    parser.add_argument("--artifact-root", type=Path, default=storage.DEFAULT_ROOT)
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
        evaluate_jev(
            dataset_path=args.dataset,
            result_dir=args.result_dir,
            artifact_root=args.artifact_root.resolve(),
        )
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
            artifacts.report_dir(
                jev_prompt.MODEL_FOLDER,
                args.result_dir or args.artifact_root / "results",
            )
            / "single_prediction.json"
        )
        artifacts.save_json(output, content)
        print("질문 입력:", jev_prompt.QUESTION)
        print("분류:", prediction.label)
        for label, probability in (prediction.probabilities or {}).items():
            print(f"{label}: {probability:.2%}")
        print("저장 위치:", output)
