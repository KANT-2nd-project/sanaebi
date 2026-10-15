"""Frozen, offline retrieval ranking and evidence-selection experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from app.documents.context import DocumentContextProvider
from app.retrieval.config import DEFAULT_SPEC, MODEL_REVISION, retrieval_spec_id
from app.retrieval.embedding import TinyEmbedder
from app.retrieval.repository import IndexRepository
from retrieval.experiments.calibration_metrics import ranking_metrics
from retrieval.experiments.calibration_search import select_evidence

ROOT = Path(__file__).resolve().parents[2]
BGE_MODEL_ID = "BAAI/bge-reranker-v2-m3"
BGE_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
COSINE_THRESHOLD = 0.35
RERANK_CANDIDATE_COUNT = 40
RANK_CUTOFFS = (5, 8, 10, 12, 20, 40)
DEFAULT_VARIANT_IDS = (
    "baseline",
    "A_existing",
    "B_tokens_only",
    "C_unlimited",
    "adjacent_top5",
    "adjacent_top8",
    "adjacent_top12",
    "bge_rerank_top5",
    "bge_rerank_top8",
    "bge_rerank_top12",
)


def parse_variant_ids(variant_ids):
    """Validate requested experiment variants; ``None`` selects development set."""
    if variant_ids is None:
        return DEFAULT_VARIANT_IDS
    if isinstance(variant_ids, str):
        variant_ids = [variant_ids]
    values = tuple(variant_ids)
    unknown = [value for value in values if value not in DEFAULT_VARIANT_IDS]
    if unknown:
        raise ValueError(f"unknown variant: {unknown[0]}")
    if len(set(values)) != len(values):
        raise ValueError("duplicate variant IDs are not allowed")
    if not values:
        raise ValueError("at least one variant must be selected")
    return values


def variants_require_reranker(variant_ids):
    return any(variant_id.startswith("bge_rerank_") for variant_id in variant_ids)


def load_requested_reranker(variant_ids, model_path, manifest_path, *, batch_size=8):
    if not variants_require_reranker(variant_ids):
        return None
    if model_path is None or manifest_path is None:
        raise ValueError("BGE variants require local reranker model and manifest paths")
    reranker = LocalBgeReranker(model_path, manifest_path, batch_size=batch_size)
    reranker.warmup()
    return reranker


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_frozen_qrels(qrels: dict[str, Any]) -> None:
    """Reject draft qrels and malformed case identity before any model work."""
    if qrels.get("status") != "frozen_independent_ai_reviewed":
        raise ValueError("independently reviewed frozen qrels are required")
    cases = qrels.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("frozen qrels must contain cases")
    case_ids = []
    for case in cases:
        if not isinstance(case, dict):
            raise TypeError("qrel case must be an object")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("qrel case_id must be a nonempty string")
        if not isinstance(case.get("question"), str):
            raise TypeError(f"{case_id}: question must be a string")
        if case.get("answerability") not in {
            "answerable",
            "partial",
            "unanswerable",
        }:
            raise ValueError(f"{case_id}: invalid answerability")
        if case.get("review_status") != "independent_ai_reviewed":
            raise ValueError(f"{case_id}: independent qrel review is required")
        claims = case.get("required_claims", [])
        if not isinstance(claims, list):
            raise TypeError(f"{case_id}: required_claims must be a list")
        for claim in claims:
            if (
                not isinstance(claim, dict)
                or not isinstance(claim.get("evidence_alternatives"), list)
                or not claim["evidence_alternatives"]
            ):
                raise ValueError(f"{case_id}: malformed required claim")
        case_ids.append(case_id)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("frozen qrel case IDs must be unique")


def _section_path(heading: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in heading.split(">") if part.strip())


def _same_nonempty_upper_section(left, right) -> bool:
    if left.document_id != right.document_id or left.revision_id != right.revision_id:
        return False
    left_path = _section_path(left.heading)
    right_path = _section_path(right.heading)
    common = 0
    for left_part, right_part in zip(left_path, right_path, strict=False):
        if left_part != right_part:
            break
        common += 1
    return common > 0


def expand_adjacent_hits(anchors, current_chunks):
    """Add immediate ordinal neighbors only inside a shared named section."""
    ordered = sorted(anchors, key=lambda item: (-float(item[1]), item[0].chunk_id))
    by_position = {}
    for chunk in current_chunks:
        key = (chunk.document_id, chunk.revision_id, chunk.ordinal)
        if key in by_position:
            raise ValueError("duplicate document revision chunk ordinal")
        by_position[key] = chunk

    anchor_ids = {chunk.chunk_id for chunk, _ in ordered}
    result = [(chunk, float(score), "anchor", None) for chunk, score in ordered]
    additions: dict[str, tuple[Any, float, str, str]] = {}
    for anchor, anchor_score in ordered:
        for offset in (-1, 1):
            neighbor = by_position.get(
                (
                    anchor.document_id,
                    anchor.revision_id,
                    anchor.ordinal + offset,
                )
            )
            if (
                neighbor is None
                or neighbor.chunk_id in anchor_ids
                or not _same_nonempty_upper_section(anchor, neighbor)
            ):
                continue
            additions.setdefault(
                neighbor.chunk_id,
                (neighbor, float(anchor_score), "expanded", anchor.chunk_id),
            )
    result.extend(additions.values())
    return result


def _new_variant_top_k(variant_id: str, prefix: str) -> int | None:
    marker = f"{prefix}_top"
    if not variant_id.startswith(marker):
        return None
    try:
        top_k = int(variant_id[len(marker) :])
    except ValueError as exc:
        raise ValueError(f"invalid variant ID: {variant_id}") from exc
    if top_k not in {5, 8, 12}:
        raise ValueError(f"unsupported variant ID: {variant_id}")
    return top_k


def select_variant_evidence(
    variant_id,
    cosine_ranked,
    snapshot,
    tokenizer,
    *,
    current_chunks=None,
    reranked=None,
):
    """Apply one named variant with selection score kept distinct by its caller."""
    ranked = sorted(
        ((chunk, float(score)) for chunk, score in cosine_ranked),
        key=lambda item: (-item[1], item[0].chunk_id),
    )

    if variant_id == "baseline":
        hits = ranked[:10]
        return select_evidence(
            hits,
            snapshot,
            5,
            tokenizer,
            None,
            total_chars=8000,
            per_evidence_chars=2000,
        )

    if variant_id in {"A_existing", "B_tokens_only", "C_unlimited"}:
        hits = [(chunk, score) for chunk, score in ranked if score >= COSINE_THRESHOLD]
        if variant_id == "A_existing":
            return select_evidence(
                hits,
                snapshot,
                math.inf,
                tokenizer,
                4000,
                total_chars=8000,
                per_evidence_chars=2000,
            )
        if variant_id == "B_tokens_only":
            return select_evidence(
                hits,
                snapshot,
                math.inf,
                tokenizer,
                4000,
                total_chars=None,
                per_evidence_chars=None,
            )
        return select_evidence(
            hits,
            snapshot,
            math.inf,
            tokenizer,
            None,
            total_chars=None,
            per_evidence_chars=None,
        )

    if not ranked or ranked[0][1] < COSINE_THRESHOLD:
        return []

    top_k = _new_variant_top_k(variant_id, "adjacent")
    if top_k is not None:
        if current_chunks is None:
            raise ValueError("current_chunks are required for adjacent variants")
        hits = expand_adjacent_hits(ranked[:top_k], current_chunks)
        return select_evidence(
            hits,
            snapshot,
            math.inf,
            tokenizer,
            None,
            total_chars=None,
            per_evidence_chars=None,
        )

    top_k = _new_variant_top_k(variant_id, "bge_rerank")
    if top_k is not None:
        if reranked is None:
            raise ValueError("reranked candidates are required for BGE variants")
        cosine_by_id = {chunk.chunk_id: score for chunk, score in ranked}
        selected = sorted(
            reranked,
            key=lambda item: (-float(item[1]), item[0].chunk_id),
        )[:top_k]
        # Evidence.score is an internal selection score; serialized experiment
        # records replace it with the separately named cosine/reranker values.
        hits = [(chunk, float(score)) for chunk, score in selected]
        if any(chunk.chunk_id not in cosine_by_id for chunk, _ in hits):
            raise ValueError("reranked candidates must come from cosine ranking")
        return select_evidence(
            hits,
            snapshot,
            math.inf,
            tokenizer,
            None,
            total_chars=None,
            per_evidence_chars=None,
        )
    raise ValueError(f"unknown variant ID: {variant_id}")


def score_evidence(evidence, cosine_scores, rerank_scores=None):
    """Serialize evidence without conflating cosine and cross-encoder scores."""
    rerank_scores = {} if rerank_scores is None else rerank_scores
    chunk_ids = tuple(evidence.chunk_ids)
    cosine_values = [cosine_scores[cid] for cid in chunk_ids if cid in cosine_scores]
    rerank_values = [rerank_scores[cid] for cid in chunk_ids if cid in rerank_scores]
    result = {
        "knowledge_id": evidence.knowledge_id,
        "document_id": evidence.document_id,
        "revision_id": evidence.revision_id,
        "revision": evidence.revision,
        "title": evidence.title,
        "text": evidence.text,
        "source_reference": evidence.source_reference,
        "spans": [asdict(span) for span in evidence.spans],
        "chunk_ids": chunk_ids,
        "expanded_chunk_ids": tuple(evidence.expanded_chunk_ids),
        "rank": evidence.rank,
        "cosine_score": max(cosine_values) if cosine_values else None,
        "rerank_score": max(rerank_values) if rerank_values else None,
    }
    return result


def make_relevance_packet(cases, chunks_by_id, documents_by_id, pool_ids_by_case):
    """Build a score/config-blind, qrel-conditioned relevance review packet."""
    packet_cases = []
    for case in cases:
        case_id = case["case_id"]
        passages = []
        for chunk_id in sorted(pool_ids_by_case.get(case_id, set())):
            chunk = chunks_by_id[chunk_id]
            document = documents_by_id[chunk.document_id]
            passages.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": document.knowledge_id,
                    "revision_id": chunk.revision_id,
                    "title": document.title,
                    "heading": chunk.heading,
                    "text": chunk.text,
                    "spans": [asdict(span) for span in chunk.spans],
                }
            )
        packet_cases.append(
            {
                "case_id": case_id,
                "question": case["question"],
                "answerability": case["answerability"],
                "required_claims": case.get("required_claims", []),
                "passages": passages,
            }
        )
    return {
        "schema_version": 1,
        "judgment_context": "qrel_conditioned_independent_relevance_review",
        "cases": packet_cases,
    }


def evaluate_rankings(rankings, grades, cutoffs=RANK_CUTOFFS):
    """Grade-join API for later use after blinded passage labels are returned."""
    if any(
        not isinstance(grade, int) or isinstance(grade, bool) or grade not in range(4)
        for grade in grades.values()
    ):
        raise ValueError("relevance grades must be integers from 0 through 3")
    return {
        str(cutoff): ranking_metrics(
            [item["chunk_id"] for item in rankings], grades, cutoff
        )
        for cutoff in cutoffs
    }


def validate_reranker_manifest(manifest_path: Path, model_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("reranker source manifest is missing or invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("model_id") != BGE_MODEL_ID
        or manifest.get("revision") != BGE_REVISION
    ):
        raise ValueError("reranker source manifest does not match the pinned model")
    files = manifest.get("files")
    if isinstance(files, dict):
        entries = list(files.items())
    elif isinstance(files, list):
        entries = []
        for item in files:
            if isinstance(item, str):
                entries.append((item, None))
            elif isinstance(item, dict):
                name = item.get("path", item.get("name"))
                entries.append((name, item.get("sha256")))
            else:
                raise TypeError("reranker manifest files list is malformed")
    else:
        raise TypeError("reranker manifest must list model files")
    if not entries:
        raise ValueError("reranker manifest file list is empty")
    root = model_path.resolve()
    listed_files = set()
    for relative, expected in entries:
        if not isinstance(relative, str) or not relative:
            raise ValueError("reranker manifest contains an invalid file path")
        file_path = (root / relative).resolve()
        if root not in file_path.parents or not file_path.is_file():
            if relative.startswith("assets/") or relative in {
                "README.md",
                ".gitattributes",
            }:
                continue
            raise ValueError(f"reranker model file is missing: {relative}")
        listed_files.add(relative)
        if isinstance(expected, dict):
            expected = expected.get("sha256")
        if expected is not None and digest_file(file_path) != expected:
            raise ValueError(f"reranker model file hash mismatch: {relative}")
    required_files = {
        "config.json",
        "model.safetensors",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }
    if not required_files.issubset(listed_files):
        raise ValueError("reranker manifest omits a required model or tokenizer file")
    if not model_path.is_dir():
        raise ValueError("local reranker model directory is missing")
    return manifest


class LocalBgeReranker:
    """Pinned local-only CPU BGE scorer with non-truncating pair tokenization."""

    def __init__(self, model_path: Path, manifest_path: Path, *, batch_size=8):
        if batch_size < 1:
            raise ValueError("reranker batch size must be positive")
        self.model_path = model_path
        self.manifest_path = manifest_path
        self.batch_size = batch_size
        self.manifest = None
        self.tokenizer = None
        self.model = None
        self.torch = None
        self.native_token_limit = None
        self.file_hashes = {}
        self._lock = threading.RLock()

    def warmup(self):
        with self._lock:
            if self.model is not None:
                return
            self.manifest = validate_reranker_manifest(
                self.manifest_path, self.model_path
            )
            try:
                import torch
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )

                tokenizer = AutoTokenizer.from_pretrained(
                    str(self.model_path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                model = AutoModelForSequenceClassification.from_pretrained(
                    str(self.model_path),
                    local_files_only=True,
                    trust_remote_code=False,
                )
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(
                    "local pinned BGE reranker could not be loaded"
                ) from exc

            tokenizer_limit = getattr(tokenizer, "model_max_length", None)
            configured_limit = getattr(model.config, "max_position_embeddings", None)
            if (
                not isinstance(tokenizer_limit, int)
                or tokenizer_limit <= 0
                or tokenizer_limit >= 10**9
                or not isinstance(configured_limit, int)
                or configured_limit < tokenizer_limit
            ):
                raise ValueError("reranker native token limit cannot be verified")
            if getattr(model.config, "num_labels", None) != 1:
                raise ValueError("pinned reranker must emit one raw relevance logit")
            torch.set_num_threads(2)
            model.to(device="cpu", dtype=torch.float32)
            model.eval()
            self.tokenizer = tokenizer
            self.model = model
            self.torch = torch
            self.native_token_limit = tokenizer_limit
            raw_files = self.manifest["files"]
            names = raw_files.keys() if isinstance(raw_files, dict) else raw_files
            for item in names:
                relative = (
                    item
                    if isinstance(item, str)
                    else item.get("path", item.get("name"))
                )
                if isinstance(relative, str):
                    path = self.model_path / relative
                    if path.is_file():
                        self.file_hashes[relative] = digest_file(path)

    def score_pairs(self, pairs):
        self.warmup()
        with self._lock:
            return self._score_pairs_locked(pairs)

    def _score_pairs_locked(self, pairs):
        scored = []
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start : start + self.batch_size]
            queries = [query for query, _passage in batch]
            passages = [passage for _query, passage in batch]
            encoded = self.tokenizer(
                queries,
                passages,
                add_special_tokens=True,
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
            lengths = encoded["attention_mask"].sum(dim=1).tolist()
            if any(length > self.native_token_limit for length in lengths):
                raise ValueError(
                    "reranker query-passage pair exceeds its native token limit"
                )
            input_ids = encoded["input_ids"].tolist()
            inputs = {name: value.to("cpu") for name, value in encoded.items()}
            try:
                with self.torch.inference_mode():
                    logits = self.model(**inputs).logits.float().reshape(-1)
                scores = logits.detach().cpu().numpy().astype(np.float32, copy=False)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeError("BGE reranker inference failed") from exc
            if len(scores) != len(batch) or not np.isfinite(scores).all():
                raise ValueError("BGE reranker returned invalid raw scores")
            attention_masks = encoded["attention_mask"].tolist()
            scored.extend(
                {
                    "score": float(score),
                    "input_ids": ids,
                    "attention_mask": mask,
                    "token_count": int(length),
                }
                for score, ids, mask, length in zip(
                    scores, input_ids, attention_masks, lengths, strict=True
                )
            )
        return scored


def _load_query_cache(path, cases):
    if path is None:
        return {}, None
    sidecar = path.with_suffix(".json")
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        vectors = np.load(path, allow_pickle=False)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("query vector cache is missing or invalid") from exc
    cache_sha = digest_file(path)
    if metadata != {
        "model_revision": MODEL_REVISION,
        "dimension": 384,
        "normalization": "l2",
        "sha256": cache_sha,
    }:
        raise ValueError("query vector cache provenance mismatch")
    result = {}
    expected_keys = {hashlib.sha256(c["question"].encode()).hexdigest() for c in cases}
    if not expected_keys.issubset(vectors.files):
        raise ValueError("query vector cache does not cover every frozen question")
    for key in expected_keys:
        vector = np.asarray(vectors[key], dtype=np.float32)
        if (
            vector.shape != (384,)
            or not np.isfinite(vector).all()
            or not np.isclose(np.linalg.norm(vector), 1.0, atol=1e-4)
        ):
            raise ValueError("query vector cache contains an invalid vector")
        result[key] = vector
    vectors.close()
    return result, cache_sha


def _verify_qrel_spans(cases, snapshot):
    documents = {document.knowledge_id: document for document in snapshot.documents}
    for case in cases:
        for claim in case.get("required_claims", []):
            if not claim["evidence_alternatives"]:
                raise ValueError(
                    f"{case['case_id']}: required claim has no alternative"
                )
            for alternative in claim["evidence_alternatives"]:
                document = documents.get(alternative.get("document_id"))
                if document is None:
                    raise ValueError(
                        f"{case['case_id']}: qrel document is outside the snapshot"
                    )
                for span in alternative.get("spans", []):
                    start, end = span.get("start"), span.get("end")
                    if (
                        not isinstance(start, int)
                        or not isinstance(end, int)
                        or start < 0
                        or end <= start
                        or end > len(document.body)
                        or document.body[start:end] != span.get("text")
                    ):
                        raise ValueError(
                            f"{case['case_id']}: qrel span does not match the snapshot"
                        )


def _set_two_cpu_affinity():
    if hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity"):
        available = sorted(os.sched_getaffinity(0))
        if available:
            os.sched_setaffinity(0, available[:2])


def run_experiment(args):
    """Run frozen local retrieval in an isolated copy of the original index."""
    if not getattr(args, "execute_frozen", False):
        raise ValueError("explicit --execute-frozen authorization is required")
    if args.output.exists():
        raise ValueError("preserve existing output; use a new explicit output path")
    variant_ids = parse_variant_ids(getattr(args, "variants", None))
    use_reranker = variants_require_reranker(variant_ids)
    reranker_model = getattr(args, "reranker_model", None)
    reranker_manifest = getattr(args, "reranker_manifest", None)
    if use_reranker and (reranker_model is None or reranker_manifest is None):
        raise ValueError("BGE variants require local reranker model and manifest paths")
    qrels_raw = args.qrels.read_bytes()
    qrels = json.loads(qrels_raw)
    validate_frozen_qrels(qrels)
    cases = qrels["cases"]
    artifact_root = args.artifact_root
    artifact_manifest = json.loads(
        (artifact_root / "manifest.json").read_text(encoding="utf-8")
    )
    source = artifact_manifest["source"]
    if source.get("retrieval_spec_id") != retrieval_spec_id(DEFAULT_SPEC):
        raise ValueError("prepared vectors do not use the frozen Tiny retrieval spec")
    source_db = artifact_root / "source/documents.sqlite3"
    snapshot = DocumentContextProvider(database_path=source_db).snapshot()
    if snapshot.fingerprint != source["snapshot_fingerprint"]:
        raise ValueError("local published snapshot differs from the prepared artifact")
    _verify_qrel_spans(cases, snapshot)

    original_index = (
        artifact_root
        / "retrieval/schema-v1"
        / source["retrieval_spec_id"]
        / "index.sqlite3"
    )
    wal = Path(str(original_index) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("original vector index has an uncheckpointed WAL")
    original_index_sha = digest_file(original_index)
    query_cache, query_cache_sha = _load_query_cache(args.query_cache, cases)
    _set_two_cpu_affinity()
    tiny = TinyEmbedder(args.model)
    tiny.warmup()
    query_hashes = {
        case["case_id"]: hashlib.sha256(case["question"].encode()).hexdigest()
        for case in cases
    }
    missing_questions = {}
    for case in cases:
        key = query_hashes[case["case_id"]]
        if key not in query_cache:
            missing_questions.setdefault(key, case["question"])
    if missing_questions:
        encoded = tiny.encode_queries(list(missing_questions.values()))
        for key, vector in zip(missing_questions, encoded, strict=True):
            query_cache[key] = vector

    reranker = load_requested_reranker(
        variant_ids,
        reranker_model,
        reranker_manifest,
        batch_size=getattr(args, "reranker_batch_size", 8),
    )
    documents_by_id = {
        document.document_id: document for document in snapshot.documents
    }

    with tempfile.TemporaryDirectory(prefix="sanaebi-retrieval-v3-") as temp:
        isolated_root = Path(temp) / "retrieval"
        target = (
            isolated_root / "schema-v1" / source["retrieval_spec_id"] / "index.sqlite3"
        )
        target.parent.mkdir(parents=True)
        shutil.copyfile(original_index, target)
        repository = IndexRepository(isolated_root)
        current = repository.current_chunks(snapshot)
        if not current:
            raise ValueError("prepared vector index contains no current chunks")
        chunk_by_id = {chunk.chunk_id: chunk for chunk, _vector in current}
        matrix = np.stack([vector for _chunk, vector in current]).astype(
            np.float32, copy=False
        )
        cosine_ranked_by_case = {}
        for case in cases:
            query = query_cache[query_hashes[case["case_id"]]]
            scores = matrix @ query
            order = sorted(
                range(len(current)),
                key=lambda index: (-float(scores[index]), current[index][0].chunk_id),
            )
            cosine_ranked_by_case[case["case_id"]] = [
                (current[index][0], float(scores[index])) for index in order
            ]

        rerank_rows_by_case = {case["case_id"]: [] for case in cases}
        rerank_scores_by_case = {case["case_id"]: {} for case in cases}
        if reranker is not None:
            pair_refs = []
            pairs = []
            for case in cases:
                for tiny_rank, (chunk, _cosine) in enumerate(
                    cosine_ranked_by_case[case["case_id"]][:RERANK_CANDIDATE_COUNT],
                    start=1,
                ):
                    document = documents_by_id[chunk.document_id]
                    passage = "\n".join(
                        part
                        for part in (document.title, chunk.heading, chunk.text)
                        if part
                    )
                    pair_refs.append((case["case_id"], chunk.chunk_id, tiny_rank))
                    pairs.append((case["question"], passage))
            pair_outputs = reranker.score_pairs(pairs)
            if len(pair_outputs) != len(pair_refs):
                raise ValueError(
                    "reranker output did not cover each top-40 pair exactly once"
                )
            for (case_id, chunk_id, tiny_rank), output in zip(
                pair_refs, pair_outputs, strict=True
            ):
                cosine = next(
                    score
                    for candidate, score in cosine_ranked_by_case[case_id]
                    if candidate.chunk_id == chunk_id
                )
                rerank_scores_by_case[case_id][chunk_id] = output["score"]
                rerank_rows_by_case[case_id].append(
                    {
                        "tiny_rank": tiny_rank,
                        "chunk_id": chunk_id,
                        "cosine_score": cosine,
                        "rerank_score": output["score"],
                        "token_count": output["token_count"],
                        "input_ids": output["input_ids"],
                        "attention_mask": output["attention_mask"],
                    }
                )

        rows = []
        rankings = []
        pool_ids_by_case = {case["case_id"]: set() for case in cases}
        for case in cases:
            case_id = case["case_id"]
            ranked = cosine_ranked_by_case[case_id]
            cosine_by_id = {chunk.chunk_id: score for chunk, score in ranked}
            rerank_by_id = rerank_scores_by_case[case_id]
            cosine_ranking = [
                {
                    "rank": rank,
                    "chunk_id": chunk.chunk_id,
                    "document_id": documents_by_id[chunk.document_id].knowledge_id,
                    "revision_id": chunk.revision_id,
                    "spans": [asdict(span) for span in chunk.spans],
                    "cosine_score": score,
                }
                for rank, (chunk, score) in enumerate(ranked, start=1)
            ]
            reranked = sorted(
                [
                    (chunk_by_id[item["chunk_id"]], item["rerank_score"])
                    for item in rerank_rows_by_case[case_id]
                ],
                key=lambda item: (-item[1], item[0].chunk_id),
            )
            bge_ranking = [
                {
                    "rank": rank,
                    "chunk_id": chunk.chunk_id,
                    "document_id": documents_by_id[chunk.document_id].knowledge_id,
                    "revision_id": chunk.revision_id,
                    "spans": [asdict(span) for span in chunk.spans],
                    "cosine_score": cosine_by_id[chunk.chunk_id],
                    "rerank_score": score,
                }
                for rank, (chunk, score) in enumerate(reranked, start=1)
            ]
            rankings.append(
                {
                    "case_id": case_id,
                    "ranking_id": "tiny_cosine",
                    "items": cosine_ranking,
                }
            )
            if reranker is not None:
                rankings.append(
                    {
                        "case_id": case_id,
                        "ranking_id": "bge_top40",
                        "items": bge_ranking,
                    }
                )
            for variant_id in variant_ids:
                start_time = time.perf_counter()
                selected = select_variant_evidence(
                    variant_id,
                    ranked,
                    snapshot,
                    tiny.tokenizer,
                    current_chunks=[chunk for chunk, _vector in current],
                    reranked=reranked if variant_id.startswith("bge_rerank_") else None,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                evidence = [
                    score_evidence(item, cosine_by_id, rerank_by_id)
                    for item in selected
                ]
                selected_ids = {
                    chunk_id for item in selected for chunk_id in item.chunk_ids
                }
                pool_ids_by_case[case_id].update(selected_ids)
                if variant_id == "baseline":
                    candidate_count = min(10, len(ranked))
                elif variant_id in {"A_existing", "B_tokens_only", "C_unlimited"}:
                    candidate_count = sum(
                        score >= COSINE_THRESHOLD for _chunk, score in ranked
                    )
                elif variant_id.startswith("adjacent_"):
                    candidate_count = min(
                        int(variant_id.removeprefix("adjacent_top")), len(ranked)
                    )
                elif variant_id.startswith("bge_rerank_"):
                    candidate_count = min(RERANK_CANDIDATE_COUNT, len(ranked))
                else:
                    candidate_count = min(
                        int(variant_id.removeprefix("adjacent_top")), len(ranked)
                    )
                rows.append(
                    {
                        "case_id": case_id,
                        "variant_id": variant_id,
                        "candidate_count": candidate_count,
                        "selected_count": len(evidence),
                        "selection_ms": elapsed_ms,
                        "evidence": evidence,
                    }
                )
            pool_ids_by_case[case_id].update(
                item["chunk_id"] for item in cosine_ranking[:RERANK_CANDIDATE_COUNT]
            )
            if "C_unlimited" not in variant_ids:
                c_selection = select_variant_evidence(
                    "C_unlimited", ranked, snapshot, tiny.tokenizer
                )
                pool_ids_by_case[case_id].update(
                    chunk_id for item in c_selection for chunk_id in item.chunk_ids
                )

        packet = make_relevance_packet(
            cases, chunk_by_id, documents_by_id, pool_ids_by_case
        )
        if digest_file(original_index) != original_index_sha:
            raise ValueError("original vector index changed during the experiment")

    query_vectors = {
        query_hashes[case["case_id"]]: query_cache[query_hashes[case["case_id"]]]
        for case in cases
    }
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.stage-", dir=output.parent
    ) as stage_dir:
        stage = Path(stage_dir)
        vector_path = stage / "query-vectors.npz"
        np.savez(vector_path, **query_vectors)
        (stage / "query-vectors.json").write_text(
            json.dumps(
                {
                    "model_revision": MODEL_REVISION,
                    "dimension": 384,
                    "normalization": "l2",
                    "sha256": digest_file(vector_path),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        rerank_file = stage / "rerank-scores.json"
        rerank_file.write_text(
            json.dumps(
                {
                    "enabled": reranker is not None,
                    "model_id": BGE_MODEL_ID if reranker is not None else None,
                    "revision": BGE_REVISION if reranker is not None else None,
                    "native_token_limit": (
                        reranker.native_token_limit if reranker is not None else None
                    ),
                    "score_semantics": (
                        "raw_single_logit_fp32" if reranker is not None else "not_run"
                    ),
                    "input_ids_include_padding": True,
                    "cases": rerank_rows_by_case if reranker is not None else {},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        packet_path = stage / "relevance-packet.json"
        packet_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        search_path = stage / "search.json"
        search_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "snapshot_fingerprint": snapshot.fingerprint,
                    "qrels_sha256": hashlib.sha256(qrels_raw).hexdigest(),
                    "source_index_sha256": original_index_sha,
                    "retrieval_spec_id": source["retrieval_spec_id"],
                    "tiny_model_revision": MODEL_REVISION,
                    "reranker_model_id": BGE_MODEL_ID if reranker is not None else None,
                    "reranker_revision": BGE_REVISION if reranker is not None else None,
                    "reranker_manifest_sha256": (
                        digest_file(reranker_manifest) if reranker is not None else None
                    ),
                    "reranker_files_sha256": (
                        reranker.file_hashes if reranker is not None else {}
                    ),
                    "variant_ids": variant_ids,
                    "query_cache_sha256": query_cache_sha,
                    "query_vectors_sha256": digest_file(vector_path),
                    "rerank_scores_sha256": digest_file(rerank_file),
                    "relevance_packet_sha256": digest_file(packet_path),
                    "rows": rows,
                    "rankings": rankings,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (stage / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "qrels_sha256": hashlib.sha256(qrels_raw).hexdigest(),
                    "snapshot_fingerprint": snapshot.fingerprint,
                    "source_database_sha256": digest_file(source_db),
                    "source_index_sha256": original_index_sha,
                    "query_cache_sha256": query_cache_sha,
                    "query_vectors_sha256": digest_file(vector_path),
                    "reranker_manifest_sha256": (
                        digest_file(reranker_manifest) if reranker is not None else None
                    ),
                    "reranker_files_sha256": (
                        reranker.file_hashes if reranker is not None else {}
                    ),
                    "search_sha256": digest_file(search_path),
                    "rerank_scores_sha256": digest_file(rerank_file),
                    "relevance_packet_sha256": digest_file(packet_path),
                    "model_revision": MODEL_REVISION,
                    "reranker_revision": (
                        BGE_REVISION if reranker is not None else None
                    ),
                    "variant_ids": variant_ids,
                    "code_commit": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if output.exists():
            raise ValueError("output appeared during execution; preserving it")
        os.replace(stage, output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reranker-model", type=Path)
    parser.add_argument("--reranker-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", metavar="VARIANT")
    parser.add_argument("--query-cache", type=Path)
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument(
        "--execute-frozen",
        action="store_true",
        help="authorize local model execution against already-frozen qrels",
    )
    args = parser.parse_args(argv)
    if not args.execute_frozen:
        parser.error("--execute-frozen is required to run model inference")
    try:
        args.variants = parse_variant_ids(args.variants)
    except ValueError as exc:
        parser.error(str(exc))
    if variants_require_reranker(args.variants) and (
        args.reranker_model is None or args.reranker_manifest is None
    ):
        parser.error("BGE variants require --reranker-model and --reranker-manifest")
    run_experiment(args)


if __name__ == "__main__":
    main()
