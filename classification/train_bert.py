# BERT 질문 분류 모델 학습

import csv
from pathlib import Path

import torch
from torch.utils.data import DataLoader, TensorDataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

##### 설정 #####

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "questions"
LABELS = ["it", "hr", "finance", "general_affairs", "other"]
MODEL_NAME = "klue/bert-base"  # 사용할 한국어 사전학습 BERT
MAX_LENGTH = 192  # 특수 토큰을 포함한 최대 토큰 수
BATCH_SIZE = 4  # 한 번에 꺼낼 문장 수
LEARNING_RATE = 2e-5  # 학습률: 0.00002
EPOCHS = 10  # 실험할 전체 학습 데이터 반복 횟수 (최적 횟수는 검증으로 판단)
SEED = 42  # 새 분류층의 초기 가중치를 재현하기 위한 난수값
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"  # 사용할 장치

##### 학습·검증·테스트 데이터 읽기 #####

with (DATA_DIR / "train.csv").open("r", encoding="utf-8-sig", newline="") as file:
    train_rows = list(csv.DictReader(file))

with (DATA_DIR / "validation.csv").open("r", encoding="utf-8-sig", newline="") as file:
    validation_rows = list(csv.DictReader(file))

with (DATA_DIR / "test.csv").open("r", encoding="utf-8-sig", newline="") as file:
    test_rows = list(csv.DictReader(file))

print("학습 데이터:", len(train_rows), "개")
print("검증 데이터:", len(validation_rows), "개")
print("테스트 데이터:", len(test_rows), "개")

##### 질문 문장과 정답 번호 준비 #####

train_texts = []  # 학습 질문 목록
train_label_ids = []  # 학습 정답 번호 목록
for row in train_rows:
    train_texts.append(row["text"])
    train_label_ids.append(LABELS.index(row["label"]))

validation_texts = []  # 검증 질문 목록
validation_label_ids = []  # 검증 정답 번호 목록
for row in validation_rows:
    validation_texts.append(row["text"])
    validation_label_ids.append(LABELS.index(row["label"]))

test_texts = []  # 테스트 질문 목록
test_label_ids = []  # 테스트 정답 번호 목록
for row in test_rows:
    test_texts.append(row["text"])
    test_label_ids.append(LABELS.index(row["label"]))

##### 토크나이저 불러오기 #####

# 선택한 BERT가 사용하는 토큰 분리 규칙과 어휘 목록 불러오기
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

##### 학습·검증·테스트 질문 토큰화 #####

train_encoded = tokenizer(
    train_texts,
    padding="max_length",  # 짧은 문장은 패딩 토큰으로 채우기
    truncation=True,  # 최대 토큰 수를 넘으면 자르기
    max_length=MAX_LENGTH,
    return_tensors="pt",  # PyTorch 텐서로 반환
)

validation_encoded = tokenizer(
    validation_texts,
    padding="max_length",
    truncation=True,
    max_length=MAX_LENGTH,
    return_tensors="pt",
)

test_encoded = tokenizer(
    test_texts,
    padding="max_length",
    truncation=True,
    max_length=MAX_LENGTH,
    return_tensors="pt",
)

##### 학습·검증·테스트 데이터셋 만들기 #####

# 정답 번호 목록을 정수 텐서로 변환
train_targets = torch.tensor(train_label_ids, dtype=torch.long)
validation_targets = torch.tensor(validation_label_ids, dtype=torch.long)
test_targets = torch.tensor(test_label_ids, dtype=torch.long)

# 같은 위치의 토큰 번호·마스크·정답을 한 묶음으로 연결
train_dataset = TensorDataset(
    train_encoded["input_ids"], train_encoded["attention_mask"], train_targets
)

validation_dataset = TensorDataset(
    validation_encoded["input_ids"],
    validation_encoded["attention_mask"],
    validation_targets,
)

test_dataset = TensorDataset(
    test_encoded["input_ids"], test_encoded["attention_mask"], test_targets
)

##### 학습·검증·테스트 데이터 로더 만들기 #####

train_loader = DataLoader(
    train_dataset,
    batch_size=BATCH_SIZE,
    shuffle=True,  # 학습할 때마다 데이터 순서를 섞기
)

validation_loader = DataLoader(
    validation_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,  # 검증 질문과 정답의 원래 순서 유지
)

test_loader = DataLoader(
    test_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,  # 테스트 질문과 정답의 원래 순서 유지
)

##### 모델의 라벨 번호 설정 #####

id2label = {}  # 번호 → 카테고리 이름
label2id = {}  # 카테고리 이름 → 번호
for index, label in enumerate(LABELS):
    id2label[index] = label
    label2id[label] = index

##### BERT 분류 모델 불러오기 #####

torch.manual_seed(SEED)
model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_NAME,
    num_labels=len(LABELS),  # 카테고리 5개의 점수를 출력하는 분류층
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
    lr=LEARNING_RATE,  # 가중치 변경 크기에 영향을 주는 학습률
    weight_decay=0.01,  # 가중치가 지나치게 커지는 것을 억제하는 설정
)

##### BERT 학습 #####

for epoch in range(1, EPOCHS + 1):
    model.train()  # 학습 모드로 설정
    total_loss = 0.0
    train_count = 0

    for step, (input_ids, attention_mask, targets) in enumerate(train_loader, start=1):
        input_ids = input_ids.to(DEVICE)
        attention_mask = attention_mask.to(DEVICE)
        targets = targets.to(DEVICE)

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
            print(f"epoch {epoch}/{EPOCHS}: 배치 {step}/{len(train_loader)}")

    print("평균 학습 손실:", round(total_loss / train_count, 4))
