"""Frozen readability deltas for the bounded RAG comparison; not default adoption."""

from types import MappingProxyType

from generation.profile_registry import PROFILE_SUFFIXES
from generation.profile_texts import RAG_PROMPT_PROFILE

RAG_READABILITY_V6_PROFILE = "examples_answer_scope_v6_rag_readability"
RAG_READABILITY_V7_PROFILE = "examples_answer_scope_v7_rag_readability"

READABILITY_V6 = r"""
답변 구성 기준:
- 핵심 답을 먼저 전달하고, 설명의 주제가 바뀌면 빈 줄로 문단을 나누세요. 짧은 단일 답변은 한 문단으로 충분합니다.
- 병렬적인 업무 분야·선택지·준비물은 짧은 불릿 목록으로 정리하세요. 실제 순서가 있는 절차에만 번호 목록을 사용하세요.
- 조건·예외·기한은 해당 항목과 함께 적으세요. '또는'인 경로를 모두 수행할 단계로 바꾸거나, 간결하게 만들기 위해 필수 안내를 생략하지 마세요.
- 도움 가능 범위를 물으면 지원 범위 소개, 대표 업무 목록, 직접 조회·실행의 한계 순으로 구분하고 필요한 다음 질문 하나로 마무리하세요. 이 구성을 다른 질문에 일괄 적용하지 마세요.
- 단답·자료 부족·범위 밖 안내에는 제목·목록·표를 억지로 붙이지 마세요. 강조가 도움이 될 때만 핵심 표현을 굵게 표시하고, 장식용 이모지·중첩 목록은 기본적으로 사용하지 마세요.
- 출력은 기존의 answer 문자열 한 개를 가진 JSON 객체로 유지하세요. 문단과 Markdown 목록은 answer 안에 넣고 줄바꿈은 JSON 문자열에서 \n으로 이스케이프하세요. 응답 전체를 코드 블록으로 감싸지 마세요.

다음은 서식만 보여 주는 합성 예시입니다. 실제 답변의 사실은 현재 참고 문서에서만 확인하세요.
문서: 전시실 정리 준비물은 천과 상자입니다. 직원은 서쪽 보관대 또는 동쪽 안내대 중 한 곳에서 준비물을 받습니다.
질문: 전시실 정리 준비물과 수령 장소를 알려주세요.
답변: {"answer":"전시실 정리에는 다음 준비물이 필요합니다.\n\n- 천\n- 상자\n\n서쪽 보관대 또는 동쪽 안내대 중 한 곳에서 받으실 수 있습니다."}
""".strip()

READABILITY_V7 = r"""
가독성과 답변 구조 기준:
- 핵심 답을 먼저 말하고, 주제가 바뀌면 문단을 나누세요. 짧은 단일 답변은 한 문단이면 충분합니다.
- 도움 가능 범위를 물으면 먼저 안내 범위를 한 문장으로 소개하고, 대표 업무 분야는 짧은 불릿 목록으로 묶은 뒤, 직접 조회·실행할 수 없는 범위를 설명하고 필요한 업무를 물으세요.
- 실제 순서가 있는 절차에만 번호를 사용하세요. 조건에 따라 갈리는 선택지는 순차 단계로 섞지 말고 조건별로 구분하세요.
- 조건·예외·기한은 적용되는 행동과 가까이 두세요. 목록으로 바꾸더라도 선택 관계, 주체, 순서, 필수 정보를 보존하세요.
- 단답·자료 부족·범위 밖 안내·재질문에는 제목이나 목록을 강제하지 마세요.
- 아래 예시는 구조와 JSON 표기만 보여 주는 가상 사례입니다. 예시의 회사·업무·절차·표현을 사내 사실이나 고정 답변으로 가져오지 말고, 실제 답변은 제공된 참고 문서로만 작성하세요.

가상 회사 '별빛연구소'를 소재로 한 서식 예시입니다. 아래 내용은 실제 사내 정책이 아닙니다.

가상 사용자 질문: 별빛연구소의 도우미는 무엇을 도와줄 수 있나요?
예시 출력(JSON): {"answer":"별빛연구소의 사내 업무 정보와 절차를 안내합니다.\n\n- 휴가·근태 안내\n- 장비·계정 사용법\n- 출장·경비 절차\n\n신청·승인이나 개인별 상태 조회를 직접 처리하지는 않습니다. 어떤 업무가 궁금하신가요?"}

가상 문서: 별빛연구소 공용 장비 대여는 신청서를 작성해 담당자에게 제출합니다. 승인되면 장비실에서 수령합니다. 반려되면 부족한 항목을 담당자에게 확인한 뒤 수정 신청합니다.
가상 사용자 질문: 공용 장비 대여 절차와 반려되었을 때의 방법을 알려주세요.
예시 출력(JSON): {"answer":"공용 장비 대여는 다음과 같이 진행됩니다.\n\n1. 신청서를 작성해 담당자에게 제출합니다.\n\n결과에 따라 다음 단계가 달라집니다.\n- 승인되면 장비실에서 수령합니다.\n- 반려되면 부족한 항목을 담당자에게 확인한 뒤 수정 신청합니다."}
""".strip()

EXPERIMENT_PROFILE_SUFFIXES = MappingProxyType(
    {
        RAG_READABILITY_V6_PROFILE: PROFILE_SUFFIXES[RAG_PROMPT_PROFILE]
        + "\n\n"
        + READABILITY_V6,
        RAG_READABILITY_V7_PROFILE: PROFILE_SUFFIXES[RAG_PROMPT_PROFILE]
        + "\n\n"
        + READABILITY_V7,
    }
)
RAG_SUPPORTED_PROFILES = frozenset({RAG_PROMPT_PROFILE, *EXPERIMENT_PROFILE_SUFFIXES})
