import json
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


##### 변수 #####

# 직원 정보가 저장될 파일 경로
SAVE_PATH = Path(__file__).resolve().parent

employee_file = SAVE_PATH / "employees.jsonl"
EMPLOYEE_ID_PREFIX = "EMP-"  # 직원 ID의 공통 접두사


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
