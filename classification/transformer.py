"""Transformer의 train 학습 → validation 선택 → 선택 상태 복원."""

import argparse
import math
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import torch
from sklearn.metrics import f1_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from classification.dataset import (
    DATASET_PATH,
    prepare_data,
    prepare_data_from_manifest,
)
from classification.persistence import file_sha, new_destination, split_id, write_json
from contracts.classification import LABELS

MODEL_NAME = "klue/roberta-small"


def encode(tokenizer, texts, max_length, device):
    return tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
        return_token_type_ids=False,
    ).to(device)


class TransformerClassifier:
    """저장된 tokenizer와 라벨 순서를 함께 사용하는 예측 객체."""

    def __init__(self, model, tokenizer, max_length=256, batch_size=4):
        self.model = model
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.batch_size = batch_size
        self.classes_ = [
            model.config.id2label[i] for i in range(model.config.num_labels)
        ]

    def predict(self, texts):
        self.model.eval()
        device = next(self.model.parameters()).device
        predictions = []
        with torch.no_grad():
            for start in range(0, len(texts), self.batch_size):
                batch = encode(
                    self.tokenizer,
                    texts[start : start + self.batch_size],
                    self.max_length,
                    device,
                )
                logits = self.model(**batch).logits
                predictions.extend(self.classes_[i] for i in logits.argmax(-1).tolist())
        return np.asarray(predictions)


def select_model(
    train_rows,
    validation_rows,
    *,
    model_name=MODEL_NAME,
    revision=None,
    learning_rates=(2e-5,),
    epochs=3,
    batch_size=4,
    max_length=256,
    seed=20261013,
    device="cpu",
):
    """test를 받지 않는다. 동점이면 앞선 후보/epoch를 유지한다."""
    if not train_rows or not validation_rows:
        raise ValueError("train과 validation이 필요합니다.")

    if (
        min(epochs, batch_size, max_length) <= 0
        or not learning_rates
        or any(not math.isfinite(lr) or lr <= 0 for lr in learning_rates)
    ):
        raise ValueError("epoch, batch, 길이, 학습률은 양수여야 합니다.")

    tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
    label_to_id = {label: i for i, label in enumerate(LABELS)}
    best_score, best_state, best_choice = -1.0, None, None
    trials = []
    for candidate, lr in enumerate(learning_rates):
        # 후보마다 같은 초기화와 배치 순서를 사용한다.
        torch.manual_seed(seed)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_name,
            revision=revision,
            num_labels=len(LABELS),
            label2id=label_to_id,
            id2label=dict(enumerate(LABELS)),
        ).to(device)

        fitted = TransformerClassifier(model, tokenizer, max_length, batch_size)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
        generator = torch.Generator().manual_seed(seed)

        for epoch in range(1, epochs + 1):
            model.train()
            loss_sum = 0.0
            order = torch.randperm(len(train_rows), generator=generator).tolist()
            for start in range(0, len(order), batch_size):
                rows = [train_rows[i] for i in order[start : start + batch_size]]
                inputs = encode(
                    tokenizer, [r["question"] for r in rows], max_length, device
                )
                targets = torch.tensor(
                    [label_to_id[r["label"]] for r in rows],
                    dtype=torch.long,
                    device=device,
                )
                optimizer.zero_grad(set_to_none=True)
                loss = model(**inputs, labels=targets).loss
                if not torch.isfinite(loss).item():
                    raise ValueError("학습 loss가 유한하지 않습니다.")
                loss.backward()
                optimizer.step()
                loss_sum += loss.item() * len(rows)
            optimizer.zero_grad(set_to_none=True)
            predictions = fitted.predict([r["question"] for r in validation_rows])
            score = float(
                f1_score(
                    [r["label"] for r in validation_rows],
                    predictions,
                    labels=LABELS,
                    average="macro",
                    zero_division=0,
                )
            )
            trial = {
                "candidate": candidate,
                "learning_rate": lr,
                "epoch": epoch,
                "train_loss": loss_sum / len(train_rows),
                "validation_macro_f1": score,
            }
            trials.append(trial)
            print(trial, flush=True)
            if score > best_score:
                best_score = score
                best_choice = {"learning_rate": lr, "epoch": epoch}
                best_state = {
                    name: value.detach().cpu().clone()
                    for name, value in model.state_dict().items()
                }
        # 다음 후보 로딩 전에 GPU 모델과 optimizer 참조를 해제한다.
        if candidate + 1 < len(learning_rates):
            del optimizer, fitted, model
    model.load_state_dict(best_state)
    model.eval()
    return TransformerClassifier(model, tokenizer, max_length, batch_size), {
        "selected": best_choice,
        "validation_macro_f1": best_score,
        "trials": trials,
        "resolved_revision": getattr(model.config, "_commit_hash", None),
    }


def load_bundle(bundle, metadata):
    model = AutoModelForSequenceClassification.from_pretrained(
        bundle, local_files_only=True
    )
    tokenizer = AutoTokenizer.from_pretrained(bundle, local_files_only=True)
    return TransformerClassifier(
        model,
        tokenizer,
        metadata["config"]["max_length"],
        metadata["config"]["batch_size"],
    )


def save_bundle(fitted, destination, metadata, check_texts):
    if not check_texts:
        raise ValueError("재로딩 검증 질문이 필요합니다.")
    with (
        new_destination(destination) as target,
        tempfile.TemporaryDirectory(dir=target.parent, prefix=".staging-") as temp,
    ):
        stage = Path(temp) / "bundle"
        fitted.model.save_pretrained(stage)
        fitted.tokenizer.save_pretrained(stage)
        restored = load_bundle(stage, metadata)
        if (
            restored.predict(check_texts).tolist()
            != fitted.predict(check_texts).tolist()
        ):
            raise ValueError("저장 전후 예측이 다릅니다.")
        write_json(stage / "metadata.json", {**metadata, "complete": True})
        stage.rename(target)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Transformer 학습/validation 선택. test 예측 없음."
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument(
        "--split-manifest", type=Path, help="고정 분할 JSON; 생략 시 기존 그룹 분할"
    )
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--revision")
    parser.add_argument("--learning-rates", type=float, nargs="+", default=[2e-5])
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20261013)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument(
        "--output", type=Path, help="새 모델 폴더. 생략하면 저장하지 않음"
    )
    args = parser.parse_args(argv)
    if args.output is not None and args.output.exists():
        parser.error(f"기존 경로를 보존합니다: {args.output}")
    sha = file_sha(args.dataset)
    manifest_sha = file_sha(args.split_manifest) if args.split_manifest else None
    splits = (
        prepare_data_from_manifest(args.dataset, args.split_manifest)
        if args.split_manifest
        else prepare_data(args.dataset, args.seed)
    )
    fitted, selection = select_model(
        splits["train"],
        splits["validation"],
        model_name=args.model,
        revision=args.revision,
        learning_rates=args.learning_rates,
        epochs=args.epochs,
        batch_size=args.batch_size,
        max_length=args.max_length,
        seed=args.seed,
        device=args.device,
    )
    if file_sha(args.dataset) != sha:
        raise ValueError("실행 중 데이터가 변경되었습니다. 저장하지 않습니다.")
    if args.split_manifest and file_sha(args.split_manifest) != manifest_sha:
        raise ValueError("실행 중 분할 manifest가 변경되었습니다. 저장하지 않습니다.")
    if args.output is not None:
        ids = {name: [r["question_id"] for r in rows] for name, rows in splits.items()}
        metadata = {
            "schema_version": 1,
            "model_name": "learning_transformer",
            "model_id": uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
            "labels": fitted.classes_,
            "dataset_sha256": sha,
            "question_ids": ids,
            "split_id": split_id(ids),
            "split_manifest_sha256": manifest_sha,
            "seed": args.seed,
            "config": {
                "pretrained_model": args.model,
                "revision": args.revision,
                "max_length": args.max_length,
                "batch_size": args.batch_size,
                "epochs": args.epochs,
                "learning_rates": args.learning_rates,
                "device": args.device,
            },
            "selection": selection,
            "test_exposure": "이미 열람한 합성 개발 평가 자료",
        }
        save_bundle(
            fitted,
            args.output,
            metadata,
            [r["question"] for r in splits["validation"][:4]],
        )
        print("모델 저장:", args.output)


if __name__ == "__main__":
    main()
