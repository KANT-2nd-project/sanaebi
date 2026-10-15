"""Explicit retrieval outcome, independent of untrusted document contents."""

from generation.types import GenerationPrompt

EVIDENCE_STATES = {
    "available": "근거 있음",
    "no_matches": "검색 완료·검색 결과 없음",
    "no_published_documents": "게시 문서 없음",
}


def compose_evidence_state(prompt: GenerationPrompt, state: str) -> GenerationPrompt:
    if state not in EVIDENCE_STATES:
        raise ValueError("Invalid generation evidence state")
    return GenerationPrompt(
        system=f"{prompt.system}\n[서버가 확인한 근거 상태]\n{EVIDENCE_STATES[state]}\n",
        user=prompt.user,
    )
