from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.answering import router as assistant
from app.answering.adapter import GenerationAnswerer
from app.classification import router as classification
from app.classification.predictor import (
    TransformerClassifier,
)
from app.diagnostics.trace import TraceMiddleware
from app.documents import registration as documents
from app.documents import router as managed_documents
from app.documents.context import DocumentContextProvider
from app.documents.http import (
    ManagedDocumentHttpMiddleware,
)
from app.documents.repository import DocumentRepository
from app.errors import register_error_handlers
from app.questions import router as questions
from app.settings import (
    PROJECT_ROOT,
    get_answer_provider,
    get_classifier_path,
    get_document_database_path,
    get_routing_mode,
)
from generation.presets import load_runtime_settings


@asynccontextmanager
async def lifespan(application: FastAPI):
    get_answer_provider()
    application.state.routing_mode = get_routing_mode()
    settings = load_runtime_settings(PROJECT_ROOT)
    repository = DocumentRepository(get_document_database_path())
    repository.initialize()
    application.state.document_repository = repository
    application.state.document_provider = DocumentContextProvider(repository=repository)
    application.state.classifier = TransformerClassifier(get_classifier_path())
    application.state.answerer = GenerationAnswerer(settings)
    try:
        yield
    finally:
        await application.state.answerer.aclose()


app = FastAPI(lifespan=lifespan)
register_error_handlers(app)
app.add_middleware(ManagedDocumentHttpMiddleware)
app.add_middleware(TraceMiddleware)
app.include_router(questions.router)
app.include_router(documents.router)
app.include_router(managed_documents.router)
app.include_router(classification.router)
app.include_router(assistant.router)


@app.get("/")
def home():
    return {"message": "FastAPI 서버가 실행 중입니다."}
