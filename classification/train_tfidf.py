# TF-IDF + 로지스틱 회귀 모델 학습

import csv
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline

##### 데이터 경로 #####

# 실행하는 위치와 관계없이 프로젝트의 data/questions 폴더를 찾기
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "questions"

LABELS = ["it","hr","finance","general_affairs","other"]

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

validation_texts = []  # 학습에 사용하지 않고 검증할 질문 문장
validation_labels = []  # 검증 질문의 실제 정답

for row in validation_rows:
    validation_texts.append(row["text"])
    validation_labels.append(row["label"])

# 문장과 정답은 같은 순서로 담기므로 같은 위치의 항목끼리 한 쌍
print("학습 데이터:", len(train_rows), "개")
print("검증 데이터:", len(validation_rows), "개")
print("첫 번째 질문:", train_texts[0])
print("첫 번째 정답:", train_labels[0])

##### TF-IDF 변환 #####

# 문장을 연속된 문자 2~5개 조각으로 나누고, 각 조각에 TF-IDF 값을 부여
vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1)

# 학습 문장에서 특징 목록과 IDF를 배우면서 숫자 벡터로 변환
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

# C는 모델이 학습 데이터에 얼마나 강하게 맞추도록 할지 조절하는 설정
for c in c_candidates:
    candidate = LogisticRegression(
        C=c, max_iter=1000, class_weight="balanced", random_state=42
    )

    # 새 모델의 가중치는 train으로만 학습
    candidate.fit(train_vectors, train_labels)

    # validation은 설정 선택에만 사용하며 가중치를 조절하지 않음
    candidate_predictions = candidate.predict(validation_vectors)
    accuracy = accuracy_score(validation_labels, candidate_predictions)
    score = f1_score(
        validation_labels,
        candidate_predictions,
        labels=LABELS,
        average="macro",
        zero_division=0,
    )
    print(f"\nC={c}: 검증 정확도={accuracy:.4f}, Macro F1={score:.4f}")

    # 각 C 후보의 혼동행렬: 행은 실제 정답, 열은 예측
    matrix = confusion_matrix(validation_labels, candidate_predictions, labels=LABELS)
    print("검증 혼동행렬: 행은 정답, 열은 예측")
    print("카테고리 순서:", LABELS)
    for label, row in zip(LABELS, matrix):
        print(label, row.tolist())

    # 동점이면 먼저 비교한 후보 유지
    if score > best_score:
        best_classifier = candidate
        best_c = c
        best_score = score

print("선택한 C:", best_c)
print("선택한 모델의 검증 Macro F1:", round(best_score, 4))

##### 테스트 데이터 읽기 #####

# 검증 점수로 모델을 선택한 뒤에 테스트 데이터를 읽기
with (DATA_DIR / "test.csv").open("r", encoding="utf-8-sig", newline="") as file:
    test_rows = list(csv.DictReader(file))

test_texts = []  # 최종 평가용 질문
test_labels = []  # 최종 평가용 정답

for row in test_rows:
    test_texts.append(row["text"])
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

# classification/model 폴더에 저장하고 파일 이름으로 모델 종류를 구분
output_dir = Path(__file__).resolve().parent / "model"
output_dir.mkdir(parents=True, exist_ok=True)  # 저장 폴더가 없으면 생성

# 학습한 TF-IDF 변환기와 선택한 분류기를 하나로 묶기 (다시 학습하지 않음)
model = make_pipeline(vectorizer, best_classifier)

# 특징 목록, IDF, 분류기의 가중치와 편향을 함께 파일에 저장
model_file = output_dir / "tfidf_logistic_regression.joblib"
joblib.dump(model, model_file)  # 재실행하면 같은 경로의 모델을 갱신
print("모델 저장 위치:", model_file)
