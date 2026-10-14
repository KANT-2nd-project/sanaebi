"""answer_pipeline 테스트 공통 준비물. 모든 테스트는 모델을 부르지 않는다 (비용·네트워크 없음).

케이스와 기록은 요청 처리 경로(SEARCH_KNOWLEDGE·CLARIFY·UNSUPPORTED)와 회사 문서 전체를
프롬프트에 넣는 답변 설계(docs/service-architecture.md)를 따르는 테스트용 가상 데이터다.
실제 실행 기록이나 실제 회사 규정이 아니다.
"""

import json

from answer_pipeline.run import ModelConfig, make_record

LEAVE_DOC = {
    "document_id": "1",
    "title": "[예시] 연차 신청",
    "text": "연차는 그루에서 잔여 일수를 확인하고 사용 3일 전까지 신청한다. "
    "팀장 승인 알림을 받은 뒤 일정을 공유한다.",
}
ROOM_DOC = {
    "document_id": "2",
    "title": "[예시] 회의실 예약",
    "text": "회의실은 온오피스에서 예약한다. 예약이 겹치면 예약 번호를 오피스운영에 전달한다.",
}
DOCUMENTS = {
    doc["document_id"]: {"title": doc["title"], "text": doc["text"]}
    for doc in (LEAVE_DOC, ROOM_DOC)
}
GOOD_ANSWER_TEXT = "그루에서 잔여 일수를 확인하고 사용 3일 전까지 신청하세요."
CONFIGS = {
    "ollama": ModelConfig(name="local", provider="ollama"),
    "openai": ModelConfig(name="cloud", provider="openai"),
}
CONDITIONS = {"num_ctx": 4096, "max_output_tokens": 512}


def build_prompt(question, documents):
    """실행기 프롬프트와 같은 모양의 테스트용 프롬프트 (문서는 제목·내용, 질문은 원문)."""
    lines = ["출력은 JSON 객체 하나이며 필드는 text뿐이다."]
    lines += [
        f"제목: {doc['title']}\n내용: {doc['text']}" for doc in documents.values()
    ]
    lines.append(f"<사용자 질문>\n{question}\n</사용자 질문>")
    return "\n".join(lines)


def answer(text):
    return json.dumps({"text": text}, ensure_ascii=False)


def case(
    case_id="dev-hr-01",
    question="연차는 어디서 신청해요?",
    expected_route="SEARCH_KNOWLEDGE",
    expected_document_ids=("1",),
    required_points=("그루",),
    forbidden_claims=(),
    question_type="answerable",
    topic="people",
):
    """load_eval_set이 돌려주는 모양의 평가 질문."""
    return {
        "id": case_id,
        "question": question,
        "split": "dev",
        "expected_route": expected_route,
        "expected_document_ids": None
        if expected_document_ids is None
        else list(expected_document_ids),
        "required_points": list(required_points),
        "forbidden_claims": list(forbidden_claims),
        "topic": topic,
        "question_type": question_type,
        "evidence_position": None,
        "note": "",
    }


def unsupported_case(case_id="dev-unsupported-01", **overrides):
    values = {
        "question": "내 연차 며칠 남았어?",
        "expected_route": "UNSUPPORTED",
        "expected_document_ids": None,
        "required_points": (),
        "question_type": None,
    }
    values.update(overrides)
    return case(case_id, **values)


def generated(test_case, provider="openai", text=None, documents=None, **overrides):
    """runner.run_case가 돌려주는 모양의 성공 결과."""
    documents = DOCUMENTS if documents is None else documents
    if test_case["expected_route"] != "SEARCH_KNOWLEDGE":
        documents = {}
    result = {
        "llm_called": True,
        "prompt": build_prompt(test_case["question"], documents),
        "response_text": answer(GOOD_ANSWER_TEXT) if text is None else text,
        "executor_output": None,
        "usage": {"input_tokens": 500, "output_tokens": 40},
        "generation_complete": True,
        "finish_reason": "stop",
        "served_model": f"test-{provider}",
        "latency_seconds": 1.0,
        "error": None,
    }
    result.update(overrides)
    return result


def llm_record(
    test_case=None, provider="openai", repeat=1, text=None, documents=None, **overrides
):
    """실행 기록. documents를 주면 그 문서만 프롬프트와 evidence에 들어간다."""
    test_case = test_case or case()
    documents = DOCUMENTS if documents is None else documents
    result = generated(test_case, provider, text, documents, **overrides)
    conditions = {"model": f"test-{provider}", **CONDITIONS}
    return make_record(
        test_case,
        CONFIGS[provider],
        conditions,
        repeat,
        result,
        documents,
        cold_start=False,
    )


def no_llm_record(test_case, provider="openai"):
    """실행기가 LLM을 부르지 않고 끝낸 기록 (고정 안내 경로)."""
    return llm_record(
        test_case,
        provider,
        llm_called=False,
        prompt=None,
        response_text="",
        usage={"input_tokens": None, "output_tokens": None},
        finish_reason=None,
        served_model=None,
    )


def good():
    """모든 단계가 정상인 openai 기록."""
    return llm_record()


def human(
    grounded=2, citation=2, relevance=2, handling=2, points=2, clarity=2, *critical
):
    """scoring.load_human_scores가 돌려주는 모양의 채점 1건."""
    return {
        "scores": {
            "grounded": grounded,
            "citation": citation,
            "relevance": relevance,
            "handling": handling,
            "required_points": points,
            "clarity": clarity,
        },
        "critical": list(critical),
    }
