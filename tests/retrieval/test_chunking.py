from itertools import pairwise

from app.retrieval.chunking import MAX_INPUT_TOKENS, chunk_document
from tests.retrieval.helpers import RetrievalTestCase, WordTokenizer, make_document


class ChunkingTests(RetrievalTestCase):
    def test_chunks_preserve_non_whitespace_source_spans_and_fit_model_input(self):
        body = (
            "# 휴가 안내\n\n"
            + " ".join(f"절차{index}" for index in range(900))
            + "\n\n## 신청 표\n\n"
            + "| 구분 | 기한 |\n|---|---|\n"
            + "| 예정 | 3일 전 |\n"
            + "| 긴급 | 가능한 시점 |"
        )
        document = make_document(title="휴가", body=body)
        tokenizer = WordTokenizer()

        chunks = chunk_document(document, tokenizer)

        self.assertGreater(len(chunks), 1)
        covered = set()
        for chunk in chunks:
            self.assertTrue(chunk.embedding_text.startswith("passage: 휴가"))
            self.assertLessEqual(
                len(tokenizer.encode(chunk.embedding_text)), MAX_INPUT_TOKENS
            )
            self.assertTrue(chunk.input_key)
            self.assertTrue(chunk.chunk_id)
            for span in chunk.spans:
                self.assertGreaterEqual(span.start, 0)
                self.assertLess(span.start, span.end)
                self.assertLessEqual(span.end, len(body))
                self.assertTrue(body[span.start : span.end])
                covered.update(range(span.start, span.end))

        self.assertTrue(
            all(
                index in covered
                for index, char in enumerate(body)
                if not char.isspace()
            )
        )

    def test_long_paragraph_uses_overlapping_windows_without_losing_text(self):
        body = " ".join(f"항목{index}" for index in range(700))
        document = make_document(body=body)

        chunks = chunk_document(document, WordTokenizer())

        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(
            any(
                left_span.end > right_span.start
                for left, right in pairwise(chunks)
                for left_span in left.spans
                for right_span in right.spans
            )
        )
        self.assertTrue(all(chunk.text.strip() for chunk in chunks))

    def test_long_table_repeats_its_header_in_each_row_group(self):
        rows = "\n".join(
            f"| 휴가 유형 {index} | 신청 기한 {index} |" for index in range(500)
        )
        body = f"| 구분 | 기한 |\n|---|---|\n{rows}"
        document = make_document(title="휴가 표", body=body)

        chunks = chunk_document(document, WordTokenizer())

        table_chunks = [
            chunk
            for chunk in chunks
            if any(span.kind == "table_header" for span in chunk.spans)
        ]
        self.assertGreater(len(table_chunks), 1)
        self.assertTrue(
            all(chunk.text.startswith("| 구분 | 기한 |") for chunk in table_chunks)
        )
