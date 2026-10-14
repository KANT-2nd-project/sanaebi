from pydantic import BaseModel, Field


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, pattern=r"\S")


class DocumentRequest(BaseModel):
    doc: str = Field(min_length=1, pattern=r"\S")


class AnswerResponse(BaseModel):
    ok: bool
    text: str
    reason: str = ""
