from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.answer_text import LLM_RESPONSE_ERROR, LLMResponseError
from app.routers import classification, documents, questions
from app.schemas import AnswerResponse

app = FastAPI()
app.include_router(questions.router)
app.include_router(documents.router)
app.include_router(classification.router)


@app.get("/")
def home():
    return {"message": "FastAPI 서버가 실행 중입니다."}


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


# 작성일: 2026-10-14
# 작성자: yu
# 기능: LLM 응답에 쓸 text가 없으면 원문 대신 안내 문구로 502 반환
@app.exception_handler(LLMResponseError)
async def handle_llm_response_error(
    request: Request, exc: LLMResponseError
) -> JSONResponse:
    response = AnswerResponse(ok=False, text="", reason=LLM_RESPONSE_ERROR)
    return JSONResponse(status_code=502, content=response.model_dump())
