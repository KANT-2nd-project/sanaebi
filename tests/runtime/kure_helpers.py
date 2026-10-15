"""Deterministic model substitute for KURE runtime lifecycle tests."""

import numpy as np

from app.retrieval.config import KURE_SPEC
from tests.retrieval.helpers import FakeEmbedder


class KureFakeEmbedder(FakeEmbedder):
    spec = KURE_SPEC

    def __init__(self):
        super().__init__()
        self.splitter_tokenizer = self.tokenizer

    @staticmethod
    def _vector(text):
        vector = np.zeros(1024, dtype=np.float32)
        for token in text.casefold().split():
            vector[sum(token.encode("utf-8")) % len(vector)] += 1
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector
