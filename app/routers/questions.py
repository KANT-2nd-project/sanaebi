from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.answer_text import LLMResponseError, extract_answer_text
from app.koelectra_classifier import classify_question
from app.langchain_adapter import generate_assistant_response
from app.schemas import AnswerResponse, QuestionRequest

# /ask에서 답변을 만들 모델 선택: "ollama" 또는 "openai"
PROVIDER = "ollama"

router = APIRouter()


@router.post(
    "/ask",
    response_model=AnswerResponse,
    responses={
        422: {"model": AnswerResponse, "description": "입력 오류"},
        502: {"model": AnswerResponse, "description": "답변 생성 오류"},
        503: {"model": AnswerResponse, "description": "분류 모델 없음"},
    },
)
def ask(request: QuestionRequest, http_request: Request):
    question = request.question.strip()

    # 1. 질문을 분류해 카테고리 가져오기
    try:
        category = classify_question(question)
    except FileNotFoundError:
        response = AnswerResponse(ok=False, text="", reason="분류 모델이 없습니다.")
        return JSONResponse(status_code=503, content=response.model_dump())

    # 2. 질문과 카테고리를 선택한 LangChain 모델에 전달
    response = {"ok": True, "text": question, "reason": ""}
    results = generate_assistant_response(
        response,
        category,
        provider=PROVIDER,
        document_provider=http_request.app.state.document_provider,
    )

    # 3. 선택한 모델의 실제 답변만 반환 (호출 실패는 기존 502 핸들러로 전달)
    result = results[PROVIDER]
    output = result.get("output", {"text": result.get("answer")})
    if not result["success"] or output is None:
        raise LLMResponseError("LangChain 모델 호출에 실패했습니다.")
    text = extract_answer_text(output)
    # 모델이 JSON 문자열로 답했다면 그 안의 text만 한 번 더 꺼내기
    if text.startswith("{"):
        text = extract_answer_text(text)
    return AnswerResponse(ok=True, text=text)
