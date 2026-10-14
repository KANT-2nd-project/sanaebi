"""Generate one answer from an explicit exported document file."""

import argparse
import json
from pathlib import Path

from generation.config import GenerationConfig, GenerationProvider
from generation.documents import load_documents
from generation.providers import build_model_call
from generation.service import generate_from_documents
from generation.types import GenerationStatus


def main() -> int:
    parser = argparse.ArgumentParser(description="사내비 문서 기반 답변 생성")
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--provider", choices=[p.value for p in GenerationProvider], required=True
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    question = args.question.strip()
    if not question:
        parser.error("--question은 비어 있을 수 없습니다.")

    config = GenerationConfig(
        provider=GenerationProvider(args.provider),
        model_name=args.model,
        timeout_seconds=args.timeout,
    )
    documents = load_documents(args.documents)
    model_call = build_model_call(config)
    result = generate_from_documents(question, documents, model_call)
    print(
        json.dumps(
            {
                "status": result.status.value,
                "answer": result.answer,
                "raw_text": result.raw_text,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.status is GenerationStatus.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
