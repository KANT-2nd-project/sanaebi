from dataclasses import replace

from app.retrieval.expansion import expand_evidence
from app.retrieval.types import Chunk, Evidence, SourceSpan
from tests.retrieval.helpers import RetrievalTestCase, make_document, make_snapshot


class ContextExpansionTests(RetrievalTestCase):
    @staticmethod
    def _chunk(document, chunk_id, ordinal, start, end):
        return Chunk(
            document_id=document.document_id,
            revision_id=document.revision_id,
            ordinal=ordinal,
            spans=(SourceSpan(start, end),),
            heading="",
            embedding_header=document.title,
            text=document.body[start:end],
            embedding_text=document.body[start:end],
            input_key=f"key-{chunk_id}",
            chunk_id=chunk_id,
        )

    @staticmethod
    def _evidence(document, chunk, *, rank=1, score=0.8):
        return Evidence(
            knowledge_id=document.knowledge_id,
            document_id=document.document_id,
            revision_id=document.revision_id,
            revision=document.revision,
            title=document.title,
            text="\n".join(
                document.body[span.start : span.end] for span in chunk.spans
            ),
            source_reference=document.source_reference,
            spans=chunk.spans,
            chunk_ids=(chunk.chunk_id,),
            score=score,
            rank=rank,
        )

    def test_short_document_expands_to_whole_body_and_preserves_hit_provenance(self):
        document = make_document(body="도입\n신고\n담당 인계")
        snapshot = make_snapshot(document)
        hit = self._chunk(document, "hit", 1, 3, 5)
        neighbor = self._chunk(document, "neighbor", 0, 0, 2)

        expanded = expand_evidence(
            [self._evidence(document, hit)], [(hit, None), (neighbor, None)], snapshot
        )

        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0].text, document.body)
        self.assertEqual(expanded[0].spans, (SourceSpan(0, len(document.body)),))
        self.assertEqual(expanded[0].chunk_ids, ("hit",))
        self.assertEqual(expanded[0].expanded_chunk_ids, ("neighbor",))
        self.assertEqual(expanded[0].original_spans, (SourceSpan(3, 5),))
        self.assertEqual(
            expanded[0].expanded_spans,
            (SourceSpan(0, 3), SourceSpan(5, len(document.body))),
        )
        self.assertEqual(expanded[0].score, 0.8)
        self.assertEqual(expanded[0].rank, 1)

    def test_only_first_three_distinct_documents_are_expanded(self):
        documents = [
            make_document(
                document_id=f"doc-{index}",
                knowledge_id=f"knowledge-{index}",
                revision_id=f"rev-{index}",
                body=f"document-{index}",
            )
            for index in range(4)
        ]
        snapshot = make_snapshot(*documents)
        chunks = [
            self._chunk(document, f"hit-{index}", 0, 0, 1)
            for index, document in enumerate(documents)
        ]
        evidence = [
            self._evidence(document, chunk, rank=index + 1)
            for index, (document, chunk) in enumerate(
                zip(documents, chunks, strict=True)
            )
        ]

        expanded = expand_evidence(
            evidence, [(chunk, None) for chunk in chunks], snapshot
        )

        self.assertEqual(
            [item.text for item in expanded],
            [documents[0].body, documents[1].body, documents[2].body, "d"],
        )
        self.assertEqual(
            [item.expanded_chunk_ids for item in expanded],
            [(), (), (), ()],
        )

    def test_expansion_budget_skips_oversized_unit_but_keeps_original_evidence(self):
        documents = [
            make_document(
                document_id=f"budget-doc-{index}",
                knowledge_id=f"budget-{index}",
                revision_id=f"budget-rev-{index}",
                body=body,
            )
            for index, body in enumerate(("a" * 3500, "b" * 2800, "c" * 1000))
        ]
        snapshot = make_snapshot(*documents)
        chunks = [
            self._chunk(document, f"budget-hit-{index}", 0, 0, 1)
            for index, document in enumerate(documents)
        ]
        evidence = [
            self._evidence(document, chunk, rank=index + 1)
            for index, (document, chunk) in enumerate(
                zip(documents, chunks, strict=True)
            )
        ]

        expanded = expand_evidence(
            evidence, [(chunk, None) for chunk in chunks], snapshot
        )

        self.assertEqual(
            [item.text for item in expanded], ["a" * 3500, "b", "c" * 1000]
        )
        self.assertEqual(
            [item.chunk_ids for item in expanded],
            [("budget-hit-0",), ("budget-hit-1",), ("budget-hit-2",)],
        )

    def test_long_document_adds_only_nonrecursive_neighbors_from_same_revision(self):
        body = "x" * 5000
        document = make_document(body=body)
        old_revision = make_document(revision_id="revision-old", body=body)
        snapshot = make_snapshot(document)
        chunks = [
            self._chunk(
                document, f"chunk-{index}", index, index * 1000, (index + 1) * 1000
            )
            for index in range(5)
        ]
        old_neighbor = replace(
            self._chunk(old_revision, "old-revision-neighbor", 1, 1000, 2000),
            revision_id=old_revision.revision_id,
        )

        expanded = expand_evidence(
            [self._evidence(document, chunks[2])],
            [(chunk, None) for chunk in chunks] + [(old_neighbor, None)],
            snapshot,
        )

        self.assertEqual(
            expanded[0].text,
            body[1000:2000] + "\n" + body[2000:3000] + "\n" + body[3000:4000],
        )
        self.assertEqual(
            expanded[0].spans,
            (SourceSpan(1000, 2000), SourceSpan(2000, 3000), SourceSpan(3000, 4000)),
        )
        self.assertEqual(expanded[0].chunk_ids, ("chunk-2",))
        self.assertEqual(expanded[0].expanded_chunk_ids, ("chunk-1", "chunk-3"))
        self.assertEqual(expanded[0].original_spans, (SourceSpan(2000, 3000),))
        self.assertEqual(
            expanded[0].expanded_spans,
            (SourceSpan(1000, 2000), SourceSpan(3000, 4000)),
        )

    def test_overlapping_same_revision_evidence_merges_spans_and_deduplicates_text(
        self,
    ):
        document = make_document(body="0123456789" + "x" * 5000)
        snapshot = make_snapshot(document)
        first = self._chunk(document, "first", 0, 0, 6)
        second = self._chunk(document, "second", 1, 4, 9)
        first_evidence = replace(
            self._evidence(document, first, rank=2, score=0.7), text="012345"
        )
        second_evidence = replace(
            self._evidence(document, second, rank=1, score=0.9), text="45678"
        )

        expanded = expand_evidence(
            [second_evidence, first_evidence],
            [],
            snapshot,
        )

        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0].text, document.body[:9])
        self.assertEqual(expanded[0].spans, (SourceSpan(0, 9),))
        self.assertEqual(expanded[0].chunk_ids, ("first", "second"))
        self.assertEqual(expanded[0].expanded_chunk_ids, ())
        self.assertEqual(expanded[0].score, 0.9)
        self.assertEqual(expanded[0].rank, 1)
        self.assertEqual(expanded[0].original_spans, (SourceSpan(0, 9),))
        self.assertEqual(expanded[0].expanded_spans, ())

    def test_long_document_does_not_use_neighbor_from_another_revision(self):
        body = "x" * 5000
        document = make_document(body=body, revision_id="current")
        old_revision = make_document(body=body, revision_id="old")
        snapshot = make_snapshot(document)
        anchor = self._chunk(document, "current-anchor", 1, 1000, 2000)
        wrong_revision_neighbor = self._chunk(
            old_revision, "old-neighbor", 2, 2000, 3000
        )

        expanded = expand_evidence(
            [self._evidence(document, anchor)],
            [(anchor, None), (wrong_revision_neighbor, None)],
            snapshot,
        )

        self.assertEqual(expanded[0].text, body[1000:2000])
        self.assertEqual(expanded[0].chunk_ids, ("current-anchor",))
        self.assertEqual(expanded[0].expanded_chunk_ids, ())
        self.assertEqual(expanded[0].original_spans, ())
        self.assertEqual(expanded[0].expanded_spans, ())
