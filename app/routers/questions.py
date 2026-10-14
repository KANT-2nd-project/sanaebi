from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import QuestionHandler, get_question_handler
from app.schemas import AnswerResponse, QuestionRequest

router = APIRouter()


@router.post(
    "/ask",
    response_model=AnswerResponse,
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        502: {"model": AnswerResponse, "description": "답변 생성 오류"},
        503: {
            "model": AnswerResponse,
            "description": "분류 모델 또는 문서 저장소 사용 불가",
        },
    },
)
def ask(
    request: QuestionRequest,
    handle: Annotated[QuestionHandler, Depends(get_question_handler)],
):
    result = handle(request.question.strip())
    return AnswerResponse(ok=True, text=result.text)
