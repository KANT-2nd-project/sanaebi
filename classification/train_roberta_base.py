# BERT 요청 처리 질문 분류 모델 학습

# 실행 순서: 공통 분할 → 질문을 토큰으로 변환 → 후보별 학습·검증
# → 최고 검증 점수의 가중치 복원 → 테스트 평가 → 모델·보고서 저장

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

# MODEL_NAME은 불러올 사전학습 모델 ID, MODEL_FOLDER는 내 모델·결과의 저장 폴더
# 여러 모델을 비교할 때 저장 폴더가 다르면 결과를 구분할 수 있음

MODEL_NAME = "klue/roberta-base"
MODEL_FOLDER = "roberta_base"


MAX_LENGTHS = [256, 384]  # 비교할 최대 토큰 수 (특수 토큰 포함)
BATCH_SIZE = 4  # 한 번에 꺼낼 문장 수
LEARNING_RATES = [2e-5, 5e-5]  # 비교할 학습률: 0.00002, 0.00005
EPOCHS = 10  # 실험할 전체 학습 데이터 반복 횟수 (최적 횟수는 검증으로 판단)
SEED = RANDOM_SEED  # 데이터 분할과 모델 초기화에 사용하는 고정 난수값
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"  # 사용할 장치
selection_started = perf_counter()  # 데이터 준비부터 후보 학습·선택까지의 시간

##### 학습·검증·테스트 데이터 나누기 #####

question_rows = read_question_rows()
# 모든 로컬 모델이 같은 시드·그룹 분할을 사용해 같은 질문으로 비교
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
    # DataLoader가 꺼낸 질문 여러 개를 길이가 같은 텐서 배치로 묶음
    # 짧은 질문의 빈 칸은 패딩으로 채우고 attention_mask에는 0으로 표시
    batch = padding_collator(questions)
    # 기존 학습 반복문에서 사용하던 토큰 번호·마스크·정답 순서로 반환
    return batch["input_ids"], batch["attention_mask"], batch["labels"]


def make_loader(texts, label_ids, max_length, shuffle=False):
    # 아직 질문마다 길이가 다르므로 토큰 번호를 리스트로 준비
    # 실제 배치를 꺼낼 때 collate_batch가 패딩하고 텐서로 변환
    encoded = tokenizer(
        texts,
        padding=False,  # 여기서는 패딩하지 않고 각 질문의 길이를 유지
        truncation=True,  # 설정한 최대 토큰 수를 넘는 질문만 자르기
        max_length=max_length,
        return_token_type_ids=False,
    )
    questions = []
    # 같은 index의 질문과 정답을 묶어 섞인 뒤에도 짝이 유지되도록 함
    for index, label_id in enumerate(label_ids):
        questions.append(
            {
                "input_ids": encoded["input_ids"][index],  # 질문을 바꾼 토큰 번호
                # 1은 실제 토큰, 0은 패딩: 모델이 패딩을 무시할 때 사용
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
# LABELS의 순서가 정답 번호와 모델 출력 점수 칸의 순서를 결정
# 저장할 때 이 대응표도 모델 설정에 포함해 예측 번호를 라벨로 복원
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

# 입력 길이·학습률·epoch를 검증 점수로 선택한 뒤 테스트 평가
# 길이 2개 × 학습률 2개 = 독립적인 학습 후보 4개
# epoch는 각 후보 안에서 train 전체를 몇 번 반복했는지 나타냄
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
                # logits는 3개 라벨의 점수, loss는 그 점수와 정답의 차이로 계산
                loss = output.loss
                loss.backward()  # 가중치를 어떻게 변경할지 기울기 계산
                optimizer.step()  # 실제 가중치 변경

                # 배치 평균 손실에 실제 배치 크기를 곱해 질문 수 기준 평균 계산
                # 마지막 배치가 작아도 같은 비중의 배치로 계산하지 않도록 함
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

            # 검증에서는 정답을 모델에 넣지 않고 예측 결과와 바깥에서 비교
            # backward와 optimizer.step을 호출하지 않아 가중치는 바뀌지 않음
            with torch.inference_mode():  # 기울기 계산 없이 예측만 수행
                for input_ids, attention_mask, _ in validation_loader:
                    output = model(
                        input_ids=input_ids.to(DEVICE),
                        attention_mask=attention_mask.to(DEVICE),
                    )
                    # 각 질문에서 점수가 가장 높은 카테고리 번호 선택
                    # dim=1은 질문마다 있는 3개 점수 중 최고 점수의 번호를 선택
                    # cpu().tolist()는 결과를 GPU 텐서에서 Python 리스트로 변환
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
            # 세 라벨별 F1을 같은 비중으로 평균한 검증 Macro F1으로 선택
            # 테스트 점수나 학습 손실로 후보를 선택하지 않음
            if validation_macro_f1 > best_score:
                best_score = validation_macro_f1
                best_max_length = max_length
                best_learning_rate = learning_rate
                best_epoch = epoch
                # detach는 기울기 연결 해제, cpu는 GPU 메모리 대신 RAM에 보관
                # clone은 이후 학습이 이 저장 가중치를 바꾸지 않도록 독립 복사
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

# 검증으로 선택한 최대 토큰 수로 테스트 데이터 로더를 준비
# 테스트 정답은 정확도·F1 계산에만 사용하고 추가 학습은 하지 않음
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

# 가중치 파일과 별도로 선택한 설정·점수·분할을 JSON으로 남김
# 보고서는 이 기록의 질문 ID로 분할을 복원해 같은 질문을 재평가
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
# 현재 Python 환경으로 보고서 코드를 별도 실행 (check=True: 실패 시 오류)
# 보고서의 재예측·속도 측정에서도 모델을 다시 학습하지 않음
subprocess.run(
    [sys.executable, str(Path(__file__).with_name("model_report.py")), MODEL_FOLDER],
    check=True,
)
