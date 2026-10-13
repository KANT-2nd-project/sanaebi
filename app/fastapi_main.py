import json
from datetime import date
from pathlib import Path
from typing import Literal

import joblib
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# 실행 코드
# python -m uv run fastapi dev .\fastapi_main.py

# BaseModel은 API에서 주고받는 데이터의 구조와 타입을 정의하고 검사하는 데 사용

app = FastAPI()

##### 클래스 #####


# 질문
class QuestionRequest(BaseModel):
    question: str


# 답변
class AnswerResponse(BaseModel):
    answer: str


# 직원 한 명의 입력 형식
class EmployeeCreate(BaseModel):
    name: str = Field(
        min_length=1, pattern=r"\S", examples=[""]
    )  # 이름 (필수, 문서에는 빈 문자열로 표시)
    password: str  # 비밀번호
    department: str  # 소속 부서
    position: str  # 직급
    email: str  # 회사 이메일
    phone_number: str  # 전화번호
    hire_date: date  # 입사일 (YYYY-MM-DD)
    annual_salary: int  # 세전 연봉 (원)


# 저장 및 응답 형식 (자동 생성한 ID 포함)
class Employee(EmployeeCreate):
    employee_id: str  # 직원 고유 ID
    employment_status: Literal["재직", "퇴직"] = "재직"  # 등록 시 재직으로 저장


# 질문 분류 결과
class ClassificationResponse(BaseModel):
    question: str  # 입력한 질문
    category: Literal["it", "hr", "finance", "general_affairs", "other"]  # 담당 영역


##### 변수 #####

# 직원 정보가 저장될 파일 경로
SAVE_PATH = Path(__file__).resolve().parent

employee_file = SAVE_PATH / "employees.jsonl"
EMPLOYEE_ID_PREFIX = "EMP-"  # 직원 ID의 공통 접두사


# 학습 스크립트에서 저장한 TF-IDF + 로지스틱 회귀 모델 경로
TFIDF_LR_MODEL_PATH = (
    SAVE_PATH.parent / "classification" / "model" / "tfidf_logistic_regression.joblib"
)

# 학습한 BERT 모델과 토크나이저가 저장된 폴더 경로
BERT_MODEL_PATH = SAVE_PATH.parent / "classification" / "model" / "bert"
BERT_MAX_LENGTH = 192  # BERT 학습 때와 같은 최대 토큰 수


# 서버가 이 파일을 읽을 때 모델을 한 번 불러오기 (다시 학습하지 않음)
tfidf_lr_model = None  # 모델이 없으면 분류 요청에서 안내 메시지 반환
if TFIDF_LR_MODEL_PATH.is_file():
    tfidf_lr_model = joblib.load(TFIDF_LR_MODEL_PATH)

# 서버가 이 파일을 읽을 때 저장된 BERT를 한 번 불러오기
bert_tokenizer = None
bert_model = None
if BERT_MODEL_PATH.is_dir():
    bert_tokenizer = AutoTokenizer.from_pretrained(
        BERT_MODEL_PATH, local_files_only=True
    )  # 저장된 토크나이저 사용
    bert_model = AutoModelForSequenceClassification.from_pretrained(
        BERT_MODEL_PATH, local_files_only=True
    )  # 저장된 가중치 사용 (다시 학습하지 않음)
    bert_model.eval()  # 예측을 위한 평가 모드


##### API 엔드포인트 #####


# 이름이 비어 있으면 알아보기 쉬운 안내 메시지 반환
# EmployeeCreate 에서 입력 검사 후 이름이 누락되면 오류 발생
# 검증 오류는 핸들러로 전달한 후 핸들러가 오류를 찾고 메시지를 반환
@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    for error in exc.errors():
        # 요청본문(body) 에서 name 에서 발생한 오류인가? + 누락, 빈 문자열, 공백만 입력한 오류인가?
        if error["loc"] == ("body", "name") and (
            error["type"] in {"missing", "string_too_short", "string_pattern_mismatch"}
            or error.get("input") is None  # 값이 null 인가?
        ):
            return JSONResponse(
                status_code=422, content={"detail": "이름을 입력하지 않았습니다."}
            )

    return await request_validation_exception_handler(request, exc)


# 질문
@app.post("/ask", response_model=AnswerResponse)
async def ask(request: QuestionRequest) -> AnswerResponse:
    return AnswerResponse(answer="답변 : " + request.question)


# TF-IDF + 로지스틱 회귀로 질문 분류
@app.post(
    "/classify/tfidf-lr",
    response_model=ClassificationResponse,
    summary="TF-IDF + 로지스틱 회귀 질문 분류",
)
async def classify_tfidf_lr(request: QuestionRequest) -> ClassificationResponse:
    if tfidf_lr_model is None:
        raise HTTPException(
            status_code=503,
            detail="해당 모델이 존재하지 않습니다.",
        )

    # 저장된 모델로 질문을 변환하고 분류 (다시 학습하지 않음)
    category = tfidf_lr_model.predict([request.question])[0]
    return ClassificationResponse(question=request.question, category=category)


# BERT로 질문 분류
@app.post(
    "/classify/bert", response_model=ClassificationResponse, summary="BERT 질문 분류"
)
async def classify_bert(request: QuestionRequest) -> ClassificationResponse:
    if bert_model is None or bert_tokenizer is None:
        raise HTTPException(status_code=503, detail="해당 모델이 존재하지 않습니다.")

    # 입력 질문을 학습 때와 같은 방식으로 토큰화
    inputs = bert_tokenizer(
        request.question,
        padding="max_length",
        truncation=True,
        max_length=BERT_MAX_LENGTH,
        return_tensors="pt",
    )

    with torch.inference_mode():  # 학습 없이 예측만 수행
        output = bert_model(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
        )

    label_id = output.logits.argmax(dim=1).item()  # 가장 높은 점수의 번호
    category = bert_model.config.id2label[label_id]  # 번호를 카테고리 이름으로 변환
    return ClassificationResponse(question=request.question, category=category)


# 직원 등록
@app.post("/employees/register", response_model=Employee, summary="직원 등록")
async def register_employee(employee: EmployeeCreate) -> Employee:
    # 마지막 직원 ID의 번호를 확인 (파일이 없거나 비어 있으면 0)
    last_number = 0
    if employee_file.exists():
        with employee_file.open("r", encoding="utf-8") as file:
            lines = file.read().strip().splitlines()  # 전체 내용을 줄 단위로 나누기

        if lines:
            last_line = lines[-1]  # 마지막 줄
            last_id = json.loads(last_line)["employee_id"]
            last_number = int(last_id.removeprefix(EMPLOYEE_ID_PREFIX))

    saved_employee = Employee(
        employee_id=f"{EMPLOYEE_ID_PREFIX}{last_number + 1:03d}",
        **employee.model_dump(),  # 나머지 요소들은 employee를 펼쳐서 저장
    )

    # 새 직원 정보만 파일 끝에 한 줄 추가 (파일이 없으면 자동 생성)
    with employee_file.open("a", encoding="utf-8") as file:
        data = saved_employee.model_dump(mode="json")
        file.write(json.dumps(data, ensure_ascii=False) + "\n")
    return saved_employee


# 등록한 직원 목록 확인
@app.get("/employees", response_model=list[Employee], summary="직원 목록 조회")
async def get_employees() -> list[Employee]:
    # 저장 파일이 없으면 안내 메시지와 404 오류 반환
    if not employee_file.exists():
        raise HTTPException(status_code=404, detail="등록된 직원 정보가 없습니다.")

    # 조회할 때만 파일을 읽고, 각 줄을 직원 정보로 변환
    employees: list[Employee] = []
    with employee_file.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():  # 빈 줄은 건너뛰기
                employees.append(Employee.model_validate_json(line))
    return employees
