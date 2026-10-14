import json
from pathlib import Path

from fastapi import APIRouter

from app.schemas import AnswerResponse, DocumentRequest

router = APIRouter()

DOCUMENT_FILE = Path(__file__).resolve().parent.parent / "documents.jsonl"


@router.post(
    "/regist-docs",
    response_model=AnswerResponse,
    responses={422: {"model": AnswerResponse, "description": "입력 오류"}},
)
def register_document(request: DocumentRequest) -> AnswerResponse:
    document = {"doc": request.doc.strip()}
    with DOCUMENT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, ensure_ascii=False) + "\n")
    return AnswerResponse(ok=True, text="문서가 등록되었습니다.")
