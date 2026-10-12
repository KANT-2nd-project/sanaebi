# BERT 질문 분류 모델 학습

import csv
from pathlib import Path

##### 설정 #####

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "questions"
LABELS = ["it", "hr", "finance", "general_affairs", "other"]

##### 학습 데이터 읽기 #####

with (DATA_DIR / "train.csv").open("r", encoding="utf-8-sig", newline="") as file:
    train_rows = list(csv.DictReader(file))

##### 문장 하나와 정답 번호 확인 #####

row = train_rows[0]  # 첫 번째 행만 꺼내기 (원본 CSV는 바꾸지 않음)
text = row["text"]  # 모델에 입력할 질문 문장
label_id = LABELS.index(row["label"])  # 라벨 목록의 위치를 정답 번호로 사용

print("학습 데이터:", len(train_rows), "개")
print("문장:", text)
print("라벨 순서:", LABELS)
print("정답 이름:", row["label"])
print("정답 번호:", label_id)
