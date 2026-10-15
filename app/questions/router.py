import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.dependencies import QuestionHandler, get_question_handler
from app.public_limits import is_public_demo_enabled
from app.schemas import AnswerResponse, QuestionRequest

router = APIRouter()
_ASK_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sanaebi-ask")


async def _run_handler_and_release_slot(handle, question: str, slots):
    if slots is None:
        return await anyio.to_thread.run_sync(handle, question, abandon_on_cancel=False)

    try:
        context = copy_context()
        worker = _ASK_EXECUTOR.submit(context.run, handle, question)
    except Exception:
        slots.release()
        raise

    worker.add_done_callback(lambda _: slots.release())
    try:
        return await asyncio.wrap_future(worker)
    except asyncio.CancelledError:
        worker.cancel()
        raise


@router.post(
    "/ask",
    response_model=AnswerResponse,
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        429: {"model": AnswerResponse, "description": "요청 또는 생성 한도 초과"},
        502: {"model": AnswerResponse, "description": "답변 생성 오류"},
        503: {
            "model": AnswerResponse,
            "description": "분류 모델, 문서 저장소 또는 검색 사용 불가",
        },
    },
)
async def ask(
    payload: QuestionRequest,
    handle: Annotated[QuestionHandler, Depends(get_question_handler)],
    http_request: Request,
):
    slots = None
    if is_public_demo_enabled():
        slots = http_request.app.state.ask_slots
        if not slots.acquire(blocking=False):
            return JSONResponse(
                status_code=429,
                content=AnswerResponse(
                    ok=False,
                    text="",
                    reason="현재 질문 요청이 많습니다. 잠시 후 다시 시도해주세요.",
                ).model_dump(),
                headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )
    result = await _run_handler_and_release_slot(
        handle, payload.question.strip(), slots
    )
    return AnswerResponse(ok=True, text=result.text)
