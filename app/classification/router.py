from typing import Annotated

from fastapi import APIRouter, Depends

from app.classification.predictor import TransformerClassifier
from app.dependencies import get_classifier
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
def classify_koelectra(
    request: QuestionRequest,
    classifier: Annotated[TransformerClassifier, Depends(get_classifier)],
):
    return ClassificationResponse(category=classifier.predict(request.question.strip()))
