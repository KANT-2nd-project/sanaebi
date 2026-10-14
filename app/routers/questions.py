from fastapi import APIRouter

from app.schemas import AnswerResponse, QuestionRequest

router = APIRouter()


@router.post(
    "/ask",
    response_model=AnswerResponse,
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
def ask(request: QuestionRequest) -> AnswerResponse:
    return AnswerResponse(ok=True, text=request.question.strip())
