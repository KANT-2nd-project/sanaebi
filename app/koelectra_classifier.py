import json
from functools import lru_cache
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

##### 저장 모델 경로 #####

# 가중치(model.safetensors), 모델 설정, 토크나이저가 함께 저장된 폴더
# 실행 위치와 관계없이 이 파일을 기준으로 프로젝트의 모델 폴더 찾기
MODEL_PATH = (
    Path(__file__).resolve().parent.parent
    / "classification"
    / "model"
    / "koelectra_base"
)

##### 모델 불러오기 #####


@lru_cache(maxsize=1)  # 처음 불러온 결과를 보관하고 다음 호출에서 재사용
def load_model():
    # 가중치 파일이 없으면 라우터에서 간단한 안내로 응답
    if not (MODEL_PATH / "model.safetensors").is_file():
        raise FileNotFoundError("분류 모델이 없습니다.")

    # 저장된 토큰 분리 규칙·어휘를 읽기 (인터넷 다운로드 없음)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)

    # config.json의 모델 구조·라벨과 model.safetensors의 학습 가중치 불러오기
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_PATH, local_files_only=True, use_safetensors=True
    )
    model.eval()  # 학습이 아닌 예측 모드로 설정

    # 학습 때 선택한 최대 토큰 수를 그대로 사용 (현재 저장 모델은 256)
    summary = json.loads(
        (MODEL_PATH / "training_summary.json").read_text(encoding="utf-8")
    )
    max_length = summary["max_length"]

    return tokenizer, model, max_length


##### 질문 분류 #####


def classify_question(question: str) -> str:
    tokenizer, model, max_length = load_model()

    # 질문을 토큰 번호·마스크로 변환하고 최대 길이를 넘는 부분만 자르기
    inputs = tokenizer(
        question.strip(),
        truncation=True,
        max_length=max_length,
        padding=False,
        return_token_type_ids=False,
        return_tensors="pt",  # 모델이 받는 PyTorch 텐서로 변환
    )

    # 예측에서는 기울기를 계산하지 않고 저장된 가중치를 그대로 사용
    with torch.inference_mode():
        output = model(**inputs)  # input_ids와 attention_mask를 펼쳐 전달

    # 질문 하나의 세 점수 중 가장 높은 점수의 카테고리 번호 선택
    category_id = output.logits.argmax(dim=1).item()
    return model.config.id2label[category_id]  # 번호를 실제 라벨 이름으로 변환
