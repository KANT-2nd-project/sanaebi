"""Transformer 학습·선택과 로컬 모델 I/O. 실험 실행·보고서는 알지 못한다."""

from dataclasses import dataclass

from contracts.classification import LABELS as ROUTING_LABELS

from ..types import DEFAULT_SEED, FittedModel, Prediction, Predictor, validate_label

LABELS = list(ROUTING_LABELS)


def texts_and_ids(rows):
    return [r["question"] for r in rows], [LABELS.index(r["label"]) for r in rows]


@dataclass(frozen=True)
class TransformerConfig:
    """모델별 설정. 후보의 순서도 실험 조건의 일부이므로 유지한다."""

    model_name: str
    model_folder: str
    max_lengths: tuple[int, ...] = (256, 384)
    learning_rates: tuple[float, ...] = (2e-5, 5e-5)
    batch_size: int = 4
    epochs: int = 10
    seed: int = DEFAULT_SEED


@dataclass
class BestCheckpoint:
    """검증 Macro F1의 엄격한 개선만 채택한다. 동점은 먼저 선택한 후보 유지."""

    score: float = -1.0
    max_length: int | None = None
    learning_rate: float | None = None
    epoch: int | None = None
    state: dict | None = None

    def consider(self, model, *, score, max_length, learning_rate, epoch):
        if score > self.score:
            self.score = score
            self.max_length = max_length
            self.learning_rate = learning_rate
            self.epoch = epoch
            # 이후 학습이 보관한 텐서를 변경하지 않게 별도 CPU 복사본을 만든다.
            self.state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
            }

    def restore(self, model):
        if self.state is None:
            raise ValueError("선택할 검증 결과가 없습니다.")
        model.load_state_dict(self.state)
        model.eval()


def make_loader(tokenizer, texts, label_ids, max_length, batch_size, shuffle=False):
    """질문을 토큰화하고 배치별 최장 길이로 패딩한다. 정답은 [B] 텐서다."""
    from torch.utils.data import DataLoader
    from transformers import DataCollatorWithPadding

    padding_collator = DataCollatorWithPadding(tokenizer=tokenizer, padding=True)

    def collate_batch(questions):
        batch = padding_collator(questions)
        return batch["input_ids"], batch["attention_mask"], batch["labels"]

    encoded = tokenizer(
        texts,
        padding=False,
        truncation=True,
        max_length=max_length,
        return_token_type_ids=False,
    )
    questions = [
        {
            "input_ids": encoded["input_ids"][index],
            "attention_mask": encoded["attention_mask"][index],
            "label": label_id,
        }
        for index, label_id in enumerate(label_ids)
    ]
    return DataLoader(
        questions, batch_size=batch_size, shuffle=shuffle, collate_fn=collate_batch
    )


def train_epoch(model, loader, optimizer, device):
    """한 epoch 가중치를 갱신하고 질문 수로 가중한 평균 loss를 반환한다."""
    model.train()
    total_loss = 0.0
    train_count = 0
    for step, (input_ids, attention_mask, targets) in enumerate(loader, start=1):
        optimizer.zero_grad()
        # 입력·마스크 [B, L] → logits [B, 3], 정답 [B] → scalar loss
        output = model(
            input_ids=input_ids.to(device),
            attention_mask=attention_mask.to(device),
            labels=targets.to(device),
        )
        loss = output.loss
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * len(targets)
        train_count += len(targets)
        if step % 10 == 0 or step == len(loader):
            print(f"배치 {step}/{len(loader)}")
    return total_loss / train_count


def predict_ids(model, loader, device):
    """정답을 모델에 전달하지 않고 [B, 3]의 argmax 번호를 모은다."""
    import torch

    model.eval()
    predictions = []
    with torch.inference_mode():
        for input_ids, attention_mask, _ in loader:
            output = model(
                input_ids=input_ids.to(device),
                attention_mask=attention_mask.to(device),
            )
            predictions.extend(output.logits.argmax(dim=1).cpu().tolist())
    return predictions


def select_transformer(config, tokenizer, splits, device):
    """train만 학습하고 validation 점수로 선택한다. test에는 접근하지 않는다."""
    import torch
    from sklearn.metrics import accuracy_score, f1_score
    from transformers import AutoModelForSequenceClassification

    train_texts, train_ids = texts_and_ids(splits["train"])
    validation_texts, validation_ids = texts_and_ids(splits["validation"])
    id2label = dict(enumerate(LABELS))
    label2id = {label: index for index, label in id2label.items()}
    best = BestCheckpoint()
    trials = []
    for max_length in config.max_lengths:
        # 기존 순서 유지: 길이별 loader 생성 → 학습률별 시드·모델 초기화.
        train_loader = make_loader(
            tokenizer,
            train_texts,
            train_ids,
            max_length,
            config.batch_size,
            shuffle=True,
        )
        validation_loader = make_loader(
            tokenizer, validation_texts, validation_ids, max_length, config.batch_size
        )
        for learning_rate in config.learning_rates:
            torch.manual_seed(config.seed)
            model = AutoModelForSequenceClassification.from_pretrained(
                config.model_name,
                num_labels=len(LABELS),
                id2label=id2label,
                label2id=label2id,
            ).to(device)
            optimizer = torch.optim.AdamW(
                model.parameters(), lr=learning_rate, weight_decay=0.01
            )
            for epoch in range(1, config.epochs + 1):
                print(
                    f"최대 토큰 수 {max_length}, 학습률 {learning_rate}, epoch {epoch}/{config.epochs}"
                )
                train_loss = train_epoch(model, train_loader, optimizer, device)
                predictions = predict_ids(model, validation_loader, device)
                accuracy = accuracy_score(validation_ids, predictions)
                score = f1_score(
                    validation_ids,
                    predictions,
                    labels=list(range(len(LABELS))),
                    average="macro",
                    zero_division=0,
                )
                print("평균 학습 손실:", round(train_loss, 4))
                print("검증 정확도:", round(accuracy, 4))
                print("검증 Macro F1:", round(score, 4))
                trials.append(
                    {
                        "max_length": max_length,
                        "learning_rate": learning_rate,
                        "epoch": epoch,
                        "train_loss": train_loss,
                        "validation_accuracy": accuracy,
                        "validation_macro_f1": score,
                    }
                )
                best.consider(
                    model,
                    score=score,
                    max_length=max_length,
                    learning_rate=learning_rate,
                    epoch=epoch,
                )
    # 마지막 후보의 가중치가 아니라 검증 최고 시점으로 복원한다.
    best.restore(model)
    return model, best, trials


def transformer_predictor(model, tokenizer, settings) -> Predictor:
    """기존 평가의 패딩·길이 규칙을 보존한다. 출력 번호는 모델 매핑으로 해석한다."""
    import torch

    model.eval()

    def predict(text: str) -> Prediction:
        encoded = tokenizer(
            text,
            padding=False
            if settings.get("padding") == "longest_in_batch"
            else "max_length",
            truncation=True,
            max_length=settings.get("max_length", 192),
            return_tensors="pt",
        )
        with torch.inference_mode():
            output = model(
                input_ids=encoded["input_ids"], attention_mask=encoded["attention_mask"]
            )
        return Prediction(
            validate_label(model.config.id2label[output.logits.argmax(dim=1).item()])
        )

    return predict


def fit(train_rows, validation_rows, config, *, device=None):
    """train/validation에서 선택하고, 모델·예측·명시적 저장 함수를 반환한다."""
    if (
        config.model_name == "모델명 입력"
        or config.model_folder == "결과 저장 폴더 명 입력"
    ):
        raise ValueError("예제의 model_name과 model_folder를 실제 값으로 설정하세요.")
    if not config.max_lengths or not config.learning_rates or config.epochs < 1:
        raise ValueError("학습 후보와 1 이상의 epochs가 필요합니다.")
    import torch
    from transformers import AutoTokenizer

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(config.model_name)
    model, best, trials = select_transformer(
        config, tokenizer, {"train": train_rows, "validation": validation_rows}, device
    )
    settings = {
        "model_name": config.model_name,
        "model_folder": config.model_folder,
        "labels": LABELS,
        "batch_size": config.batch_size,
        "learning_rate": best.learning_rate,
        "best_epoch": best.epoch,
        "validation_macro_f1": best.score,
        "max_length": best.max_length,
        "max_length_candidates": list(config.max_lengths),
        "padding": "longest_in_batch",
        "input_condition": "question 열만 입력, 선택한 최대 토큰 수 초과 시 잘림",
        "seed": config.seed,
        "training_device": device,
        "trials": trials,
    }

    def predict_batch(texts):
        loader = make_loader(
            tokenizer, texts, [0] * len(texts), best.max_length, config.batch_size
        )
        ids = predict_ids(model, loader, device)
        return [
            Prediction(validate_label(model.config.id2label[index])) for index in ids
        ]

    def save(path):
        path.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(path, safe_serialization=True)
        tokenizer.save_pretrained(path)

    return FittedModel(
        lambda text: predict_batch([text])[0], save, settings, predict_batch
    )


def load(model_path, settings, *, cpu_threads=4) -> Predictor:
    """저장 파일만 읽고 CPU 예측 함수를 반환한다. 다운로드하지 않는다."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(cpu_threads)
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path, local_files_only=True
    ).to("cpu")
    return transformer_predictor(model, tokenizer, settings)
