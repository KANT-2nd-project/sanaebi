import concurrent.futures
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.retrieval.types import Chunk, SourceSpan
from retrieval.experiments.calibration_search import select_evidence
from retrieval.experiments.optimization import (
    BGE_REVISION,
    DEFAULT_VARIANT_IDS,
    LocalBgeReranker,
    expand_adjacent_hits,
    load_requested_reranker,
    make_relevance_packet,
    parse_variant_ids,
    run_experiment,
    score_evidence,
    select_variant_evidence,
    validate_frozen_qrels,
    validate_reranker_manifest,
    variants_require_reranker,
)
from retrieval.experiments.optimization_benchmark import (
    bounded_request_batches,
    make_timing_row,
    select_variant_evidence_serialized,
    summarize_timing_rows,
    validate_benchmark_request,
)
from tests.retrieval.helpers import WordTokenizer, make_document, make_snapshot


def chunk(
    chunk_id,
    ordinal,
    *,
    document_id="db-doc",
    revision_id="revision-1",
    heading="Policy > Annual leave",
    text=None,
    start=None,
):
    text = text or f"passage {chunk_id}"
    start = ordinal * 30 if start is None else start
    return Chunk(
        document_id=document_id,
        revision_id=revision_id,
        ordinal=ordinal,
        spans=(SourceSpan(start, start + len(text)),),
        heading=heading,
        embedding_header="",
        text=text,
        embedding_text=text,
        input_key=f"input-{chunk_id}",
        chunk_id=chunk_id,
    )


class AdjacentExpansionTests(unittest.TestCase):
    def test_requires_same_revision_and_nonempty_common_upper_section(self):
        anchor = chunk("anchor", 2, heading="Policy > Leave")
        allowed = chunk("allowed", 1, heading="Policy > Attendance")
        unrelated = chunk("unrelated", 3, heading="Payroll > Salary")
        other_revision = chunk("other-rev", 3, revision_id="rev-2")
        other_document = chunk("other-doc", 3, document_id="db-other")

        expanded = expand_adjacent_hits(
            [(anchor, 0.9)],
            [anchor, allowed, unrelated, other_revision, other_document],
        )

        self.assertEqual([item[0].chunk_id for item in expanded], ["anchor", "allowed"])
        self.assertEqual(expanded[1][1], 0.9)
        self.assertEqual(expanded[1][2:], ("expanded", "anchor"))
        self.assertEqual(
            [
                item[0].chunk_id
                for item in expand_adjacent_hits(
                    [(anchor, 0.9)],
                    [anchor, chunk("no-parent", 3, heading="Other")],
                )
            ],
            ["anchor"],
        )

    def test_adds_only_immediate_neighbors_and_deduplicates_by_best_anchor(self):
        left = chunk("left", 0)
        anchor_a = chunk("anchor-a", 1)
        anchor_b = chunk("anchor-b", 3)
        right = chunk("right", 4)
        skipped = chunk("skipped", 2)
        expanded = expand_adjacent_hits(
            [(anchor_a, 0.8), (anchor_b, 0.8)],
            [right, skipped, anchor_b, left, anchor_a],
        )

        self.assertEqual(
            [item[0].chunk_id for item in expanded],
            ["anchor-a", "anchor-b", "left", "skipped", "right"],
        )
        self.assertEqual(
            [item[3] for item in expanded[2:]],
            ["anchor-a", "anchor-a", "anchor-b"],
        )


class VariantSelectionTests(unittest.TestCase):
    def test_c_unlimited_matches_existing_threshold_and_unlimited_selection(self):
        document = make_document(document_id="db-doc", body="alpha beta gamma")
        snapshot = make_snapshot(document)
        chunks = [
            chunk("a", 0, text="alpha", start=0),
            chunk("b", 1, text="beta", start=6),
            chunk("c", 2, text="gamma", start=11),
        ]
        ranked = [(chunks[1], 0.8), (chunks[0], 0.6), (chunks[2], 0.34)]
        tokenizer = WordTokenizer()
        expected = select_evidence(
            [(item, score) for item, score in ranked if score >= 0.35],
            snapshot,
            float("inf"),
            tokenizer,
            None,
            total_chars=None,
            per_evidence_chars=None,
        )

        actual = select_variant_evidence("C_unlimited", ranked, snapshot, tokenizer)

        self.assertEqual(actual, expected)

    def test_rerank_selection_keeps_cosine_and_rerank_scores_separate(self):
        first = chunk("first", 0, document_id="db-1", text="first evidence", start=0)
        second = chunk("second", 0, document_id="db-2", text="second evidence", start=0)
        documents = [
            make_document(document_id="db-1", knowledge_id="k1", body="first evidence"),
            make_document(
                document_id="db-2", knowledge_id="k2", body="second evidence"
            ),
        ]
        snapshot = make_snapshot(*documents)
        cosine = {"first": 0.91, "second": 0.72}
        rerank = {"first": -2.0, "second": 4.0}
        selected = select_variant_evidence(
            "bge_rerank_top5",
            [(first, cosine["first"]), (second, cosine["second"])],
            snapshot,
            WordTokenizer(),
            reranked=[(second, rerank["second"]), (first, rerank["first"])],
        )

        records = [score_evidence(item, cosine, rerank) for item in selected]
        self.assertEqual(
            [item["chunk_ids"] for item in records], [("second",), ("first",)]
        )
        self.assertEqual(records[0]["cosine_score"], 0.72)
        self.assertEqual(records[0]["rerank_score"], 4.0)
        self.assertNotIn("score", records[0])

    def test_new_variants_have_no_character_caps_and_fail_closed_below_threshold(self):
        body = "x" * 25_000
        doc = make_document(document_id="db-doc", knowledge_id="k1", body=body)
        long_chunk = chunk("long", 0, text=body, start=0, document_id=doc.document_id)
        snapshot = make_snapshot(doc)
        selected = select_variant_evidence(
            "adjacent_top5",
            [(long_chunk, 0.4)],
            snapshot,
            WordTokenizer(),
            current_chunks=[long_chunk],
        )
        self.assertEqual(selected[0].text, body)
        self.assertEqual(selected[0].spans, (SourceSpan(0, len(body)),))

        empty = select_variant_evidence(
            "adjacent_top5",
            [(long_chunk, 0.3499)],
            snapshot,
            WordTokenizer(),
            current_chunks=[long_chunk],
        )
        self.assertEqual(empty, [])


class FreezeAndBlindPacketTests(unittest.TestCase):
    def test_only_independently_reviewed_frozen_qrels_are_accepted(self):
        data = {
            "status": "frozen_independent_ai_reviewed",
            "cases": [
                {
                    "case_id": "Q1",
                    "question": "Where?",
                    "answerability": "partial",
                    "required_claims": [],
                    "review_status": "independent_ai_reviewed",
                }
            ],
        }
        validate_frozen_qrels(data)
        data["status"] = "ai_draft"
        with self.assertRaisesRegex(ValueError, "frozen"):
            validate_frozen_qrels(data)

    def test_runner_requires_explicit_frozen_execution_flag(self):
        with self.assertRaisesRegex(ValueError, "execute-frozen"):
            run_experiment(SimpleNamespace(execute_frozen=False))

    def test_variant_subset_defaults_to_development_set_and_loads_bge_only_if_selected(
        self,
    ):
        self.assertEqual(parse_variant_ids(None), DEFAULT_VARIANT_IDS)
        subset = parse_variant_ids(["C_unlimited", "adjacent_top8"])
        self.assertEqual(subset, ("C_unlimited", "adjacent_top8"))
        self.assertFalse(variants_require_reranker(subset))
        self.assertTrue(variants_require_reranker(["C_unlimited", "bge_rerank_top8"]))
        with patch("retrieval.experiments.optimization.LocalBgeReranker") as model:
            self.assertIsNone(load_requested_reranker(subset, None, None))
        model.assert_not_called()

    def test_variant_subset_rejects_unknown_and_duplicate_names(self):
        with self.assertRaisesRegex(ValueError, "unknown variant"):
            parse_variant_ids(["finalcandidate"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_variant_ids(["C_unlimited", "C_unlimited"])

    def test_benchmark_request_requires_authorization_and_five_full_rounds(self):
        args = SimpleNamespace(
            execute_frozen_benchmark=False,
            rounds=1,
            concurrency=(1, 2),
            variant="C_unlimited",
        )
        with self.assertRaisesRegex(ValueError, "execute-frozen-benchmark"):
            validate_benchmark_request(args, case_count=48)
        args.execute_frozen_benchmark = True
        self.assertEqual(validate_benchmark_request(args, case_count=48), "C_unlimited")
        args.rounds = 0
        with self.assertRaisesRegex(ValueError, "one"):
            validate_benchmark_request(args, case_count=48)
        args.rounds = 1
        with self.assertRaisesRegex(ValueError, "48"):
            validate_benchmark_request(args, case_count=47)

    def test_benchmark_response_latency_includes_queue_wait(self):
        row = make_timing_row(
            submitted_at=1.0,
            started_at=1.25,
            finished_at=2.0,
            stages_ms={"query_embedding_ms": 50.0},
        )
        self.assertEqual(row["queue_wait_ms"], 250.0)
        self.assertEqual(row["service_ms"], 750.0)
        self.assertEqual(row["response_ms"], 1000.0)
        summary = summarize_timing_rows([row, row])
        self.assertEqual(summary["response_ms"]["p95"], 1000.0)
        self.assertEqual(summary["request_count"], 2)

    def test_benchmark_submission_batches_bound_executor_backlog(self):
        batches = list(bounded_request_batches(list(range(5)), concurrency=2))
        self.assertEqual(batches, [[0, 1], [2, 3], [4]])

    def test_benchmark_serializes_global_budget_patch_during_selection(self):
        first_entered = threading.Event()
        allow_first_to_finish = threading.Event()
        second_entered = threading.Event()
        call_counter_lock = threading.Lock()
        call_counter = 0

        def fake_selection(*_args, **_kwargs):
            nonlocal call_counter
            with call_counter_lock:
                call_counter += 1
                call_number = call_counter
            if call_number == 1:
                first_entered.set()
                if not allow_first_to_finish.wait(timeout=2):
                    raise AssertionError("test did not release first selection")
            else:
                second_entered.set()
            return call_number

        with (
            patch(
                "retrieval.experiments.optimization_benchmark.select_variant_evidence",
                side_effect=fake_selection,
            ),
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(select_variant_evidence_serialized, "C_unlimited")
            self.assertTrue(first_entered.wait(timeout=1))
            second = executor.submit(select_variant_evidence_serialized, "C_unlimited")
            self.assertFalse(second_entered.wait(timeout=0.05))
            allow_first_to_finish.set()
            self.assertEqual(first.result(timeout=1), 1)
            self.assertEqual(second.result(timeout=1), 2)

        self.assertTrue(second_entered.is_set())

    def test_packet_contains_qrel_context_but_no_variant_score_or_rank(self):
        passage = chunk("chunk-1", 0, text="proof", start=0)
        doc = make_document(body="proof")
        case = {
            "case_id": "Q1",
            "question": "Where?",
            "answerability": "answerable",
            "required_claims": [{"claim_id": "C1", "claim": "It is here."}],
        }
        packet = make_relevance_packet(
            [case], {"chunk-1": passage}, {"db-doc": doc}, {"Q1": {"chunk-1"}}
        )

        self.assertEqual(
            packet["judgment_context"],
            "qrel_conditioned_independent_relevance_review",
        )
        self.assertEqual(packet["cases"][0]["required_claims"], case["required_claims"])
        item = packet["cases"][0]["passages"][0]
        self.assertEqual(item["chunk_id"], "chunk-1")
        self.assertNotIn("variant", item)
        self.assertNotIn("score", item)
        self.assertNotIn("rank", item)

    def test_runner_is_pinned_to_requested_bge_revision(self):
        self.assertEqual(BGE_REVISION, "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")

    def test_manifest_requires_model_files_but_allows_absent_reference_images(self):
        required = {
            "config.json",
            "model.safetensors",
            "sentencepiece.bpe.model",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model"
            model.mkdir()
            for name in required:
                (model / name).write_text("local", encoding="utf-8")
            manifest = root / "source.json"
            manifest.write_text(
                json.dumps(
                    {
                        "model_id": "BAAI/bge-reranker-v2-m3",
                        "revision": BGE_REVISION,
                        "license": "apache-2.0",
                        "files": sorted(required) + ["assets/reference.png"],
                    }
                ),
                encoding="utf-8",
            )

            validated = validate_reranker_manifest(manifest, model)

        self.assertEqual(validated["revision"], BGE_REVISION)

    def test_pair_scoring_never_requests_truncation_and_rejects_over_limit(self):
        class FakeTensor:
            def __init__(self, values):
                self.values = values

            def to(self, _device):
                return self

            def tolist(self):
                return self.values

            def sum(self, dim):
                self.assert_dim = dim
                return FakeTensor([sum(row) for row in self.values])

        class FakeLogits(FakeTensor):
            def float(self):
                return self

            def reshape(self, *_shape):
                return self

            def detach(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                import numpy as np

                return np.asarray(self.values)

        class FakeTokenizer:
            model_max_length = 4

            def __init__(self, token_count):
                self.token_count = token_count
                self.kwargs = None

            def __call__(self, _queries, _passages, **kwargs):
                self.kwargs = kwargs
                ids = [list(range(self.token_count))]
                mask = [[1] * self.token_count]
                return {
                    "input_ids": FakeTensor(ids),
                    "attention_mask": FakeTensor(mask),
                }

        class FakeTorch:
            @staticmethod
            def inference_mode():
                from contextlib import nullcontext

                return nullcontext()

        class FakeModel:
            calls = 0

            def __call__(self, **_inputs):
                self.calls += 1
                return SimpleNamespace(logits=FakeLogits([0.5]))

        reranker = LocalBgeReranker(Path("unused"), Path("unused"))
        reranker.tokenizer = FakeTokenizer(4)
        reranker.model = FakeModel()
        reranker.torch = FakeTorch()
        reranker.native_token_limit = 4
        result = reranker.score_pairs([("query", "passage")])
        self.assertFalse(reranker.tokenizer.kwargs["truncation"])
        self.assertEqual(result[0]["input_ids"], [0, 1, 2, 3])
        self.assertEqual(result[0]["attention_mask"], [1, 1, 1, 1])

        reranker.tokenizer = FakeTokenizer(5)
        reranker.model.calls = 0
        with self.assertRaisesRegex(ValueError, "native token limit"):
            reranker.score_pairs([("query", "too long")])
        self.assertEqual(reranker.model.calls, 0)
