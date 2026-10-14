from fastapi import APIRouter, Request

from app.langchain_adapter import generate_assistant_response
from app.schemas import AnswerResponse, AssistantRequest

router = APIRouter()


@router.post(
    "/assistant",
    summary="질문과 카테고리로 LangChain 답변 생성",
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
def ask_assistant(request: AssistantRequest, http_request: Request) -> dict:
    # model_dump는 Pydantic 입력 객체를 일반 사전으로 변환
    return generate_assistant_response(
        response=request.response.model_dump(),
        category=request.classification_label,
        document_provider=http_request.app.state.document_provider,
    )
