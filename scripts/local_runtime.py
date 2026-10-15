"""Read-only local runtime diagnostics. No model inference or implicit writes."""

import argparse
import json
import os

from app.documents.context import DocumentContextProvider, DocumentStorageError
from app.retrieval.baseline import validate_baseline
from app.retrieval.config import SERVER_SPEC
from app.retrieval.repository import IndexRepository
from app.retrieval.types import RetrievalUnavailable
from app.settings import (
    PROJECT_ROOT,
    get_classifier_path,
    get_document_database_path,
    get_embedding_path,
    get_retrieval_baseline,
    get_retrieval_mode,
    get_retrieval_root,
    get_retrieval_source,
)
from scripts.deployment_embedding import (
    ReleaseError,
    parse_manifest,
    validate_model_directory,
)


def check_prerequisites():
    errors = []
    classifier = get_classifier_path()
    if not all(
        (classifier / name).is_file()
        for name in (
            "config.json",
            "metadata.json",
            "model.safetensors",
            "tokenizer.json",
        )
    ):
        errors.append("classifier_missing")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        errors.append("generation_credentials_missing")
    return errors


def check_model():
    release = parse_manifest(
        (PROJECT_ROOT / "deployment/retrieval-release.json").read_bytes()
    )
    validate_model_directory(get_embedding_path(), release)


def diagnose():
    errors = check_prerequisites()
    result = {"errors": errors}
    try:
        mode = get_retrieval_mode()
        result["mode"] = mode
        database = get_document_database_path()
        result["database"] = str(database)
        snapshot = None
        if not database.is_file():
            errors.append("database_missing")
        else:
            try:
                snapshot = DocumentContextProvider(database_path=database).snapshot()
                result["published_documents"] = len(snapshot.documents)
            except DocumentStorageError:
                errors.append("database_invalid")
        if mode == "rag":
            try:
                check_model()
            except (OSError, ValueError, ReleaseError):
                errors.append("model_missing_or_invalid")
            baseline = get_retrieval_baseline()
            result.update(
                baseline=str(baseline), retrieval_root=str(get_retrieval_root())
            )
            if not baseline.is_file():
                errors.append("baseline_missing")
            else:
                try:
                    validate_baseline(
                        baseline, get_retrieval_source(), spec=SERVER_SPEC
                    )
                    result["restore_ready"] = True
                except RetrievalUnavailable:
                    errors.append("baseline_mismatch")
            if snapshot is not None:
                status = IndexRepository(get_retrieval_root(), spec=SERVER_SPEC).status(
                    snapshot
                )
                result["index_ready"] = status["ready"]
                if not status["ready"]:
                    errors.append("index_not_ready")
    except (OSError, ValueError, RetrievalUnavailable):
        errors.append("configuration_invalid")
    result["ready"] = not errors
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = diagnose()
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif result["ready"]:
        print(f"Local runtime ready ({result['mode']}).")
    else:
        print("Local runtime not ready: " + ", ".join(result["errors"]))
        print("Run npm run setup:local (new database: add -- --init-documents).")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
