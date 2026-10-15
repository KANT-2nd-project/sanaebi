from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType

import numpy as np

from app.documents.context import DocumentContext, DocumentContextSnapshot


class RetrievalTestCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp_path = Path(temporary.name)


@dataclass(frozen=True)
class Tokenized:
    input_ids: list[int]
    offset_mapping: list[tuple[int, int]]


class WordTokenizer:
    """Small deterministic tokenizer with Hugging Face's offset API shape."""

    def __call__(
        self, text, *, add_special_tokens=False, return_offsets_mapping=False, **_
    ):
        offsets = [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
        result = {"input_ids": list(range(1, len(offsets) + 1))}
        if return_offsets_mapping:
            result["offset_mapping"] = offsets
        return result

    def encode(self, text, *, add_special_tokens=False):
        return self(text, add_special_tokens=add_special_tokens)["input_ids"]


class FakeEmbedder:
    def __init__(self):
        self.tokenizer = WordTokenizer()
        self.document_batches: list[tuple[str, ...]] = []
        self.query_batches: list[tuple[str, ...]] = []

    def encode_documents(self, texts):
        self.document_batches.append(tuple(texts))
        return np.stack([self._vector(text) for text in texts])

    def encode_queries(self, texts):
        self.query_batches.append(tuple(texts))
        return np.stack([self._vector(text) for text in texts])

    @staticmethod
    def _vector(text):
        vector = np.zeros(384, dtype=np.float32)
        for token in text.casefold().split():
            vector[sum(token.encode("utf-8")) % len(vector)] += 1
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector


def make_document(
    *,
    document_id="db-document-1",
    knowledge_id="ieum-001",
    revision_id="revision-1",
    revision=1,
    title="휴가 신청",
    body="예정된 휴가는 포털에서 신청한다.",
    source_reference="document:ieum-001",
):
    return DocumentContext(
        document_id=document_id,
        knowledge_id=knowledge_id,
        revision_id=revision_id,
        revision=revision,
        title=title,
        body=body,
        source_reference=source_reference,
        content_hash="unused-context-hash",
        metadata=MappingProxyType({}),
    )


def make_snapshot(*documents):
    return DocumentContextSnapshot(tuple(documents))
