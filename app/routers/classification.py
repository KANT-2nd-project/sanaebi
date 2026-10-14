from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.koelectra_classifier import classify_question
from app.schemas import AnswerResponse, ClassificationResponse, QuestionRequest

router = APIRouter()


@router.post(
    "/classify/koelectra-base",
    response_model=ClassificationResponse,
    summary="KoELECTRA Base 질문 분류",
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        503: {"model": AnswerResponse, "description": "모델 없음"},
    },
)
def classify_koelectra(request: QuestionRequest):
    # 저장 모델로 질문을 예측하고 카테고리 이름만 반환
    try:
        category = classify_question(request.question.strip())
    except FileNotFoundError:
        response = AnswerResponse(ok=False, text="", reason="분류 모델이 없습니다.")
        return JSONResponse(status_code=503, content=response.model_dump())
    return ClassificationResponse(category=category)
