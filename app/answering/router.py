from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.dependencies import AssistantHandler, get_assistant_handler
from app.diagnostics.trace import record_routing
from app.schemas import AnswerResponse, AssistantRequest

router = APIRouter()


@router.post(
    "/assistant",
    summary="이미 분류한 질문으로 Luna 답변 생성",
    response_model=AnswerResponse,
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        502: {"model": AnswerResponse, "description": "답변 생성 오류"},
        503: {"model": AnswerResponse, "description": "문서 저장소 사용 불가"},
    },
)
def ask_assistant(
    request: AssistantRequest,
    http_request: Request,
    handle: Annotated[AssistantHandler, Depends(get_assistant_handler)],
) -> AnswerResponse:
    if not request.response.ok:
        record_routing(
            {
                "routing_mode": http_request.app.state.routing_mode,
                "label_source": "client",
                "classification_status": "not_run",
                "classification_elapsed_seconds": None,
                "processing_path": "upstream_failure",
                "generation_attempted": False,
            }
        )
        return AnswerResponse(
            ok=False, text="", reason="이전 단계에서 요청을 처리하지 못했습니다."
        )
    result = handle(request.response.text.strip(), request.classification_label)
    return AnswerResponse(ok=True, text=result.text)
