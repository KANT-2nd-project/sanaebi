from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers import documents, questions
from app.schemas import AnswerResponse

app = FastAPI()
app.include_router(questions.router)
app.include_router(documents.router)

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
