import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import AnswerResponse, DocumentRequest, QuestionRequest

app = FastAPI()

# 실행 위치와 관계없이 이 Python 파일 옆에 문서를 저장합니다.
DOCUMENT_FILE = Path(__file__).resolve().parent / "documents.jsonl"


@app.get("/")
def home():
    return {"message": "FastAPI 서버가 실행 중입니다."}


#### 엔드포인트 ####


@app.post(
    "/ask",
    response_model=AnswerResponse,
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
def ask(request: QuestionRequest) -> AnswerResponse:
    return AnswerResponse(ok=True, text=request.question.strip())


@app.post(
    "/regist-docs",
    response_model=AnswerResponse,
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
def register_document(request: DocumentRequest) -> AnswerResponse:
    document = {"doc": request.doc.strip()}
    with DOCUMENT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, ensure_ascii=False) + "\n")
    return AnswerResponse(ok=True, text="문서가 등록되었습니다.")


# 오류가 나면 handler가 오류를 찾고 오류 내용을 말해줌
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
