"""Inject the runtime document snapshot into the generation executor."""


def generate_assistant_response(
    response: dict,
    category: str,
    *,
    provider: str | None = None,
    document_provider=None,
) -> dict:
    from app.services.document_context import DocumentContextProvider
    from sanaebi_assistant import process_response

    snapshot = None
    if response.get("ok") and category == "SEARCH_KNOWLEDGE":
        snapshot = (document_provider or DocumentContextProvider()).snapshot()
    return process_response(
        response,
        classification_label=category,
        provider=provider,
        document_snapshot=snapshot,
    )
