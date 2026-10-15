"""Model-free demo reset and index restoration shared by maintenance CLIs."""

from pathlib import Path

from app.documents.context import DocumentContextProvider
from app.documents.reset import reset_demo_documents
from app.retrieval.baseline import restore_baseline, validate_baseline
from app.retrieval.config import DEFAULT_SPEC
from app.retrieval.repository import IndexRepository
from app.retrieval.sync import writer_lock


def reset_with_retrieval(source, database, bundle, root, *, spec=DEFAULT_SPEC):
    """Return partial completion explicitly; never retry the document mutation."""
    report = {"documents_reset": False, "retrieval_ready": False}
    try:
        validate_baseline(bundle, source, spec=spec)
        with writer_lock(root, spec=spec):
            validate_baseline(bundle, source, spec=spec)
            reset = reset_demo_documents(source, database, apply=True)
            report.update(documents_reset=True, restored_count=reset["restored_count"])
            snapshot = DocumentContextProvider(database_path=database).snapshot()
            repository = IndexRepository(root, spec=spec)
            restore_baseline(repository, bundle, source, snapshot)
            report.update(repository.status(snapshot))
            report["retrieval_ready"] = report["ready"]
        report["status"] = "ready" if report["retrieval_ready"] else "incomplete"
    except Exception as exc:  # noqa: BLE001 - safe CLI outcome, no document-bearing errors
        report.update(status="failed", error_type=type(exc).__name__)
    if report["documents_reset"] and not report["retrieval_ready"]:
        report["recovery_hint"] = "python -m scripts.index_documents --restore-baseline"
        report["recovery_environment"] = {
            "SANAEBI_DOCUMENT_DB": str(Path(database).resolve()),
            "SANAEBI_RETRIEVAL_SOURCE": str(Path(source).resolve()),
            "SANAEBI_RETRIEVAL_ROOT": str(Path(root).resolve()),
            "SANAEBI_RETRIEVAL_BASELINE": str(Path(bundle).resolve()),
        }
    return report
