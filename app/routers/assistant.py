from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.koelectra_classifier import classify_question
from app.langchain_adapter import generate_assistant_response
from app.schemas import AnswerResponse, AssistantRequest, QuestionRequest
from app.services.question_service import (
    ClassificationModelUnavailable,
    answer_question,
)

router = APIRouter()


@router.post(
    "/assistant",
    summary="질문과 카테고리로 LangChain 답변 생성",
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
def ask_assistant(request: AssistantRequest) -> dict:
    # model_dump는 Pydantic 입력 객체를 일반 사전으로 변환
    return generate_assistant_response(
        response=request.response.model_dump(),
        category=request.classification_label,
    )


@router.post(
    "/ask/langchain",
    summary="KoELECTRA 자동 분류 후 LangChain 답변 생성",
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        503: {"model": AnswerResponse, "description": "분류 모델 없음"},
    },
)
def ask_with_classification(request: QuestionRequest):
    # 처리 순서는 서비스 함수에 맡기고 실제 분류기와 연결 함수를 전달
    try:
        return answer_question(
            question=request.question,
            classify=classify_question,
            generate=generate_assistant_response,
        )
    except ClassificationModelUnavailable:
        response = AnswerResponse(ok=False, text="", reason="분류 모델이 없습니다.")
        return JSONResponse(status_code=503, content=response.model_dump())
