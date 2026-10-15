from contextlib import asynccontextmanager
from dataclasses import replace
from threading import BoundedSemaphore, Lock

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
from app.health import router as health
from app.public_limits import (
    DailyGenerationBudget,
    PublicDemoRateLimitMiddleware,
    get_daily_generation_limit,
    get_generation_budget_path,
    get_max_inflight_asks,
    is_public_demo_enabled,
)
from app.questions import router as questions
from app.settings import (
    PROJECT_ROOT,
    get_answer_provider,
    get_classifier_path,
    get_document_database_path,
    get_embedding_path,
    get_retrieval_baseline,
    get_retrieval_mode,
    get_retrieval_root,
    get_retrieval_source,
    get_routing_mode,
)
from generation.presets import load_runtime_settings


@asynccontextmanager
async def lifespan(application: FastAPI):
    get_answer_provider()
    application.state.routing_mode = get_routing_mode()
    settings = load_runtime_settings(PROJECT_ROOT)
    retrieval_mode = get_retrieval_mode()
    application.state.retrieval_mode = retrieval_mode
    application.state.retriever = None
    application.state.retrieval_sync = None
    if retrieval_mode == "rag":
        from app.settings import get_rag_expand_context, get_rag_prompt_profile

        settings = replace(settings, prompt_profile=get_rag_prompt_profile())
        expand_context = get_rag_expand_context()
        from app.retrieval.config import SERVER_SPEC
        from app.retrieval.embedding import create_embedder
        from app.retrieval.indexer import RetrievalIndexer
        from app.retrieval.repository import IndexRepository
        from app.retrieval.search import policy_for_spec
        from app.retrieval.service import RetrievalService
        from app.retrieval.sync import DocumentIndexSynchronizer

        embedder = create_embedder(get_embedding_path(), spec=SERVER_SPEC)
        embedder.warmup()
        index_repository = IndexRepository(get_retrieval_root(), spec=SERVER_SPEC)
        retrieval_indexer = RetrievalIndexer(
            index_repository, embedder, baseline_path=get_retrieval_baseline()
        )
        application.state.retriever = RetrievalService(
            index_repository,
            embedder,
            search_policy=policy_for_spec(SERVER_SPEC),
            indexer=retrieval_indexer,
            expand_context=expand_context,
        )
    public_demo = is_public_demo_enabled()
    generation_budget = None
    if public_demo:
        generation_budget = DailyGenerationBudget(
            get_generation_budget_path(), get_daily_generation_limit()
        )
        generation_budget.initialize()
    repository = DocumentRepository(get_document_database_path())
    repository.initialize()
    application.state.document_repository = repository
    application.state.document_provider = DocumentContextProvider(repository=repository)
    if retrieval_mode == "rag":
        application.state.retrieval_sync = DocumentIndexSynchronizer(
            repository=index_repository,
            retrieval_indexer=retrieval_indexer,
            document_provider=application.state.document_provider,
            baseline_path=get_retrieval_baseline(),
            source_path=get_retrieval_source(),
        )
    application.state.classifier = TransformerClassifier(get_classifier_path())
    application.state.classifier_warm_lock = Lock()
    application.state.classifier_warmed = False
    application.state.public_demo = public_demo
    application.state.ask_slots = BoundedSemaphore(
        get_max_inflight_asks() if public_demo else 2
    )
    application.state.generation_budget = generation_budget
    application.state.answerer = GenerationAnswerer(
        settings,
        reserve_generation=(
            generation_budget.reserve if generation_budget is not None else None
        ),
    )
    try:
        yield
    finally:
        await application.state.answerer.aclose()


app = FastAPI(lifespan=lifespan)
register_error_handlers(app)
app.add_middleware(ManagedDocumentHttpMiddleware)
app.add_middleware(TraceMiddleware)
app.add_middleware(PublicDemoRateLimitMiddleware)
app.include_router(questions.router)
app.include_router(documents.router)
app.include_router(managed_documents.router)
app.include_router(classification.router)
app.include_router(assistant.router)
app.include_router(health)


@app.get("/")
def home():
    return {"message": "FastAPI 서버가 실행 중입니다."}
