import hashlib
import json
from itertools import pairwise

from app.retrieval.chunking import MAX_INPUT_TOKENS, chunk_document
from app.retrieval.config import DEFAULT_SPEC, retrieval_spec_id
from retrieval.experiments.contextual_chunking import contextual_chunk_document
from retrieval.experiments.contextual_config import CONTEXTUAL_SPEC
from tests.retrieval.helpers import RetrievalTestCase, WordTokenizer, make_document


class ChunkingTests(RetrievalTestCase):
    def test_embedding_context_is_added_without_changing_source_spans_or_default_spec(
        self,
    ):
        body = (
            "# 경비 처리\n\n"
            "개인 결제는 다음 달 15일에 지급한다.\n\n"
            "## 증빙 제출\n\n"
            "영수증은 포털에 등록한다."
        )
        document = make_document(body=body)
        tokenizer = WordTokenizer()

        default_chunks = chunk_document(document, tokenizer, spec=DEFAULT_SPEC)
        contextual_chunks = contextual_chunk_document(document, tokenizer)

        target_default = next(
            chunk for chunk in default_chunks if "영수증" in chunk.text
        )
        target_contextual = next(
            chunk for chunk in contextual_chunks if "영수증" in chunk.text
        )
        self.assertEqual(target_contextual.spans, target_default.spans)
        self.assertNotIn("다음 달 15일", target_default.embedding_text)
        self.assertIn("다음 달 15일", target_contextual.embedding_text)
        self.assertLessEqual(
            len(tokenizer.encode(target_contextual.embedding_text)), MAX_INPUT_TOKENS
        )
        self.assertNotEqual(
            target_contextual.input_key,
            target_default.input_key,
        )
        self.assertNotEqual(
            retrieval_spec_id(CONTEXTUAL_SPEC), retrieval_spec_id(DEFAULT_SPEC)
        )

    def test_context_is_removed_before_body_or_title_when_input_nears_512(self):
        body = (
            "# 긴 제목 "
            + "제목" * 100
            + "\n\n"
            + " ".join(f"정책{index}" for index in range(350))
        )
        document = make_document(title="제목 " * 100, body=body)
        tokenizer = WordTokenizer()

        chunks = contextual_chunk_document(document, tokenizer)

        self.assertTrue(chunks)
        self.assertTrue(
            all(
                len(tokenizer.encode(chunk.embedding_text)) <= MAX_INPUT_TOKENS
                for chunk in chunks
            )
        )

    def test_short_context_before_is_redistributed_to_the_following_source(self):
        body = (
            "## 이전 절\n\n짧은 앞 문맥\n\n"
            "## 대상 절\n\n핵심 조건이다.\n\n"
            "## 다음 절\n\n" + " ".join(f"뒤문맥{index}" for index in range(80))
        )
        document = make_document(body=body)

        chunks = contextual_chunk_document(document, WordTokenizer())

        target = next(chunk for chunk in chunks if "핵심 조건" in chunk.text)
        self.assertIn("뒤문맥50", target.embedding_text)

    def test_context_uses_thirty_tokens_on_each_side_when_available(self):
        previous = " ".join(f"앞항목{index}" for index in range(40))
        following = " ".join(f"뒤항목{index}" for index in range(40))
        body = (
            f"## 이전 절\n\n{previous}\n\n"
            f"## 대상 절\n\n핵심 조건이다.\n\n"
            f"## 다음 절\n\n{following}"
        )
        tokenizer = WordTokenizer()
        chunks = contextual_chunk_document(make_document(body=body), tokenizer)
        target = next(chunk for chunk in chunks if "핵심 조건" in chunk.text)
        before = target.embedding_header.split("[인접 이전 문맥]\n", 1)[1].split(
            "\n[인접 다음 문맥]", 1
        )[0]
        after = target.embedding_header.split("[인접 다음 문맥]\n", 1)[1]

        self.assertEqual(len(tokenizer.encode(before)), 30)
        self.assertEqual(len(tokenizer.encode(after)), 30)

    def test_context_budget_shrinks_before_the_full_source_chunk(self):
        source_body = " ".join(f"본문항목{index}" for index in range(360))
        body = (
            "## 이전 절\n\n"
            + " ".join(f"앞문맥{index}" for index in range(40))
            + "\n\n## 대상 절\n\n"
            + source_body
            + "\n\n## 다음 절\n\n"
            + " ".join(f"뒤문맥{index}" for index in range(40))
        )
        tokenizer = WordTokenizer()
        document = make_document(title="긴제목 " * 200, body=body)

        chunks = contextual_chunk_document(document, tokenizer)

        target = next(chunk for chunk in chunks if "본문항목0" in chunk.text)
        before = target.embedding_header.split("[인접 이전 문맥]\n", 1)[1].split(
            "\n[인접 다음 문맥]", 1
        )[0]
        after = target.embedding_header.split("[인접 다음 문맥]\n", 1)[1]
        self.assertEqual(len(tokenizer.encode(target.text)), 360)
        self.assertLess(
            len(tokenizer.encode(before)) + len(tokenizer.encode(after)), 60
        )
        self.assertLessEqual(
            len(tokenizer.encode(target.embedding_text)), MAX_INPUT_TOKENS
        )

    def test_default_and_contextual_outputs_match_pre_move_fingerprints(self):
        fixtures = {
            "heading_boundary": (
                make_document(
                    document_id="doc-boundary",
                    revision_id="rev-1",
                    title="경비 안내",
                    body=(
                        "# 경비 처리\n\n개인 결제는 다음 달 15일에 지급한다.\n\n"
                        "## 증빙 제출\n\n영수증은 포털에 등록한다."
                    ),
                ),
                {
                    "default": "5f3aea0f0b1e3fd027de7bce7f0663054cd09fc15738820b6631cef92b121b5d",
                    "contextual": "4eb0cadf85458bc0df8dd3b1a24110d0d071d1ec66ff228e33e3758699774fd4",
                },
            ),
            "context_redistribution": (
                make_document(
                    document_id="doc-redistribution",
                    revision_id="rev-2",
                    title="안내",
                    body=(
                        "## 이전 절\n\n짧은 앞 문맥\n\n## 대상 절\n\n핵심 조건이다.\n\n"
                        "## 다음 절\n\n" + " ".join(f"뒤문맥{i}" for i in range(80))
                    ),
                ),
                {
                    "default": "a02b6fe531ee709192d1b0e5e1cd32047b439a5933bb3d4d73e30367131c17a0",
                    "contextual": "a3e05219dffc8b846120a361fd9635239f49e1506ddede59f169b5915804f076",
                },
            ),
            "context_shrink": (
                make_document(
                    document_id="doc-shrink",
                    revision_id="rev-3",
                    title="긴제목 " * 200,
                    body=(
                        "## 이전 절\n\n"
                        + " ".join(f"앞문맥{i}" for i in range(40))
                        + "\n\n## 대상 절\n\n"
                        + " ".join(f"본문항목{i}" for i in range(360))
                        + "\n\n## 다음 절\n\n"
                        + " ".join(f"뒤문맥{i}" for i in range(40))
                    ),
                ),
                {
                    "default": "121358195a8316c0ac72667f095e9017ee1b798832f2b90479f85d63a6060a27",
                    "contextual": "7a9bf63eeb0e9b4e4c1c8914997593ec0f9a9c5fbcc644c15b7309c3d7d843d3",
                },
            ),
            "table": (
                make_document(
                    document_id="doc-table",
                    revision_id="rev-4",
                    title="휴가 신청",
                    body=(
                        "# 휴가 안내\n\n절차를 포털에서 진행한다.\n\n"
                        "## 신청 표\n\n| 구분 | 기한 |\n|---|---|\n"
                        "| 예정 | 3일 전 |\n| 긴급 | 가능한 시점 |"
                    ),
                ),
                {
                    "default": "2b23600833502d469fe0058cbd8a88e32cdfeebdebb374f55508ccb7cdee26b1",
                    "contextual": "fa9a06f90ef3044d93cbc75bb6e3e0abc173a9395e7f305afd764d5d1a1a7778",
                },
            ),
        }
        expected_spec_ids = {
            "default": "d08dee58d2ef8e7ad5c41141fece619e49de0a6b701aec0d284d5eeef58f1529",
            "contextual": "d23cb5d91dae4f4cb96b3a3f40b9bdf8418060845c4f51e0a859db7cee39ff5e",
        }
        tokenizer = WordTokenizer()
        for document, expected_hashes in fixtures.values():
            for mode, spec, chunker in (
                ("default", DEFAULT_SPEC, chunk_document),
                ("contextual", CONTEXTUAL_SPEC, contextual_chunk_document),
            ):
                chunks = chunker(document, tokenizer, spec=spec)
                serialized = [
                    {
                        "ordinal": chunk.ordinal,
                        "spans": [
                            [span.start, span.end, span.kind] for span in chunk.spans
                        ],
                        "heading": chunk.heading,
                        "embedding_header": chunk.embedding_header,
                        "text": chunk.text,
                        "embedding_text": chunk.embedding_text,
                        "input_key": chunk.input_key,
                        "chunk_id": chunk.chunk_id,
                    }
                    for chunk in chunks
                ]
                payload = {
                    "spec_id": retrieval_spec_id(spec),
                    "spec": spec.to_dict(),
                    "chunks": serialized,
                }
                fingerprint = hashlib.sha256(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                self.assertEqual(retrieval_spec_id(spec), expected_spec_ids[mode])
                self.assertEqual(fingerprint, expected_hashes[mode])

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
