"""Internal liveness and readiness probes for deployment orchestration."""

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.classification.predictor import (
    ClassificationInferenceError,
    ClassificationUnavailable,
)
from app.documents.context import DocumentStorageError
from app.retrieval.types import RetrievalNotReady, RetrievalUnavailable
from app.settings import PROJECT_ROOT, get_answer_provider
from generation.presets import load_runtime_settings

router = APIRouter()


@router.get("/health/live", include_in_schema=False)
def live():
    return JSONResponse({"status": "live"}, headers={"Cache-Control": "no-store"})


@router.get("/health/ready", include_in_schema=False)
def ready(request: Request):
    try:
        get_answer_provider()
        load_runtime_settings(PROJECT_ROOT)
        if not os.getenv("OPENAI_API_KEY", "").strip():
            raise ValueError("generation credentials are not configured")

        application = request.app
        snapshot = application.state.document_provider.snapshot()
        if (
            application.state.retriever is not None
            and not application.state.retriever.status(snapshot)["ready"]
        ):
            raise RetrievalNotReady("Retrieval is not ready")
        if application.state.retriever is not None:
            application.state.retrieval_sync.preflight_restore()
        with application.state.classifier_warm_lock:
            if not application.state.classifier_warmed:
                application.state.classifier.predict("서비스 준비 상태 확인")
                application.state.classifier_warmed = True
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ClassificationUnavailable,
        ClassificationInferenceError,
        DocumentStorageError,
        RetrievalUnavailable,
        RetrievalNotReady,
    ):
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready"},
            headers={"Cache-Control": "no-store"},
        )

    return JSONResponse({"status": "ready"}, headers={"Cache-Control": "no-store"})
