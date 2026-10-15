from pydantic import BaseModel, Field, model_validator

from contracts.classification import ClassificationLabel


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, pattern=r"\S")


class DocumentRequest(BaseModel):
    doc: str = Field(min_length=1, max_length=50_000, pattern=r"\S")


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

    @model_validator(mode="after")
    def validate_successful_question(self):
        if self.response.ok and not self.response.text.strip():
            raise ValueError("성공한 앞 단계의 질문은 비어 있을 수 없습니다.")
        return self
