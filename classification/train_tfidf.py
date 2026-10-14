# TF-IDF + 로지스틱 회귀 모델 학습

# 실행 순서: 공통 분할 → train으로 TF-IDF 학습 → C 후보 학습·검증
# → 최고 검증 F1 후보의 테스트 평가 → 변환기·분류기 저장 → HTML 생성

import csv
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import joblib
from question_split import (
    LABELS,
    RANDOM_SEED,
    make_split_record,
    question_input,
    split_questions,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline

##### 데이터 경로 #####

# 기준 예제와 같은 질문 CSV를 사용
DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "dataset.csv"

selection_started = perf_counter()  # 데이터 준비부터 후보 학습·선택까지의 시간

##### CSV 읽기 #####

# 공통 함수가 질문 ID를 정렬하고 같은 그룹끼리 학습·검증·테스트로 분할
with DATASET_PATH.open("r", encoding="utf-8-sig", newline="") as file:
    question_rows = list(csv.DictReader(file))
splits = split_questions(question_rows, seed=RANDOM_SEED)
train_rows = splits["train"]
validation_rows = splits["validation"]
test_rows = splits["test"]

# 모델 저장 기록에 질문 ID·라벨 수량·시드를 포함해 보고서도 같은 데이터 사용
split_record = make_split_record(splits, DATASET_PATH, seed=RANDOM_SEED)

##### 학습 문장과 정답 준비 #####

train_texts = []  # 모델에 입력할 질문 (question 열만 사용)
train_labels = []  # 각 문장의 정답 카테고리

for row in train_rows:
    train_texts.append(question_input(row))
    train_labels.append(row["label"])

validation_texts = []  # 검증할 질문
validation_labels = []  # 검증 질문의 실제 정답

for row in validation_rows:
    validation_texts.append(question_input(row))
    validation_labels.append(row["label"])

# 문장과 정답은 같은 순서로 담기므로 같은 위치의 항목끼리 한 쌍
print("학습 데이터:", len(train_rows), "개")
print("검증 데이터:", len(validation_rows), "개")
print("테스트 데이터:", len(test_rows), "개 / 분할 시드:", RANDOM_SEED)
print("첫 번째 질문:", train_texts[0])
print("첫 번째 정답:", train_labels[0])

# 분할·입력만 확인할 때는 TF-IDF 학습도 실행하지 않음
if "--preview-questions" in sys.argv or "--preview-documents" in sys.argv:
    for name, data in split_record["splits"].items():
        print(name, data["label_counts"])
    raise SystemExit(0)

##### TF-IDF 변환 #####

# 문장을 연속된 문자 2~5개 조각으로 나누고, 각 조각에 TF-IDF 값을 부여
vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1)

# 학습 문장에서 특징 목록과 IDF를 배우면서 숫자 벡터로 변환
# fit_transform은 학습과 변환을 함께 수행: validation·test에는 사용하지 않음
train_vectors = vectorizer.fit_transform(train_texts)

# 검증 문장은 학습한 특징 목록과 IDF를 그대로 사용해서 변환
validation_vectors = vectorizer.transform(validation_texts)

# shape는 (문장 수, 특징 수): 두 데이터의 특징 수가 같아야 함
print("학습 벡터 크기:", train_vectors.shape)
print("검증 벡터 크기:", validation_vectors.shape)

# 벡터화 로그
# print(train_vectors)
# print(validation_vectors)

# features = vectorizer.get_feature_names_out()
# first_vector = train_vectors[0]  # 첫 번째 질문의 벡터

# for index, value in zip(first_vector.indices, first_vector.data):
#     print(repr(features[index]), round(float(value), 4))

##### 검증 결과로 설정 비교 #####

# C가 작을수록 가중치가 지나치게 커지는 것을 강하게 억제
c_candidates = [0.1, 0.5, 1.0, 10.0]
best_classifier = None
best_c = None
best_score = -1.0  # F1은 0~1이므로 첫 후보부터 비교 가능
trials = []  # 각 C 후보의 검증 결과를 HTML 표에 표시

# C는 모델이 학습 데이터에 얼마나 강하게 맞추도록 할지 조절하는 설정
for c in c_candidates:
    candidate = LogisticRegression(
        # max_iter는 최적화 반복 상한, balanced는 라벨 수가 적을수록 손실 비중 증가
        C=c,
        max_iter=1000,
        class_weight="balanced",
        random_state=RANDOM_SEED,
    )

    # 새 모델의 가중치는 train으로만 학습
    candidate.fit(train_vectors, train_labels)

    # validation은 설정 선택에만 사용하며 가중치를 조절하지 않음
    # predict는 학습한 가중치를 그대로 사용해 라벨을 예측 (가중치 변경 없음)
    candidate_predictions = candidate.predict(validation_vectors)
    accuracy = accuracy_score(validation_labels, candidate_predictions)
    score = f1_score(
        validation_labels,
        candidate_predictions,
        labels=LABELS,
        average="macro",  # 세 카테고리별 F1을 같은 비중으로 평균
        zero_division=0,
    )
    print(f"\nC={c}: 검증 정확도={accuracy:.4f}, Macro F1={score:.4f}")
    trials.append(
        {"C": c, "validation_accuracy": accuracy, "validation_macro_f1": score}
    )

    # 각 C 후보의 혼동행렬: 행은 실제 정답, 열은 예측
    matrix = confusion_matrix(validation_labels, candidate_predictions, labels=LABELS)
    print("검증 혼동행렬: 행은 정답, 열은 예측")
    print("카테고리 순서:", LABELS)
    for label, row in zip(LABELS, matrix):
        print(label, row.tolist())

    # 동점이면 먼저 비교한 후보 유지
    # C는 가중치 자체가 아니라 학습 시 가중치 크기를 억제하는 정도를 조절
    # 최종 선택에는 검증 점수만 사용하고 테스트 점수는 사용하지 않음
    if score > best_score:
        best_classifier = candidate
        best_c = c
        best_score = score

print("선택한 C:", best_c)
print("선택한 모델의 검증 Macro F1:", round(best_score, 4))
selection_seconds = perf_counter() - selection_started

##### 선택 완료 후 테스트 입력 준비 #####

test_texts = []  # 최종 평가용 질문
test_labels = []  # 최종 평가용 정답

for row in test_rows:
    test_texts.append(question_input(row))
    test_labels.append(row["label"])

##### 선택한 모델의 테스트 평가 #####

# train에서 학습한 변환기를 그대로 사용 (테스트에서는 fit을 호출하지 않음)
test_vectors = vectorizer.transform(test_texts)
test_predictions = best_classifier.predict(test_vectors)

test_accuracy = accuracy_score(test_labels, test_predictions)
test_macro_f1 = f1_score(
    test_labels,
    test_predictions,
    labels=LABELS,
    average="macro",
    zero_division=0,
)

print("테스트 데이터:", len(test_rows), "개")
print("테스트 정확도:", round(test_accuracy, 4))
print("테스트 Macro F1:", round(test_macro_f1, 4))

test_matrix = confusion_matrix(test_labels, test_predictions, labels=LABELS)
print("테스트 혼동행렬: 행은 정답, 열은 예측")
print("카테고리 순서:", LABELS)
for label, row in zip(LABELS, test_matrix):
    print(label, row.tolist())

print("테스트에서 틀린 질문:")
for text, actual, predicted in zip(test_texts, test_labels, test_predictions):
    if actual != predicted:
        print("질문:", text)
        print("정답:", actual, "/ 예측:", predicted)

##### 선택한 모델 저장 #####

# TF-IDF 모델은 classification/model/tf-idf 폴더에 저장
output_dir = Path(__file__).resolve().parent / "model" / "tf-idf"
output_dir.mkdir(parents=True, exist_ok=True)  # 저장 폴더가 없으면 생성

# 학습한 TF-IDF 변환기와 선택한 분류기를 하나로 묶기 (다시 학습하지 않음)
# 새 질문에도 같은 특징 목록·IDF를 적용한 뒤 같은 분류기로 예측하도록 묶음
model = make_pipeline(vectorizer, best_classifier)

# 특징 목록, IDF, 분류기의 가중치와 편향을 함께 파일에 저장
model_file = output_dir / "tfidf_logistic_regression.joblib"
joblib.dump(model, model_file)  # 재실행하면 같은 경로의 모델을 갱신
print("모델 저장 위치:", model_file)

##### 학습 설정 기록 및 HTML 보고서 생성 #####

# 이 JSON은 모델 가중치가 아니라 재평가에 필요한 설정·분할·검증 결과 기록
training_summary = {
    "model_name": "TF-IDF + LogisticRegression",
    "labels": LABELS,
    "C": best_c,
    "analyzer": "char",
    "ngram_range": [2, 5],
    "min_df": 1,
    "class_weight": "balanced",
    "max_iter": 1000,
    "seed": RANDOM_SEED,
    "data_split": split_record,
    "input_condition": "question 열만 입력, 전체 질문 사용",
    "validation_macro_f1": best_score,
    "selection_seconds": selection_seconds,
    "trials": trials,
}
with model_file.with_suffix(".json").open("w", encoding="utf-8") as file:
    json.dump(training_summary, file, ensure_ascii=False, indent=2)

# 별도 CPU 프로세스에서 저장 모델을 평가해 두 모델의 비교 조건을 맞추기
subprocess.run(
    [sys.executable, str(Path(__file__).with_name("model_report.py")), "tfidf_lr"],
    check=True,
)
