"""Gradio boundary shares the echo helpers, not an HTTP route."""

from app.answer_text import extract_answer_text, generate_answer
from app.schemas import QuestionRequest


def answer_question(question: str) -> str:
    request = QuestionRequest(question=question)
    return extract_answer_text(generate_answer(request.question.strip()))
