from pydantic import BaseModel, Field

from contracts.classification import ClassificationLabel


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, pattern=r"\S")


class DocumentRequest(BaseModel):
    doc: str = Field(min_length=1, pattern=r"\S")


class AnswerResponse(BaseModel):
    ok: bool
    text: str
    reason: str = ""


# 분류 API가 반환하는 세 가지 카테고리
class ClassificationResponse(BaseModel):
    category: ClassificationLabel


# 분류를 마친 질문과 카테고리를 답변 생성 단계로 전달하는 입력
class AssistantRequest(BaseModel):
    response: AnswerResponse  # text에 질문, ok에 앞 단계의 성공 여부
    classification_label: ClassificationLabel
