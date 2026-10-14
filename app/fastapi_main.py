import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI()

# 실행 위치와 관계없이 이 Python 파일 옆에 문서를 저장합니다.
DOCUMENT_FILE = Path(__file__).resolve().parent / "documents.jsonl"


#### 스키마 ####


@app.get("/")
def home():
    return {"message": "FastAPI 서버가 실행 중입니다."}


# BaseModel은 요청 JSON의 필드·타입을 검사하는 입력 스키마
class QuestionRequest(BaseModel):
    # 최소 1글자이며 공백이 아닌 문자가 하나 이상 있어야 함
    question: str = Field(min_length=1, pattern=r"\S")


class DocumentRequest(BaseModel):
    doc: str = Field(min_length=1, pattern=r"\S")


# 성공·실패 모두 같은 응답 필드를 사용 (reason은 오류 설명)
class AnswerResponse(BaseModel):
    ok: bool
    text: str
    reason: str = ""


#### 엔드포인트 ####


@app.post(
    "/ask",
    response_model=AnswerResponse,
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
# 현재는 통신 확인용: 분류기·LLM 호출 없이 질문을 그대로 응답
def ask(request: QuestionRequest) -> AnswerResponse:
    return AnswerResponse(ok=True, text=request.question.strip())


@app.post(
    "/regist-docs",
    response_model=AnswerResponse,
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
def register_document(request: DocumentRequest) -> AnswerResponse:
    document = {"doc": request.doc.strip()}
    # a는 기존 파일 끝에 추가; JSONL은 문서 하나를 한 줄에 저장
    with DOCUMENT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, ensure_ascii=False) + "\n")
    return AnswerResponse(ok=True, text="문서가 등록되었습니다.")


# 요청 스키마 검사에 실패하면 엔드포인트 대신 이 핸들러가 오류 응답 생성
# 422는 입력 검증 실패: 모델 학습 오류나 서버 내부 오류를 처리하는 것은 아님
@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    response = AnswerResponse(
        ok=False,
        text="",
        reason="요청 형식이 올바르지 않습니다. 필수 항목과 입력값을 확인해주세요.",
    )
    return JSONResponse(status_code=422, content=response.model_dump())
