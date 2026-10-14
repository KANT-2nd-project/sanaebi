from dataclasses import dataclass

from generation.config import GenerationConfig
from generation.types import GenerationResult


@dataclass(frozen=True)
class GenerationRun:
    case_id: str
    config: GenerationConfig
    result: GenerationResult | None
    elapsed_seconds: float
    error_type: str | None = None
