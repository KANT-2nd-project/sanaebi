import unittest

from app.retrieval.types import Chunk, SourceSpan
from generation.documents import render_document
from retrieval.experiments.calibration_search import proxy_tokens, select_evidence
from tests.retrieval.helpers import WordTokenizer, make_document, make_snapshot


class ContextBudgetTests(unittest.TestCase):
    def test_budget_counts_actual_proxy_tokens_and_preserves_source_positions(self):
        body = " ".join(f"word{i}" for i in range(500))
        document = make_document(body=body)
        snapshot = make_snapshot(document)
        chunk = Chunk(
            document_id=document.document_id,
            revision_id=document.revision_id,
            ordinal=0,
            spans=(SourceSpan(0, len(body)),),
            heading="",
            embedding_header="",
            text=body,
            embedding_text=body,
            input_key="key",
            chunk_id="chunk",
        )
        tokenizer = WordTokenizer()
        evidence = select_evidence([(chunk, 0.8)], snapshot, 5, tokenizer, 40)
        self.assertTrue(evidence)
        rendered = "\n\n".join(
            "[현재 게시 문서의 발췌 근거]\n"
            + render_document(e.knowledge_id, e.title, e.text, e.revision)
            for e in evidence
        )
        self.assertLessEqual(len(tokenizer.encode(rendered)), 40)
        self.assertLessEqual(proxy_tokens(tokenizer, evidence), 40)
        for item in evidence:
            self.assertEqual(
                item.text, "\n".join(body[s.start : s.end] for s in item.spans)
            )
        self.assertEqual(select_evidence([(chunk, 0.8)], snapshot, 5, tokenizer, 0), [])

    def test_empty_evidence_stays_empty(self):
        self.assertEqual(
            select_evidence([], make_snapshot(), 5, WordTokenizer(), 1000), []
        )

    def test_unlimited_removes_merge_per_item_total_and_count_caps(self):
        from dataclasses import replace

        documents = [
            make_document(
                document_id=f"d{i}",
                knowledge_id=f"k{i}",
                revision_id=f"r{i}",
                body=" ".join(f"w{j}" for j in range(1600)),
            )
            for i in range(6)
        ]
        hits = []
        for i, d in enumerate(documents):
            first = Chunk(
                document_id=d.document_id,
                revision_id=d.revision_id,
                ordinal=0,
                spans=(SourceSpan(0, 4500),),
                heading="",
                embedding_header="",
                text=d.body[:4500],
                embedding_text="unused",
                input_key=f"i{i}",
                chunk_id=f"c{i}a",
            )
            second = replace(
                first,
                ordinal=1,
                spans=(SourceSpan(4000, len(d.body)),),
                text=d.body[4000:],
                chunk_id=f"c{i}b",
            )
            hits.extend([(first, 0.9 - i * 0.01), (second, 0.8 - i * 0.01)])
        snapshot = make_snapshot(*documents)
        original = select_evidence(hits, snapshot, float("inf"), WordTokenizer(), 4000)
        full = select_evidence(
            hits,
            snapshot,
            float("inf"),
            WordTokenizer(),
            None,
            total_chars=None,
            per_evidence_chars=None,
        )
        self.assertEqual(len(full), 6)
        self.assertGreater(sum(len(e.text) for e in full), 8000)
        self.assertEqual(
            {e.document_id: e.text for e in full},
            {d.document_id: d.body for d in documents},
        )
        self.assertTrue(all(len(e.chunk_ids) == 2 for e in full))
        self.assertTrue(all(len(e.text) <= 2000 for e in original))
        bounded = select_evidence(
            hits,
            snapshot,
            float("inf"),
            WordTokenizer(),
            4000,
            total_chars=None,
            per_evidence_chars=None,
        )
        self.assertLessEqual(proxy_tokens(WordTokenizer(), bounded), 4000)
        self.assertGreater(max(len(e.text) for e in bounded), 2000)
        for e in bounded:
            body = next(d.body for d in documents if d.document_id == e.document_id)
            self.assertEqual(e.text, "\n".join(body[s.start : s.end] for s in e.spans))
        from app.retrieval import service

        self.assertEqual(service.MAX_EVIDENCE_CHARS, 2000)
        self.assertEqual(service.MAX_TOTAL_EVIDENCE_CHARS, 8000)
