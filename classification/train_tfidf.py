# TF-IDF + 로지스틱 회귀 모델 학습

import csv
from pathlib import Path

##### 데이터 경로 #####

# 실행하는 위치와 관계없이 프로젝트의 data/questions 폴더를 찾기
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "questions"

##### CSV 읽기 #####

# DictReader는 각 행을 {"text": "질문 문장", "label": "lookup", ...} 형태로 읽기
with (DATA_DIR / "train.csv").open("r", encoding="utf-8-sig", newline="") as file:
    train_rows = list(csv.DictReader(file))

with (DATA_DIR / "validation.csv").open("r", encoding="utf-8-sig", newline="") as file:
    validation_rows = list(csv.DictReader(file))

##### 학습 문장과 정답 준비 #####

train_texts = []  # 모델에 입력할 질문 문장
train_labels = []  # 각 문장의 정답 카테고리

for row in train_rows:
    train_texts.append(row["text"])
    train_labels.append(row["label"])

# 문장과 정답은 같은 순서로 담기므로 같은 위치의 항목끼리 한 쌍
print("학습 데이터:", len(train_rows), "개")
print("검증 데이터:", len(validation_rows), "개")
print("첫 번째 질문:", train_texts[0])
print("첫 번째 정답:", train_labels[0])
