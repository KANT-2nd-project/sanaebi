from fastapi import APIRouter

from app.answer_text import extract_answer_text, generate_answer
from app.schemas import AnswerResponse, QuestionRequest

router = APIRouter()


@router.post(
    "/ask",
    response_model=AnswerResponse,
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        502: {"model": AnswerResponse, "description": "답변 생성 오류"},
    },
)
def ask(request: QuestionRequest) -> AnswerResponse:
    result = generate_answer(request.question.strip())
    return AnswerResponse(ok=True, text=extract_answer_text(result))
