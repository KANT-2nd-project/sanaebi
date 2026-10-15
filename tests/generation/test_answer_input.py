import unittest
from datetime import UTC, datetime

from app.answering.input import AnswerInput
from app.documents.context import DocumentContext, DocumentContextSnapshot
from app.retrieval.types import Evidence, RetrievedContext, SourceSpan
from generation.advisory import ClassificationContext
from generation.documents import render_document


class AnswerInputTests(unittest.TestCase):
    def test_snapshot_factory_renders_documents_in_order_once(self):
        snapshot = DocumentContextSnapshot(
            (
                DocumentContext(
                    "db-1",
                    "source-1",
                    "revision-1",
                    2,
                    "첫 문서",
                    "첫 내용",
                    "source:1",
                    "hash-1",
                    {},
                ),
                DocumentContext(
                    "db-2",
                    "source-2",
                    "revision-2",
                    3,
                    "둘째 문서",
                    "둘째 내용",
                    "source:2",
                    "hash-2",
                    {},
                ),
            )
        )
        advisory = ClassificationContext("SEARCH_KNOWLEDGE")

        result = AnswerInput.from_snapshot(
            "질문", snapshot, classification_context=advisory
        )

        self.assertEqual(
            result.documents,
            (
                render_document("source-1", "첫 문서", "첫 내용", 2),
                render_document("source-2", "둘째 문서", "둘째 내용", 3),
            ),
        )
        self.assertEqual(result.snapshot_fingerprint, snapshot.fingerprint)
        self.assertIs(result.classification_context, advisory)

    def test_retrieved_factory_preserves_source_prefix_and_state(self):
        context = RetrievedContext(
            snapshot_fingerprint="snapshot-hash",
            spec_id="spec",
            evidence=(
                Evidence(
                    knowledge_id="source-3",
                    document_id="db-3",
                    revision_id="revision-3",
                    revision=4,
                    title="게시 문서",
                    text="검색 발췌",
                    source_reference="source:3",
                    spans=(SourceSpan(0, 5),),
                    chunk_ids=("chunk-1",),
                    score=0.9,
                    rank=1,
                ),
            ),
            candidate_count=1,
            selected_count=1,
            observed_at=datetime.now(UTC),
            source_document_count=1,
        )

        result = AnswerInput.from_retrieved("질문", context)

        self.assertEqual(
            result.documents,
            (
                "[현재 게시 문서의 발췌 근거]\n"
                + render_document("source-3", "게시 문서", "검색 발췌", 4),
            ),
        )
        self.assertEqual(result.evidence_state, "available")
        self.assertEqual(result.snapshot_fingerprint, "snapshot-hash")

    def test_empty_retrieved_factory_distinguishes_empty_corpus_and_no_match(self):
        for document_count, expected in (
            (0, "no_published_documents"),
            (4, "no_matches"),
        ):
            with self.subTest(document_count=document_count):
                context = RetrievedContext(
                    snapshot_fingerprint="snapshot-hash",
                    spec_id="spec",
                    evidence=(),
                    candidate_count=0,
                    selected_count=0,
                    observed_at=datetime.now(UTC),
                    source_document_count=document_count,
                )

                result = AnswerInput.from_retrieved("질문", context)

                self.assertEqual(result.documents, ())
                self.assertEqual(result.evidence_state, expected)


if __name__ == "__main__":
    unittest.main()
