"""Focused contracts for the KURE server retrieval profile."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import torch
import transformers

from app.retrieval.baseline import prepare_baseline, restore_baseline, validate_baseline
from app.retrieval.chunking import chunk_document
from app.retrieval.config import (
    DEFAULT_SPEC,
    KURE_SPEC,
    MODEL_ID,
    MODEL_REVISION,
    SERVER_SPEC,
    retrieval_spec_id,
)
from app.retrieval.embedding import (
    MODEL_MANIFEST_FILENAME,
    KureEmbedder,
    model_manifest,
)
from app.retrieval.repository import IndexRepository
from app.retrieval.search import KURE_MINIMUM_SIMILARITY_SCORE, search_config_id
from app.retrieval.service import RetrievalService, _ranked_hits
from app.retrieval.types import (
    Chunk,
    RetrievalInputTooLong,
    RetrievalUnavailable,
    SourceSpan,
)
from tests.retrieval.helpers import (
    RetrievalTestCase,
    WordTokenizer,
    make_document,
    make_snapshot,
)


def _write_source(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class _KureTokenizer:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        texts,
        *,
        add_special_tokens=False,
        padding=False,
        truncation=False,
        return_tensors=None,
        **_,
    ):
        self.calls.append(texts)
        if isinstance(texts, str):
            ids = list(range(1, len(texts.split()) + 1))
            if add_special_tokens:
                ids = [101, *ids, 102]
            return {"input_ids": ids}
        rows = []
        for text in texts:
            ids = list(range(1, len(text.split()) + 1))
            if add_special_tokens:
                ids = [101, *ids, 102]
            rows.append(ids)
        width = max(map(len, rows))
        padded = [row + [0] * (width - len(row)) for row in rows]
        masks = [[1] * len(row) + [0] * (width - len(row)) for row in rows]
        return {
            "input_ids": torch.tensor(padded, dtype=torch.long),
            "attention_mask": torch.tensor(masks, dtype=torch.long),
        }


class _KureModel:
    def __init__(self):
        self.config = SimpleNamespace(hidden_size=1024)
        self.is_eval = False
        self.is_float = False
        self.device = None

    def float(self):
        self.is_float = True
        return self

    def to(self, device):
        self.device = device
        return self

    def eval(self):
        self.is_eval = True
        return self

    def __call__(self, input_ids, attention_mask):
        assert torch.is_inference_mode_enabled()
        hidden = torch.zeros((*input_ids.shape, 1024), dtype=torch.float32)
        # CLS is deliberately different from all later token states.
        hidden[:, 0, 0] = 3.0
        if input_ids.shape[1] > 1:
            hidden[:, 1:, 1] = 7.0
        return SimpleNamespace(last_hidden_state=hidden)


def _model_directory(path, spec, *, pooling="cls-token"):
    path.mkdir(parents=True)
    (path / MODEL_MANIFEST_FILENAME).write_text(
        json.dumps(model_manifest(spec)), encoding="utf-8"
    )
    (path / "1_Pooling").mkdir()
    (path / "1_Pooling/config.json").write_text(
        json.dumps(
            {
                "pooling_mode_cls_token": pooling == "cls-token",
                "pooling_mode_mean_tokens": pooling == "attention-mask-mean",
            }
        ),
        encoding="utf-8",
    )
    return path


class KureRuntimeTests(RetrievalTestCase):
    def test_kure_contract_keeps_legacy_tiny_spec_id_and_sets_server_profile(self):
        self.assertEqual(
            retrieval_spec_id(DEFAULT_SPEC),
            "d08dee58d2ef8e7ad5c41141fece619e49de0a6b701aec0d284d5eeef58f1529",
        )
        self.assertEqual(KURE_SPEC.model_id, "nlpai-lab/KURE-v1")
        self.assertEqual(
            KURE_SPEC.model_revision,
            "8b418a58414668e75532ed045c22d9ca018ae2b2",
        )
        self.assertEqual(KURE_SPEC.dimension, 1024)
        self.assertEqual(KURE_SPEC.pooling, "cls")
        self.assertEqual(KURE_SPEC.query_prefix, "")
        self.assertEqual(KURE_SPEC.passage_prefix, "")
        self.assertEqual(KURE_SPEC.max_query_tokens, 512)
        self.assertEqual(KURE_SPEC.max_document_tokens, 8192)
        self.assertEqual(SERVER_SPEC, KURE_SPEC)
        self.assertNotEqual(
            retrieval_spec_id(DEFAULT_SPEC), retrieval_spec_id(KURE_SPEC)
        )

    def test_kure_spec_identity_includes_the_frozen_splitter(self):
        changed_splitter = replace(
            KURE_SPEC,
            splitter_model_revision="different-pinned-splitter-revision",
        )

        self.assertNotEqual(
            retrieval_spec_id(KURE_SPEC), retrieval_spec_id(changed_splitter)
        )
        self.assertEqual(
            KURE_SPEC.to_dict()["splitter"],
            {
                "model_id": MODEL_ID,
                "revision": MODEL_REVISION,
                "directory": "splitter",
            },
        )
        self.assertEqual(
            model_manifest(KURE_SPEC)["splitter"],
            KURE_SPEC.to_dict()["splitter"],
        )

    def test_kure_embedder_uses_local_cls_fp32_without_prefix_and_validates_lengths(
        self,
    ):
        model_path = _model_directory(self.tmp_path / "kure", KURE_SPEC)
        splitter_path = self.tmp_path / "splitter"
        splitter_path.mkdir()
        for filename in (
            "config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ):
            (splitter_path / filename).write_text("{}", encoding="utf-8")
        query_tokenizer = _KureTokenizer()
        splitter_tokenizer = WordTokenizer()
        model = _KureModel()
        tokenizer_loads = []
        model_loads = []

        def load_tokenizer(path, **kwargs):
            tokenizer_loads.append((path, kwargs))
            return (
                splitter_tokenizer
                if str(path) == str(splitter_path)
                else query_tokenizer
            )

        def load_model(path, **kwargs):
            model_loads.append((path, kwargs))
            return model

        with (
            patch.object(transformers.AutoTokenizer, "from_pretrained", load_tokenizer),
            patch.object(transformers.AutoModel, "from_pretrained", load_model),
        ):
            embedder = KureEmbedder(model_path, splitter_path=splitter_path)
            query = embedder.encode_queries(["휴가 신청 방법"])
            passage = embedder.encode_documents(["휴가 신청 방법"])
            self.assertIs(embedder.tokenizer, query_tokenizer)
            self.assertIs(embedder.splitter_tokenizer, splitter_tokenizer)
            with self.assertRaises(RetrievalInputTooLong):
                embedder.encode_queries([" ".join("x" for _ in range(512))])
            with self.assertRaises(RetrievalInputTooLong):
                embedder.encode_documents([" ".join("x" for _ in range(8192))])

        self.assertEqual(query.shape, (1, 1024))
        self.assertTrue(np.allclose(query, passage))
        self.assertAlmostEqual(float(np.linalg.norm(query[0])), 1.0, places=5)
        self.assertTrue(model.is_float)
        self.assertEqual(model.device, "cpu")
        self.assertTrue(model.is_eval)
        self.assertEqual(len(model_loads), 1)
        self.assertTrue(
            all(kwargs["local_files_only"] for _, kwargs in tokenizer_loads)
        )
        self.assertTrue(all(kwargs["local_files_only"] for _, kwargs in model_loads))
        self.assertTrue(
            any(call == ["휴가 신청 방법"] for call in query_tokenizer.calls)
        )
        self.assertFalse(any("query: " in str(call) for call in query_tokenizer.calls))
        self.assertFalse(
            any("passage: " in str(call) for call in query_tokenizer.calls)
        )

    def test_malformed_kure_pooling_config_fails_as_retrieval_unavailable(self):
        model_path = _model_directory(self.tmp_path / "bad-pooling", KURE_SPEC)
        (model_path / "1_Pooling/config.json").write_text("[]", encoding="utf-8")

        with self.assertRaises(RetrievalUnavailable):
            KureEmbedder(model_path).warmup()

    def test_kure_chunk_geometry_uses_frozen_splitter_and_omits_e5_prefix(self):
        document = make_document(
            body="# 제목\n\n" + " ".join(f"항목{i}" for i in range(500))
        )

        tiny_chunks = chunk_document(document, WordTokenizer(), spec=DEFAULT_SPEC)
        kure_chunks = chunk_document(document, WordTokenizer(), spec=KURE_SPEC)

        self.assertEqual(
            [chunk.spans for chunk in kure_chunks],
            [chunk.spans for chunk in tiny_chunks],
        )
        self.assertTrue(
            all(
                not chunk.embedding_text.startswith("passage: ")
                for chunk in kure_chunks
            )
        )
        self.assertTrue(
            all(chunk.embedding_text.startswith("passage: ") for chunk in tiny_chunks)
        )
        self.assertNotEqual(kure_chunks[0].chunk_id, tiny_chunks[0].chunk_id)

    def test_kure_service_applies_inclusive_question_gate_then_top_twenty(self):
        class ReadyRepository:
            spec = KURE_SPEC

            def __init__(self, current):
                self.current = current

            @staticmethod
            def status(_snapshot):
                return {"ready": True}

            def current_chunks(self, _snapshot):
                return self.current

        class Embedder:
            tokenizer = WordTokenizer()
            spec = KURE_SPEC

            @staticmethod
            def encode_queries(_questions):
                query = np.zeros(1024, dtype=np.float32)
                query[0] = 1.0
                return query[None, :]

        documents = [
            make_document(
                document_id=f"doc-{index}",
                knowledge_id=f"knowledge-{index}",
                revision_id=f"revision-{index}",
                body=f"source-{index}",
            )
            for index in range(22)
        ]
        snapshot = make_snapshot(*documents)
        current = []
        for index, document in enumerate(documents):
            chunk = Chunk(
                document_id=document.document_id,
                revision_id=document.revision_id,
                ordinal=0,
                spans=(SourceSpan(0, len(document.body)),),
                heading="",
                embedding_header=document.title,
                text=document.body,
                embedding_text=document.body,
                input_key=f"key-{index}",
                chunk_id=f"chunk-{index:02}",
            )
            score = KURE_MINIMUM_SIMILARITY_SCORE if index == 0 else 0.2 + (index / 100)
            vector = np.zeros(1024, dtype=np.float32)
            vector[0] = score
            vector[1] = np.sqrt(1.0 - score**2)
            current.append((chunk, vector))

        service = RetrievalService(ReadyRepository(current), Embedder())
        result = service.retrieve("질문", snapshot)

        self.assertEqual(result.search_config_id, search_config_id(KURE_SPEC))
        self.assertEqual(result.candidate_count, 20)
        self.assertEqual(len(result.candidate_chunk_ids), 20)
        self.assertEqual(result.candidate_chunk_ids[0], "chunk-00")
        self.assertTrue(
            any(
                float(vector[0]) < KURE_MINIMUM_SIMILARITY_SCORE
                for _, vector in current[1:]
            )
        )
        self.assertEqual(len(result.evidence), 20)

        below_current = list(current)
        chunk, _ = below_current[0]
        below = np.zeros(1024, dtype=np.float32)
        below[0] = KURE_MINIMUM_SIMILARITY_SCORE - 1e-4
        below[1] = np.sqrt(1.0 - below[0] ** 2)
        below_current[0] = (chunk, below)
        blocked = RetrievalService(ReadyRepository(below_current), Embedder()).retrieve(
            "질문", snapshot
        )
        self.assertEqual(blocked.candidate_count, 0)
        self.assertEqual(blocked.evidence, ())

    def test_kure_top_twenty_cutoff_breaks_exact_score_ties_by_chunk_id(self):
        document = make_document(body="원문")
        current = []
        scores = []
        for index in range(21):
            chunk_id = f"chunk-{20 - index:02}"
            chunk = Chunk(
                document_id=document.document_id,
                revision_id=document.revision_id,
                ordinal=index,
                spans=(SourceSpan(0, len(document.body)),),
                heading="",
                embedding_header=document.title,
                text=document.body,
                embedding_text=document.body,
                input_key=f"key-{index}",
                chunk_id=chunk_id,
            )
            current.append((chunk, np.ones(KURE_SPEC.dimension, dtype=np.float32)))
            scores.append(0.8 if index < 19 else 0.5)

        hits = _ranked_hits(current, np.asarray(scores), spec=KURE_SPEC)

        self.assertEqual(len(hits), 20)
        self.assertEqual(hits[-1][0].chunk_id, "chunk-00")
        self.assertNotIn("chunk-01", [chunk.chunk_id for chunk, _ in hits])

    def test_kure_repository_uses_dimension_specific_spec_path_and_vectors(self):
        repository = IndexRepository(self.tmp_path / "indices", spec=KURE_SPEC)
        tiny = IndexRepository(self.tmp_path / "indices", spec=DEFAULT_SPEC)
        self.assertNotEqual(repository.database_path, tiny.database_path)

        document = make_document(body="기준 문장입니다.")
        chunks = chunk_document(document, WordTokenizer(), spec=KURE_SPEC)
        vectors = np.zeros((len(chunks), KURE_SPEC.dimension), dtype=np.float32)
        vectors[:, 0] = 1.0
        repository.store_documents(((document, chunks, vectors),))

        self.assertTrue(repository.status(make_snapshot(document))["ready"])
        self.assertEqual(
            len(repository.current_chunks(make_snapshot(document))), len(chunks)
        )

    def test_kure_baseline_prepare_validate_and_restore_are_spec_scoped(self):
        class Embedder:
            tokenizer = WordTokenizer()
            splitter_tokenizer = WordTokenizer()
            spec = KURE_SPEC

            @staticmethod
            def encode_documents(texts):
                vectors = np.zeros((len(texts), KURE_SPEC.dimension), dtype=np.float32)
                vectors[:, 0] = 1.0
                return vectors

        source = self.tmp_path / "source.jsonl"
        _write_source(
            source,
            [
                {
                    "document_id": "ieum-001",
                    "title": "휴가",
                    "document": "신청은 포털에서 한다.",
                }
            ],
        )
        bundle = prepare_baseline(
            source,
            self.tmp_path / "baselines",
            Embedder(),
            spec=KURE_SPEC,
        )
        validation = validate_baseline(bundle, source, spec=KURE_SPEC)
        self.assertEqual(validation["spec_id"], retrieval_spec_id(KURE_SPEC))

        document = make_document(
            knowledge_id="ieum-001",
            revision_id="reset-1",
            title="휴가",
            body="신청은 포털에서 한다.",
        )
        repository = IndexRepository(self.tmp_path / "runtime", spec=KURE_SPEC)
        restored = restore_baseline(
            repository,
            bundle,
            source,
            make_snapshot(document),
            spec=KURE_SPEC,
        )
        self.assertTrue(restored["ready"])
        self.assertEqual(len(repository.current_chunks(make_snapshot(document))), 1)

    def test_tiny_bundle_is_rejected_before_kure_repository_is_mutated(self):
        class TinyBundleEmbedder:
            tokenizer = WordTokenizer()
            spec = DEFAULT_SPEC

            @staticmethod
            def encode_documents(texts):
                vectors = np.zeros(
                    (len(texts), DEFAULT_SPEC.dimension), dtype=np.float32
                )
                vectors[:, 0] = 1.0
                return vectors

        source = self.tmp_path / "source.jsonl"
        _write_source(
            source,
            [
                {
                    "document_id": "ieum-001",
                    "title": "휴가",
                    "document": "신청은 포털에서 한다.",
                }
            ],
        )
        tiny_bundle = prepare_baseline(
            source,
            self.tmp_path / "tiny-baselines",
            TinyBundleEmbedder(),
        )
        source_before = source.read_bytes()
        document = make_document(
            knowledge_id="ieum-001",
            revision_id="reset-1",
            title="휴가",
            body="신청은 포털에서 한다.",
        )
        repository = IndexRepository(self.tmp_path / "kure-runtime", spec=KURE_SPEC)

        with self.assertRaises(RetrievalUnavailable):
            restore_baseline(
                repository,
                tiny_bundle,
                source,
                make_snapshot(document),
            )

        self.assertEqual(source.read_bytes(), source_before)
        self.assertFalse(repository.database_path.exists())

    def test_baseline_prepare_rejects_embedder_spec_mismatch_before_writing(self):
        class WrongEmbedder:
            tokenizer = WordTokenizer()
            splitter_tokenizer = tokenizer
            spec = DEFAULT_SPEC

            @staticmethod
            def encode_documents(_texts):
                raise AssertionError("the wrong model must not be used")

        source = self.tmp_path / "source.jsonl"
        _write_source(
            source,
            [{"document_id": "ieum-001", "title": "휴가", "document": "신청"}],
        )
        output = self.tmp_path / "baselines"

        with self.assertRaises(RetrievalUnavailable):
            prepare_baseline(source, output, WrongEmbedder(), spec=KURE_SPEC)

        self.assertFalse(output.exists())
