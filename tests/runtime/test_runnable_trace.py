"""Trace safety and naming contracts that do not require the HTTP app."""

import json
import unittest

from langchain_core.runnables import RunnableLambda

from app.diagnostics import trace
from app.documents.context import DocumentContext, DocumentContextSnapshot


class RunnableTraceTests(unittest.TestCase):
    def test_named_stage_keeps_only_allowlisted_metadata(self):
        callback = trace.TraceCallback()
        runnable = RunnableLambda(
            lambda state: {
                "selected_count": 1,
                "documents": ["PRIVATE UNSELECTED DOCUMENT"],
                "answer": "PRIVATE ANSWER",
            }
        ).with_config(
            **trace.named_trace_config(
                run_name="rag.retrieve",
                stage="검색",
                role="retriever",
            )
        )
        runnable.invoke(
            {
                "question": "PRIVATE QUESTION",
                "snapshot": self._snapshot("PRIVATE SNAPSHOT DOCUMENT"),
                "selected_count": 1,
                "selected_chunk_ids": ["chunk-1"],
            },
            config={
                "callbacks": [callback],
                "metadata": {"search_config_id": "kure-v1"},
            },
        )

        rows = callback.stage_rows()
        row = next(item for item in rows if item["name"] == "rag.retrieve")
        self.assertEqual(row["stage"], "검색")
        self.assertEqual(row["role"], "retriever")
        self.assertEqual(row["metadata"], {"search_config_id": "kure-v1"})
        self.assertEqual(
            row["input"], {"selected_count": 1, "selected_chunk_ids": ["chunk-1"]}
        )
        self.assertEqual(row["output"], {"selected_count": 1})
        serialized = json.dumps(rows, ensure_ascii=False)
        for private_value in (
            "PRIVATE QUESTION",
            "PRIVATE SNAPSHOT DOCUMENT",
            "PRIVATE UNSELECTED DOCUMENT",
            "PRIVATE ANSWER",
        ):
            self.assertNotIn(private_value, serialized)

    def test_empty_retrieval_processing_path_is_retained(self):
        callback = trace.TraceCallback()
        callback.record_routing(
            {"processing_path": "empty_retrieval", "generation_attempted": False}
        )

        [classification] = callback.record_rows("/ask", {"question": "q"}, 200)
        self.assertEqual(classification["processing_path"], "empty_retrieval")
        self.assertFalse(classification["generation_attempted"])

    def test_only_contract_classification_label_is_retained_from_chain_input(self):
        callback = trace.TraceCallback()
        callback.on_chain_start(
            {"name": "RunnableLambda"},
            {
                "classification_label": "SEARCH_KNOWLEDGE",
                "question": "PRIVATE QUESTION",
            },
            run_id="known-label",
        )
        callback.on_chain_start(
            {"name": "RunnableLambda"},
            {"classification_label": "PRIVATE QUESTION"},
            run_id="invalid-label",
        )

        rows = callback.stage_rows()
        self.assertEqual(rows[0]["input"], {"classification_label": "SEARCH_KNOWLEDGE"})
        self.assertEqual(rows[1]["input"], {})
        record_rows = callback.record_rows("/ask", {"question": "q"}, 200)
        self.assertEqual(record_rows[0]["output"], "SEARCH_KNOWLEDGE")
        serialized = json.dumps(rows, ensure_ascii=False)
        self.assertNotIn("PRIVATE QUESTION", serialized)

    def test_generation_summary_retains_finish_reason(self):
        callback = trace.TraceCallback()
        callback.record_generation(
            {"status": "truncated", "finish_reason": "length", "seconds": 1.2}
        )

        rows = callback.record_rows("/ask", {"question": "q"}, 502)
        generation = next(row for row in rows if row["stage"] == trace.GENERATION_STAGE)
        self.assertEqual(generation["status"], "truncated")
        self.assertEqual(generation["finish_reason"], "length")

    def test_retrieval_event_keeps_safe_identifiers_and_scores_only(self):
        callback = trace.TraceCallback()
        token = trace._current_trace.set(callback)
        try:
            trace.record_retrieval(
                status="ok",
                seconds=0.125,
                selected_count=1,
                metadata={
                    "snapshot_fingerprint": "snapshot-hash",
                    "spec_id": "kure-spec-v2",
                    "search_config_id": "kure-search-v1",
                    "candidate_count": 4,
                    "selected_chunk_ids": ["chunk-7"],
                    "scores": [0.91],
                    "ranks": [1],
                    "documents": ["PRIVATE DOCUMENT"],
                    "question": "PRIVATE QUESTION",
                },
            )
        finally:
            trace._current_trace.reset(token)

        rows = callback.record_rows("/ask", {"question": "q"}, 200)
        retrieval = next(row for row in rows if row["stage"] == "검색")
        self.assertEqual(retrieval["snapshot_fingerprint"], "snapshot-hash")
        self.assertEqual(retrieval["spec_id"], "kure-spec-v2")
        self.assertEqual(retrieval["search_config_id"], "kure-search-v1")
        self.assertEqual(retrieval["candidate_count"], 4)
        self.assertEqual(retrieval["selected_chunk_ids"], ["chunk-7"])
        self.assertEqual(retrieval["scores"], [0.91])
        self.assertEqual(retrieval["ranks"], [1])
        self.assertEqual(retrieval["selected_count"], 1)
        serialized = json.dumps(rows, ensure_ascii=False)
        self.assertNotIn("PRIVATE DOCUMENT", serialized)
        self.assertNotIn("PRIVATE QUESTION", serialized)

    def test_runnable_errors_keep_type_without_exception_input(self):
        callback = trace.TraceCallback()
        callback.on_chain_start(
            {"name": "RunnableLambda"},
            {"selected_count": 1},
            run_id="failing-stage",
        )
        callback.on_chain_error(
            RuntimeError("PRIVATE QUESTION AND DOCUMENT BODY"),
            run_id="failing-stage",
        )

        [row] = callback.stage_rows()
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], "RuntimeError")
        self.assertNotIn("PRIVATE QUESTION", json.dumps(row, ensure_ascii=False))
        self.assertNotIn("DOCUMENT BODY", json.dumps(row, ensure_ascii=False))

    @staticmethod
    def _snapshot(body: str) -> DocumentContextSnapshot:
        return DocumentContextSnapshot(
            (
                DocumentContext(
                    document_id="doc-1",
                    knowledge_id="knowledge-1",
                    revision_id="revision-1",
                    revision=1,
                    title="Policy",
                    body=body,
                    source_reference="document:knowledge-1",
                    content_hash="content-hash",
                    metadata={},
                ),
            )
        )


if __name__ == "__main__":
    unittest.main()
