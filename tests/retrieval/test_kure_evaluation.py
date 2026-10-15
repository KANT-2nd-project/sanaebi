"""Focused offline tests for the frozen KURE evaluation runner."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.documents.context import DocumentContextProvider
from app.documents.repository import DocumentRepository
from app.retrieval.chunking import chunk_document
from app.retrieval.config import DEFAULT_SPEC, MODEL_REVISION, VECTOR_DIMENSION
from app.retrieval.repository import IndexRepository
from app.retrieval.types import Chunk, SourceSpan
from retrieval.experiments import kure_evaluation as runner
from tests.retrieval.helpers import WordTokenizer, make_document, make_snapshot


class FakeQueryEncoder:
    def __init__(self, *, model="kure", vector=None):
        self.model_id = (
            runner.KURE_MODEL_ID if model == "kure" else runner.TINY_MODEL_ID
        )
        self.revision = runner.KURE_REVISION if model == "kure" else MODEL_REVISION
        self.dimension = runner.KURE_DIMENSION if model == "kure" else VECTOR_DIMENSION
        self.tokenizer = WordTokenizer()
        self.vector = vector
        self.calls = []

    def count_query_tokens(self, question):
        return len(question.split()) + 2

    def encode_queries(self, questions):
        self.calls.extend(questions)
        if self.vector is not None:
            return np.stack([self.vector for _ in questions]).astype(np.float32)
        vectors = np.zeros((len(questions), self.dimension), dtype=np.float32)
        vectors[:, 0] = 1
        return vectors


def _case(case_id="Q1", *, question="이 정책은?", related=True, gate_negative=False):
    body = "관련 정책 근거입니다."
    return {
        "case_id": case_id,
        "question": question,
        "intent_group": case_id,
        "answerability": "answerable",
        "required_claims": [
            {
                "claim_id": f"{case_id}-r1",
                "claim": "관련 정책 근거",
                "evidence_alternatives": [
                    {
                        "document_id": "ieum-001",
                        "spans": [{"start": 0, "end": len(body), "text": body}],
                    }
                ],
            }
        ],
        "optional_claims": [],
        "review_status": "independent_ai_reviewed",
        "related": related,
        "gate_negative": gate_negative,
    }


def _chunk(document, chunk_id="chunk-1"):
    return Chunk(
        document_id=document.document_id,
        revision_id=document.revision_id,
        ordinal=0,
        spans=(SourceSpan(0, len(document.body)),),
        heading="정책",
        embedding_header="정책",
        text=document.body,
        embedding_text="정책\n" + document.body,
        input_key="input-key",
        chunk_id=chunk_id,
    )


class CaseValidationTests(unittest.TestCase):
    def test_confirmation_requires_exact_counts_and_rejects_duplicates(self):
        cases = []
        for index in range(20):
            cases.append(
                {
                    **_case(f"H{index + 1:02}", related=True),
                    "answerability": "answerable",
                }
            )
        for index in range(5):
            cases.append(
                {
                    **_case(f"H{index + 21:02}", related=True),
                    "answerability": "partial",
                }
            )
        for index in range(5):
            cases.append(
                {
                    **_case(f"H{index + 26:02}", related=True),
                    "answerability": "unanswerable",
                    "required_claims": [],
                }
            )
        for index in range(10):
            cases.append(
                {
                    **_case(f"H{index + 31:02}", related=False, gate_negative=True),
                    "answerability": "unanswerable",
                    "required_claims": [],
                }
            )
        payload = {
            "status": "frozen_independent_ai_reviewed",
            "cases": cases,
        }
        self.assertEqual(
            runner._validate_case_set(payload, phase="confirmation"), cases
        )

        duplicated = {**payload, "cases": [*cases[:-1], cases[0]]}
        with self.assertRaisesRegex(ValueError, "duplicate case ID"):
            runner._validate_case_set(duplicated, phase="confirmation")

        wrong_answerability = {
            **payload,
            "cases": [*cases[:-1], {**cases[-1], "answerability": "partial"}],
        }
        with self.assertRaisesRegex(ValueError, "answerability counts"):
            runner._validate_case_set(wrong_answerability, phase="confirmation")

    def test_development_keeps_canonical_48_first_and_preserves_qrel_content(self):
        canonical = json.loads(runner.QREL_V3_PATH.read_text(encoding="utf-8"))
        cases = [
            {
                **case,
                "related": case["case_id"] not in {"U01", "U02", "U05"},
                "gate_negative": False,
            }
            for case in canonical["cases"]
        ]
        cases.extend(
            {
                **_case(
                    f"G{index + 1:02}", related=index < 10, gate_negative=index >= 10
                ),
                "answerability": "unanswerable",
                "required_claims": [],
            }
            for index in range(20)
        )
        payload = {
            "status": "frozen_independent_ai_reviewed",
            "cases": cases,
        }
        self.assertEqual(runner._validate_case_set(payload, phase="development"), cases)
        misclassified_qrel = [dict(case) for case in cases]
        misclassified_qrel[0]["related"] = False
        misclassified_qrel[0]["gate_negative"] = True
        with self.assertRaisesRegex(
            ValueError, "canonical qrel-v3 cases cannot be gate negatives"
        ):
            runner._validate_case_set(
                {**payload, "cases": misclassified_qrel}, phase="development"
            )
        changed = [dict(case) for case in cases]
        changed[0]["required_claims"] = []
        with self.assertRaisesRegex(ValueError, "canonical qrel-v3 content changed"):
            runner._validate_original_qrel_cases(changed, canonical["cases"])


class CandidateFreezeTests(unittest.TestCase):
    def test_candidate_freeze_binds_confirmation_and_development_raw_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development.json"
            development.write_text(
                json.dumps(
                    {
                        "phase": "development",
                        "model_id": runner.KURE_MODEL_ID,
                        "model_revision": runner.KURE_REVISION,
                        "cases_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )
            confirmation_sha = "b" * 64
            freeze_path = root / "candidate-freeze.json"
            freeze_path.write_text(
                json.dumps(
                    {
                        "status": "frozen_candidate",
                        "threshold": 0.49,
                        "model_id": runner.KURE_MODEL_ID,
                        "model_revision": runner.KURE_REVISION,
                        "top_k": 20,
                        "confirmation_cases_sha256": confirmation_sha,
                        "development_cases_sha256": "a" * 64,
                        "development_results_sha256": runner.digest_file(development),
                        "development_results_path": str(development),
                        "created_at": "2026-10-16T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            loaded = runner._validate_candidate_freeze(
                freeze_path,
                expected_case_sha=confirmation_sha,
                case_sha_field="confirmation_cases_sha256",
            )
            self.assertEqual(loaded["threshold"], 0.49)
            self.assertEqual(loaded["sha256"], runner.digest_file(freeze_path))

            with self.assertRaisesRegex(ValueError, "confirmation_cases_sha256"):
                runner._validate_candidate_freeze(
                    freeze_path,
                    expected_case_sha="c" * 64,
                    case_sha_field="confirmation_cases_sha256",
                )
            development.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "development results SHA-256"):
                runner._validate_candidate_freeze(
                    freeze_path,
                    expected_case_sha=confirmation_sha,
                    case_sha_field="confirmation_cases_sha256",
                )


class VectorProvenanceTests(unittest.TestCase):
    def test_kure_pilot_vectors_require_revision_qrels_sources_norm_and_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kure = root / "kure"
            kure.mkdir()
            chunk_ids = [f"chunk-{index:03}" for index in range(298)]
            matrix = np.zeros((298, runner.KURE_DIMENSION), dtype=np.float32)
            scores = np.linspace(0.99, 0.1, len(chunk_ids), dtype=np.float32)
            matrix[:, 0] = scores
            matrix[:, 1] = np.sqrt(1 - scores**2)
            np.save(kure / "vectors.npy", matrix)
            canonical_qrels = json.loads(
                runner.QREL_V3_PATH.read_text(encoding="utf-8")
            )
            query_vectors = np.zeros(
                (len(canonical_qrels["cases"]), runner.KURE_DIMENSION),
                dtype=np.float32,
            )
            query_vectors[:, 0] = 1
            np.save(kure / "queries.npy", query_vectors)
            canonical_qrels_sha = runner.digest_file(runner.QREL_V3_PATH)
            (kure / "results.json").write_text(
                json.dumps(
                    {
                        "model": "kure",
                        "revision": runner.KURE_REVISION,
                        "qrels_sha": canonical_qrels_sha,
                        "snapshot": "snapshot",
                        "chunks": 298,
                        "max_document_tokens": 371,
                        "source_hashes": {
                            "source": "source-sha",
                            "index": "index-sha",
                        },
                        "rankings": [
                            {
                                "case_id": case["case_id"],
                                "ranking": [
                                    {"chunk_id": chunk_id, "score": float(score)}
                                    for chunk_id, score in zip(
                                        chunk_ids, scores, strict=True
                                    )
                                ],
                            }
                            for case in canonical_qrels["cases"]
                        ],
                    }
                ),
                encoding="utf-8",
            )
            vectors, provenance = runner._validate_kure_pilot(
                root,
                snapshot_fingerprint="snapshot",
                chunk_ids=chunk_ids,
                source_sha256="source-sha",
                index_sha256="index-sha",
                canonical_qrels_sha256=canonical_qrels_sha,
            )
            self.assertEqual(vectors.shape, (298, 1024))
            self.assertEqual(
                provenance["vector_sha256"], runner.digest_file(kure / "vectors.npy")
            )
            self.assertEqual(
                provenance["pilot_results_sha256"],
                runner.digest_file(kure / "results.json"),
            )
            matrix[0, 0] = 2
            np.save(kure / "vectors.npy", matrix)
            with self.assertRaisesRegex(ValueError, "L2 normalized"):
                runner._validate_kure_pilot(
                    root,
                    snapshot_fingerprint="snapshot",
                    chunk_ids=chunk_ids,
                    source_sha256="source-sha",
                    index_sha256="index-sha",
                    canonical_qrels_sha256=canonical_qrels_sha,
                )
            matrix[0, 0] = scores[0]
            matrix[0, 1] = np.sqrt(1 - scores[0] ** 2)
            matrix[[0, 1]] = matrix[[1, 0]]
            np.save(kure / "vectors.npy", matrix)
            with self.assertRaisesRegex(ValueError, "pilot ranking differs"):
                runner._validate_kure_pilot(
                    root,
                    snapshot_fingerprint="snapshot",
                    chunk_ids=chunk_ids,
                    source_sha256="source-sha",
                    index_sha256="index-sha",
                    canonical_qrels_sha256=canonical_qrels_sha,
                )
            self.assertEqual(
                provenance["pilot_queries_sha256"],
                runner.digest_file(kure / "queries.npy"),
            )

    def test_copy_isolation_reads_unchanged_bytes_into_a_separate_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact"
            source = artifact / "source/documents.sqlite3"
            index = (
                artifact
                / "retrieval/schema-v1"
                / runner.retrieval_spec_id(DEFAULT_SPEC)
                / "index.sqlite3"
            )
            source.parent.mkdir(parents=True)
            index.parent.mkdir(parents=True)
            source.write_bytes(b"source database bytes")
            index.write_bytes(b"vector index bytes")
            staging = root / "staging"
            staging.mkdir()
            copied = runner._copy_isolated_inputs(
                artifact,
                staging,
                {
                    "published_database": "source/documents.sqlite3",
                    "isolated_retrieval_root": "retrieval",
                    "retrieval_spec_id": runner.retrieval_spec_id(DEFAULT_SPEC),
                },
            )
            source_before = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(copied["source_sha256"], source_before)
            copied["copied_source"].write_bytes(b"modified isolated copy")
            self.assertEqual(source.read_bytes(), b"source database bytes")
            self.assertEqual(index.read_bytes(), b"vector index bytes")

    def test_isolated_copy_keeps_the_published_snapshot_when_original_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact"
            source_path = artifact / "source/documents.sqlite3"
            source_path.parent.mkdir(parents=True)
            source_repository = DocumentRepository(source_path)
            source_repository.initialize()

            def publish(document_id, title, body):
                fields = {
                    "title": title,
                    "body": body,
                    "source_label": "test",
                    "source_url": None,
                    "owner_department": None,
                    "effective_from": None,
                }
                with source_repository.transaction() as connection:
                    created = source_repository.create_in_transaction(
                        connection, fields, document_id=document_id
                    )
                with source_repository.transaction() as connection:
                    source_repository.publish_in_transaction(
                        connection,
                        document_id,
                        created["record_version"],
                        created["draft"]["id"],
                    )

            publish("doc-1", "첫 안내", "현재 게시된 원문 안내입니다.")
            original_snapshot = DocumentContextProvider(
                database_path=source_path
            ).snapshot()
            document = original_snapshot.documents[0]
            chunks = chunk_document(document, WordTokenizer())
            self.assertEqual(len(chunks), 1)
            repository = IndexRepository(artifact / "retrieval")
            repository.initialize()
            vector = np.zeros((1, VECTOR_DIMENSION), dtype=np.float32)
            vector[0, 0] = 1
            repository.store_documents([(document, chunks, vector)])

            spec_id = runner.retrieval_spec_id(DEFAULT_SPEC)
            manifest = {
                "source": {
                    "published_database": "source/documents.sqlite3",
                    "isolated_retrieval_root": "retrieval",
                    "retrieval_spec": DEFAULT_SPEC.to_dict(),
                    "retrieval_spec_id": spec_id,
                    "snapshot_fingerprint": original_snapshot.fingerprint,
                }
            }
            staging = root / "staging"
            staging.mkdir()
            copied = runner._copy_isolated_inputs(artifact, staging, manifest["source"])

            publish("doc-2", "추가 안내", "복사 후 추가한 문서입니다.")
            changed_original = DocumentContextProvider(
                database_path=source_path
            ).snapshot()
            copied_snapshot = DocumentContextProvider(
                database_path=copied["copied_source"]
            ).snapshot()
            copied_chunks = IndexRepository(
                staging / "isolated-input/retrieval"
            ).current_chunks(copied_snapshot)

            self.assertNotEqual(
                changed_original.fingerprint, original_snapshot.fingerprint
            )
            self.assertEqual(copied_snapshot.fingerprint, original_snapshot.fingerprint)
            self.assertEqual(len(copied_chunks), 1)
            self.assertEqual(copied_chunks[0][0].text, document.body)


class RankingRunnerTests(unittest.TestCase):
    def setUp(self):
        self.document = make_document(
            knowledge_id="ieum-001",
            body="관련 정책 근거입니다.",
        )
        self.snapshot = make_snapshot(self.document)
        self.chunk = _chunk(self.document)
        self.case = _case()
        self.query = np.zeros(runner.KURE_DIMENSION, dtype=np.float32)
        self.query[0] = 1
        self.encoder = FakeQueryEncoder(vector=self.query)

    def test_development_uses_raw_top20_and_does_not_gate_low_score_evidence(self):
        passage = np.zeros(runner.KURE_DIMENSION, dtype=np.float32)
        passage[0] = 0.2
        passage[1] = math.sqrt(1 - 0.2**2)
        row = runner._rank_case(
            self.case,
            self.snapshot,
            [(self.chunk, passage)],
            np.stack([passage]),
            self.encoder,
            model="kure",
            phase="development",
            threshold=None,
        )
        self.assertAlmostEqual(row["maximum"], 0.2)
        self.assertFalse(row["gate_rejected"])
        self.assertEqual(row["policy"], "kure_raw_top20_no_gate")
        self.assertTrue(row["complete"])
        self.assertEqual(row["selected_chunk_ids"], ["chunk-1"])
        json.dumps(row, ensure_ascii=False)

    def test_confirmation_applies_gate_once_to_question_then_keeps_ranked_hits(self):
        passage = np.zeros(runner.KURE_DIMENSION, dtype=np.float32)
        passage[0] = 0.2
        passage[1] = math.sqrt(1 - 0.2**2)
        rejected = runner._rank_case(
            self.case,
            self.snapshot,
            [(self.chunk, passage)],
            np.stack([passage]),
            self.encoder,
            model="kure",
            phase="confirmation",
            threshold=0.3,
        )
        self.assertTrue(rejected["gate_rejected"])
        self.assertEqual(rejected["selected_chunk_ids"], [])
        self.assertFalse(rejected["complete"])

        strong = np.zeros(runner.KURE_DIMENSION, dtype=np.float32)
        strong[0] = 1
        passed = runner._rank_case(
            self.case,
            self.snapshot,
            [(self.chunk, strong)],
            np.stack([strong]),
            self.encoder,
            model="kure",
            phase="confirmation",
            threshold=0.3,
        )
        self.assertFalse(passed["gate_rejected"])
        self.assertEqual(passed["selected_chunk_ids"], ["chunk-1"])
        self.assertTrue(passed["complete"])

    def test_confirmation_evaluate_writes_provenance_bound_flat_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact"
            database_path = artifact / "source/documents.sqlite3"
            database_path.parent.mkdir(parents=True)
            document_repository = DocumentRepository(database_path)
            document_repository.initialize()
            fields = {
                "title": "정책 안내",
                "body": self.document.body,
                "source_label": "test",
                "source_url": None,
                "owner_department": None,
                "effective_from": None,
            }
            with document_repository.transaction() as connection:
                created = document_repository.create_in_transaction(
                    connection, fields, document_id="ieum-001"
                )
            with document_repository.transaction() as connection:
                document_repository.publish_in_transaction(
                    connection,
                    "ieum-001",
                    created["record_version"],
                    created["draft"]["id"],
                )
            snapshot = DocumentContextProvider(database_path=database_path).snapshot()
            document = snapshot.documents[0]
            chunks = chunk_document(document, WordTokenizer())
            index_repository = IndexRepository(artifact / "retrieval")
            index_repository.initialize()
            tiny_vectors = np.zeros((len(chunks), VECTOR_DIMENSION), dtype=np.float32)
            tiny_vectors[:, 0] = 1
            index_repository.store_documents([(document, chunks, tiny_vectors)])

            spec_id = runner.retrieval_spec_id(DEFAULT_SPEC)
            source_manifest = {
                "published_database": "source/documents.sqlite3",
                "isolated_retrieval_root": "retrieval",
                "retrieval_spec": DEFAULT_SPEC.to_dict(),
                "retrieval_spec_id": spec_id,
                "snapshot_fingerprint": snapshot.fingerprint,
            }
            (artifact / "manifest.json").write_text(
                json.dumps({"source": source_manifest}), encoding="utf-8"
            )
            index_path = artifact / "retrieval/schema-v1" / spec_id / "index.sqlite3"
            source_sha = runner.digest_file(database_path)
            index_sha = runner.digest_file(index_path)

            confirmation_cases = []
            answerability = (
                [
                    "answerable",
                ]
                * 20
                + ["partial"] * 5
                + ["unanswerable"] * 15
            )
            for index, category in enumerate(answerability):
                related = index < 30
                gate_negative = index >= 30
                case = _case(
                    f"H{index + 1:02}",
                    related=related,
                    gate_negative=gate_negative,
                )
                case["answerability"] = category
                if category == "unanswerable":
                    case["required_claims"] = []
                confirmation_cases.append(case)
            cases_path = root / "confirmation.json"
            cases_raw = json.dumps(
                {
                    "status": "frozen_independent_ai_reviewed",
                    "cases": confirmation_cases,
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            cases_path.write_bytes(cases_raw)
            cases_sha = hashlib.sha256(cases_raw).hexdigest()

            development_path = root / "development-results.json"
            development_cases_sha = "a" * 64
            development_path.write_text(
                json.dumps(
                    {
                        "phase": "development",
                        "model_id": runner.KURE_MODEL_ID,
                        "model_revision": runner.KURE_REVISION,
                        "cases_sha256": development_cases_sha,
                    }
                ),
                encoding="utf-8",
            )
            freeze_path = root / "candidate-freeze.json"
            freeze_path.write_text(
                json.dumps(
                    {
                        "status": "frozen_candidate",
                        "threshold": 0.5,
                        "model_id": runner.KURE_MODEL_ID,
                        "model_revision": runner.KURE_REVISION,
                        "top_k": 20,
                        "confirmation_cases_sha256": cases_sha,
                        "development_cases_sha256": development_cases_sha,
                        "development_results_sha256": runner.digest_file(
                            development_path
                        ),
                        "development_results_path": str(development_path),
                        "created_at": "2026-10-16T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            pilot_root = root / "pilot"
            pilot_kure = pilot_root / "kure"
            pilot_kure.mkdir(parents=True)
            kure_vectors = np.zeros(
                (len(chunks), runner.KURE_DIMENSION), dtype=np.float32
            )
            kure_vectors[:, 0] = 1
            np.save(pilot_kure / "vectors.npy", kure_vectors)
            pilot_cases = json.loads(runner.QREL_V3_PATH.read_text(encoding="utf-8"))[
                "cases"
            ]
            pilot_queries = np.zeros(
                (len(pilot_cases), runner.KURE_DIMENSION), dtype=np.float32
            )
            pilot_queries[:, 0] = 1
            np.save(pilot_kure / "queries.npy", pilot_queries)
            canonical_qrels_sha = runner.digest_file(runner.QREL_V3_PATH)
            (pilot_kure / "results.json").write_text(
                json.dumps(
                    {
                        "model": "kure",
                        "revision": runner.KURE_REVISION,
                        "qrels_sha": canonical_qrels_sha,
                        "snapshot": snapshot.fingerprint,
                        "chunks": len(chunks),
                        "max_document_tokens": 5,
                        "source_hashes": {
                            str(database_path): source_sha,
                            str(index_path): index_sha,
                        },
                        "rankings": [
                            {
                                "case_id": case["case_id"],
                                "ranking": [
                                    {"chunk_id": chunks[0].chunk_id, "score": 1.0}
                                ],
                            }
                            for case in pilot_cases
                        ],
                    }
                ),
                encoding="utf-8",
            )
            model_path = root / "local-kure"
            model_path.mkdir()
            output = root / "confirmation-output"
            before = (source_sha, index_sha)
            fake_encoder = FakeQueryEncoder()
            with patch.object(runner, "EXPECTED_CHUNK_COUNT", len(chunks)):
                result_path = runner.evaluate(
                    SimpleNamespace(
                        phase="confirmation",
                        model="kure",
                        benchmark=False,
                        cases=cases_path,
                        output=output,
                        artifact_root=artifact,
                        model_path=model_path,
                        pilot_root=pilot_root,
                        candidate_freeze=freeze_path,
                    ),
                    encoder_factory=lambda model, path: fake_encoder,
                )
            result = json.loads(result_path.read_text(encoding="utf-8"))

            self.assertEqual(len(result["rows"]), 40)
            self.assertEqual(
                [row["case_id"] for row in result["rows"]],
                [case["case_id"] for case in confirmation_cases],
            )
            self.assertTrue(all(row["maximum"] == 1.0 for row in result["rows"]))
            self.assertTrue(all(not row["gate_rejected"] for row in result["rows"]))
            self.assertTrue(all(row["complete"] is True for row in result["rows"][:25]))
            self.assertTrue(all(row["complete"] is None for row in result["rows"][25:]))
            self.assertFalse(result["query_cache_used"])
            self.assertEqual(
                result["vector_provenance"]["pilot_results_sha256"],
                runner.digest_file(pilot_kure / "results.json"),
            )
            self.assertEqual(
                before,
                (runner.digest_file(database_path), runner.digest_file(index_path)),
            )
            self.assertEqual(
                len(fake_encoder.calls), 41
            )  # one warmup plus each of the 40 input cases

    def test_each_case_recomputes_same_question_without_a_query_cache(self):
        for case_id in ("Q1", "Q2"):
            runner._rank_case(
                {**self.case, "case_id": case_id},
                self.snapshot,
                [(self.chunk, self.query)],
                np.stack([self.query]),
                self.encoder,
                model="kure",
                phase="development",
                threshold=None,
            )
        self.assertEqual(
            self.encoder.calls, [self.case["question"], self.case["question"]]
        )

    def test_benchmark_completes_three_rounds_at_each_concurrency(self):
        cases = [{"case_id": f"R{index:02}"} for index in range(48)]
        with patch.object(runner, "_rank_case", return_value={}):
            benchmark = runner._run_benchmark(
                cases,
                snapshot=None,
                current=[],
                matrix=np.empty((0, runner.KURE_DIMENSION), dtype=np.float32),
                encoder=self.encoder,
                threshold=0.5,
            )

        self.assertEqual(benchmark["case_ids"], [case["case_id"] for case in cases])
        self.assertEqual(benchmark["rounds"], 3)
        self.assertEqual(
            [
                (run["concurrency"], run["requested"], run["completed"])
                for run in benchmark["runs"]
            ],
            [(1, 144, 144), (2, 144, 144)],
        )
        self.assertTrue(all(run["p95_ms"] >= 0 for run in benchmark["runs"]))

    def test_query_limit_and_output_id_validation_fail_closed(self):
        long_case = {**self.case, "question": "token " * 511}
        with self.assertRaisesRegex(ValueError, "512-token"):
            runner._rank_case(
                long_case,
                self.snapshot,
                [(self.chunk, self.query)],
                np.stack([self.query]),
                self.encoder,
                model="kure",
                phase="development",
                threshold=None,
            )
        with self.assertRaisesRegex(ValueError, "case IDs"):
            runner._validate_output_rows(
                [self.case, {**self.case, "case_id": "Q2"}],
                [{"case_id": "Q1"}],
            )


if __name__ == "__main__":
    unittest.main()
