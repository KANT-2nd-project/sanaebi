"""Explicit local preparation; never reset or import into an existing database."""

import argparse
import json
import os
import uuid

from app.documents.context import DocumentContextProvider
from app.documents.transfer import import_knowledge
from app.retrieval.baseline import prepare_baseline, validate_baseline
from app.retrieval.config import SERVER_SPEC
from app.retrieval.embedding import create_embedder
from app.retrieval.indexer import RetrievalIndexer
from app.retrieval.repository import IndexRepository
from app.retrieval.sync import writer_lock
from app.settings import (
    PROJECT_ROOT,
    get_document_database_path,
    get_embedding_path,
    get_retrieval_baseline,
    get_retrieval_mode,
    get_retrieval_root,
    get_retrieval_source,
)
from scripts.deployment_embedding import prepare_embedding
from scripts.local_runtime import check_model, check_prerequisites, diagnose


def prepare(*, init_documents=False):
    errors = check_prerequisites()
    if errors:
        return {"ready": False, "errors": errors}
    mode = get_retrieval_mode()
    database = get_document_database_path()
    # Existing files, including intentionally empty stores, are always read-only here.
    if database.exists():
        DocumentContextProvider(database_path=database).snapshot()
    elif not init_documents:
        return {"ready": False, "errors": ["database_missing"]}
    source = get_retrieval_source()
    embedder = None
    baseline = None
    if mode == "rag":
        baseline = get_retrieval_baseline()  # validate source before downloads/writes
        model = get_embedding_path()
        if model.exists():
            check_model()
        else:
            if os.getenv("SANAEBI_EMBEDDING_PATH"):
                return {"ready": False, "errors": ["explicit_model_missing"]}
            prepared = prepare_embedding(
                PROJECT_ROOT / "deployment/retrieval-release.json",
                PROJECT_ROOT / "artifacts/embeddings",
            )
            if prepared != model:
                raise ValueError("model path mismatch")
        embedder = create_embedder(model, spec=SERVER_SPEC)
        if baseline.exists():
            validate_baseline(baseline, source, spec=SERVER_SPEC)
        elif os.getenv("SANAEBI_RETRIEVAL_BASELINE"):
            return {"ready": False, "errors": ["explicit_baseline_missing"]}
        else:
            baseline = prepare_baseline(
                source,
                PROJECT_ROOT / "artifacts/retrieval-baselines",
                embedder,
                spec=SERVER_SPEC,
            )
    # Serialize concurrent setup calls; recheck existence inside the lock.
    with writer_lock(get_retrieval_root(), spec=SERVER_SPEC):
        if not database.exists():
            database.parent.mkdir(parents=True, exist_ok=True)
            # Import off to the side. Failure must not poison the authoritative path.
            staged = database.with_name(f".local-setup-{uuid.uuid4().hex}.sqlite3")
            import_knowledge(source, staged, apply=True, publish=True)
            DocumentContextProvider(database_path=staged).snapshot()
            try:
                os.link(staged, database)  # never replace a concurrently created store
            finally:
                # Successful import is retained if another writer won publication.
                if database.exists() and os.path.samefile(staged, database):
                    staged.unlink()
        snapshot = DocumentContextProvider(database_path=database).snapshot()
        if mode == "rag":
            indexer = RetrievalIndexer(
                IndexRepository(get_retrieval_root(), spec=SERVER_SPEC),
                embedder,
                baseline_path=baseline,
            )
            indexer.reconcile(snapshot)
    return diagnose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-documents", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = prepare(init_documents=args.init_documents)
    except Exception as exc:  # noqa: BLE001 - preserve partial results, never print secrets
        result = {
            "ready": False,
            "errors": ["preparation_failed"],
            "error_type": type(exc).__name__,
        }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
