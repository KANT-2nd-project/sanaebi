# BERT 요청 처리 질문 분류 모델 학습

import csv
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import torch
from question_split import (
    LABELS,
    RANDOM_SEED,
    make_split_record,
    question_input,
    split_questions,
)
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from torch.utils.data import DataLoader
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
)

##### 설정 #####

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "dataset.csv"


##### 질문 CSV 읽기·정렬 확인 #####


def read_question_rows():
    with DATASET_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        question_rows = list(csv.DictReader(file))

    # CSV의 행 순서가 바뀌어도 같은 순서로 데이터를 준비
    question_rows.sort(key=lambda row: row["question_id"])
    return question_rows


##### 요청 처리 분류 모델 설정 #####

MODEL_NAME = "모델명 입력"  # 사용할 한국어 사전학습 BERT
MODEL_FOLDER = (
    "결과 저장 폴더 명 입력"  # 모델·결과 저장 폴더 이름 (예: bert, koelectra)
)


MAX_LENGTHS = [256, 384]  # 비교할 최대 토큰 수 (특수 토큰 포함)
BATCH_SIZE = 4  # 한 번에 꺼낼 문장 수
LEARNING_RATES = [2e-5, 5e-5]  # 비교할 학습률: 0.00002, 0.00005
EPOCHS = 10  # 실험할 전체 학습 데이터 반복 횟수 (최적 횟수는 검증으로 판단)
SEED = RANDOM_SEED  # 데이터 분할과 모델 초기화에 사용하는 고정 난수값
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"  # 사용할 장치
selection_started = perf_counter()  # 데이터 준비부터 후보 학습·선택까지의 시간

##### 학습·검증·테스트 데이터 나누기 #####

question_rows = read_question_rows()
splits = split_questions(question_rows, seed=RANDOM_SEED)
train_rows = splits["train"]
validation_rows = splits["validation"]
test_rows = splits["test"]

print("전체 질문:", len(question_rows), "개 / 분할 시드:", RANDOM_SEED)
print("학습 데이터:", len(train_rows), "개")
print("검증 데이터:", len(validation_rows), "개")
print("테스트 데이터:", len(test_rows), "개")

##### 모델 결과에 포함할 데이터 분할 기록 준비 #####

split_record = make_split_record(splits, DATASET_PATH, seed=RANDOM_SEED)

##### 질문 입력과 정답 번호 준비 #####

train_texts = []  # 학습 질문 목록
train_label_ids = []  # 학습 정답 번호 목록
for row in train_rows:
    # question 열만 입력으로 사용 (ID·그룹·출처·정답은 제외)
    train_texts.append(question_input(row))
    train_label_ids.append(LABELS.index(row["label"]))

validation_texts = []  # 검증 질문 목록
validation_label_ids = []  # 검증 정답 번호 목록
for row in validation_rows:
    validation_texts.append(question_input(row))
    validation_label_ids.append(LABELS.index(row["label"]))

test_texts = []  # 테스트 질문 목록
test_label_ids = []  # 테스트 정답 번호 목록
for row in test_rows:
    test_texts.append(question_input(row))
    test_label_ids.append(LABELS.index(row["label"]))

# 분할과 입력 준비만 확인하고 종료 (모델 학습 없음)
if "--preview-questions" in sys.argv or "--preview-documents" in sys.argv:
    for name, rows in splits.items():
        print(
            name,
            {label: sum(row["label"] == label for row in rows) for label in LABELS},
        )
    print("첫 번째 학습 입력:\n", train_texts[0], sep="")
    print("첫 번째 정답 번호:", train_label_ids[0])
    print("첫 번째 정답 라벨:", LABELS[train_label_ids[0]])
    raise SystemExit(0)

##### 토크나이저 불러오기 #####

# 선택한 BERT가 사용하는 토큰 분리 규칙과 어휘 목록 불러오기
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

##### 배치별 패딩과 데이터 로더 준비 #####

# 배치를 꺼낼 때 해당 배치에서 가장 긴 질문까지만 패딩
padding_collator = DataCollatorWithPadding(tokenizer=tokenizer, padding=True)


def collate_batch(questions):
    batch = padding_collator(questions)
    # 기존 학습 반복문에서 사용하던 토큰 번호·마스크·정답 순서로 반환
    return batch["input_ids"], batch["attention_mask"], batch["labels"]


def make_loader(texts, label_ids, max_length, shuffle=False):
    encoded = tokenizer(
        texts,
        padding=False,  # 여기서는 패딩하지 않고 각 질문의 길이를 유지
        truncation=True,  # 설정한 최대 토큰 수를 넘는 질문만 자르기
        max_length=max_length,
        return_token_type_ids=False,
    )
    questions = []
    for index, label_id in enumerate(label_ids):
        questions.append(
            {
                "input_ids": encoded["input_ids"][index],
                "attention_mask": encoded["attention_mask"][index],
                "label": label_id,
            }
        )
    return DataLoader(
        questions,
        batch_size=BATCH_SIZE,
        shuffle=shuffle,
        collate_fn=collate_batch,  # 배치로 묶으면서 패딩·텐서 변환
    )


##### 모델의 라벨 번호 설정 #####

id2label = {}  # 번호 → 카테고리 이름
label2id = {}  # 카테고리 이름 → 번호
for index, label in enumerate(LABELS):
    id2label[index] = label
    label2id[label] = index

##### 입력 길이·학습률별 학습과 검증 #####

best_score = -1.0  # 첫 번째 검증 결과부터 선택할 수 있도록 초기화
best_max_length = None
best_learning_rate = None
best_epoch = None
best_state = None  # 가장 좋은 시점의 가중치 보관
trials = []  # 입력 길이·학습률·epoch별 결과를 HTML 표에 표시

# 입력 길이는 검증 점수로 선택하고 테스트는 선택 완료 후 한 번만 평가
for max_length in MAX_LENGTHS:
    train_loader = make_loader(train_texts, train_label_ids, max_length, shuffle=True)
    validation_loader = make_loader(validation_texts, validation_label_ids, max_length)

    # 학습률마다 모델과 optimizer를 새로 준비해 독립적으로 비교
    for learning_rate in LEARNING_RATES:
        print("\n최대 토큰 수:", max_length, "/ 학습률:", learning_rate)

        ##### BERT 분류 모델 불러오기 #####

        torch.manual_seed(SEED)  # 후보마다 같은 초기 조건에서 시작
        model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_NAME,
            num_labels=len(LABELS),  # 요청 처리 카테고리 3개의 점수를 출력하는 분류층
            id2label=id2label,
            label2id=label2id,
        )
        model = model.to(DEVICE)  # 모델을 CPU 또는 GPU로 이동
        print("사용 장치:", DEVICE)
        if DEVICE == "cuda":
            print("GPU:", torch.cuda.get_device_name(torch.cuda.current_device()))

        ##### 가중치를 변경할 도구 준비 #####

        optimizer = torch.optim.AdamW(
            model.parameters(),  # BERT 본체와 분류층의 학습 가능한 가중치
            lr=learning_rate,  # 가중치 변경 크기에 영향을 주는 학습률
            weight_decay=0.01,  # 가중치가 지나치게 커지는 것을 억제하는 설정
        )

        ##### BERT 학습 #####

        for epoch in range(1, EPOCHS + 1):
            model.train()  # 학습 모드로 설정
            total_loss = 0.0
            train_count = 0

            for step, (input_ids, attention_mask, targets) in enumerate(
                train_loader, start=1
            ):
                # gpu로 데이터 옮김
                input_ids = input_ids.to(DEVICE)  # 질문의 토큰 번호
                attention_mask = attention_mask.to(
                    DEVICE
                )  # 실제 토큰과 패딩을 구분하는 값
                targets = targets.to(DEVICE)  # 각 질문의 정답 카테고리

                optimizer.zero_grad()  # 이전 배치의 기울기 지우기
                output = model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    labels=targets,  # 정답과 비교해 손실 계산
                )
                loss = output.loss
                loss.backward()  # 가중치를 어떻게 변경할지 기울기 계산
                optimizer.step()  # 실제 가중치 변경

                total_loss += loss.item() * len(targets)
                train_count += len(targets)
                if step % 10 == 0 or step == len(train_loader):
                    print(
                        f"최대 토큰 수 {max_length}, 학습률 {learning_rate}, epoch {epoch}/{EPOCHS}: 배치 {step}/{len(train_loader)}"
                    )

            print("평균 학습 손실:", round(total_loss / train_count, 4))

            ##### epoch별 검증 #####

            model.eval()  # 평가 모드로 설정
            validation_predictions = []

            with torch.inference_mode():  # 기울기 계산 없이 예측만 수행
                for input_ids, attention_mask, _ in validation_loader:
                    output = model(
                        input_ids=input_ids.to(DEVICE),
                        attention_mask=attention_mask.to(DEVICE),
                    )
                    # 각 질문에서 점수가 가장 높은 카테고리 번호 선택
                    predicted_ids = output.logits.argmax(dim=1).cpu().tolist()
                    validation_predictions.extend(predicted_ids)

            validation_accuracy = accuracy_score(
                validation_label_ids, validation_predictions
            )
            validation_macro_f1 = f1_score(
                validation_label_ids,
                validation_predictions,
                labels=list(range(len(LABELS))),
                average="macro",  # 카테고리별 F1의 평균
                zero_division=0,
            )
            print("검증 정확도:", round(validation_accuracy, 4))
            print("검증 Macro F1:", round(validation_macro_f1, 4))
            trials.append(
                {
                    "max_length": max_length,
                    "learning_rate": learning_rate,
                    "epoch": epoch,
                    "train_loss": total_loss / train_count,
                    "validation_accuracy": validation_accuracy,
                    "validation_macro_f1": validation_macro_f1,
                }
            )

            # 최고 점수가 갱신되면 해당 시점의 가중치를 별도로 복사
            # 동점이면 먼저 선택한 결과 유지
            if validation_macro_f1 > best_score:
                best_score = validation_macro_f1
                best_max_length = max_length
                best_learning_rate = learning_rate
                best_epoch = epoch
                best_state = {
                    name: value.detach().cpu().clone()
                    for name, value in model.state_dict().items()
                }

##### 가장 좋은 모델 선택 #####

# 마지막 실험의 가중치 대신 최고 검증 점수 시점의 가중치 적용
model.load_state_dict(best_state)
model.eval()

print("선택한 최대 토큰 수:", best_max_length)
print("선택한 학습률:", best_learning_rate)
print("선택한 epoch:", best_epoch)
print("최고 검증 Macro F1:", round(best_score, 4))
selection_seconds = perf_counter() - selection_started

##### 선택한 모델의 테스트 평가 #####

test_loader = make_loader(test_texts, test_label_ids, best_max_length)
test_predictions = []
with torch.inference_mode():  # 선택한 가중치를 변경하지 않고 예측
    for input_ids, attention_mask, _ in test_loader:
        output = model(
            input_ids=input_ids.to(DEVICE),
            attention_mask=attention_mask.to(DEVICE),
        )
        predicted_ids = output.logits.argmax(dim=1).cpu().tolist()
        test_predictions.extend(predicted_ids)

test_accuracy = accuracy_score(test_label_ids, test_predictions)
test_macro_f1 = f1_score(
    test_label_ids,
    test_predictions,
    labels=list(range(len(LABELS))),
    average="macro",
    zero_division=0,
)
print("테스트 정확도:", round(test_accuracy, 4))
print("테스트 Macro F1:", round(test_macro_f1, 4))

test_matrix = confusion_matrix(
    test_label_ids, test_predictions, labels=list(range(len(LABELS)))
)
print("테스트 혼동행렬: 행은 정답, 열은 예측 / 순서:", LABELS)
for label, row in zip(LABELS, test_matrix):
    print(label, row.tolist())

##### 선택한 모델과 토크나이저 저장 #####

model_dir = Path(__file__).resolve().parent / "model" / MODEL_FOLDER
model_dir.mkdir(parents=True, exist_ok=True)  # 저장 폴더가 없으면 생성

# 최고 검증 점수 시점의 가중치와 모델 설정 저장
model.save_pretrained(model_dir, safe_serialization=True)
tokenizer.save_pretrained(model_dir)  # 예측할 때 사용할 토크나이저도 함께 저장

training_summary = {
    "model_name": MODEL_NAME,
    "model_folder": MODEL_FOLDER,
    "labels": LABELS,
    "batch_size": BATCH_SIZE,
    "learning_rate": best_learning_rate,
    "best_epoch": best_epoch,
    "validation_macro_f1": best_score,
    "test_accuracy": test_accuracy,
    "test_macro_f1": test_macro_f1,
    "test_confusion_matrix": test_matrix.tolist(),
    "max_length": best_max_length,
    "max_length_candidates": MAX_LENGTHS,
    "padding": "longest_in_batch",
    "input_condition": "question 열만 입력, 선택한 최대 토큰 수 초과 시 잘림",
    "seed": SEED,
    "data_split": split_record,  # 저장 모델에도 동일한 질문 ID·수량·시드 기록
    "training_device": DEVICE,
    "selection_seconds": selection_seconds,
    "trials": trials,
}
with (model_dir / "training_summary.json").open("w", encoding="utf-8") as file:
    json.dump(training_summary, file, ensure_ascii=False, indent=2)

print("모델 저장 위치:", model_dir)

##### HTML 보고서 생성 #####

# BERT도 별도 CPU 프로세스에서 평가해 TF-IDF와 같은 조건으로 측정
subprocess.run(
    [sys.executable, str(Path(__file__).with_name("model_report.py")), MODEL_FOLDER],
    check=True,
)
