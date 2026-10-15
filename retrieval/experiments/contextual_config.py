"""Retrieval contract used only by the historical heading-context experiment."""

from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.config import RetrievalSpec


@dataclass(frozen=True)
class ContextualRetrievalSpec(RetrievalSpec):
    chunker_version: str = "markdown-source-spans-v2-embedding-context"
    embedding_context_tokens: int = 60
    context_before_tokens: int = 30
    context_after_tokens: int = 30

    def to_dict(self) -> dict:
        value = super().to_dict()
        value["embedding_context"] = {
            "max_tokens": self.embedding_context_tokens,
            "before_tokens": self.context_before_tokens,
            "after_tokens": self.context_after_tokens,
        }
        return value


CONTEXTUAL_SPEC = ContextualRetrievalSpec()
