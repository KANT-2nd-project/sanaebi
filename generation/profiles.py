"""Composable prompt profiles for controlled generation experiments."""

from generation.prompts import build_prompt
from generation.types import GenerationPrompt

_CONCISE_RULES = """

추가 답변 기준:
- 질문과 같은 업무·대상에 적용되는 문서 내용만 사용하고, 다른 업무의 절차를 가져오지 마세요.
- 문서의 행위 주체, 적용 범위, 순서, 시간 기준점, 조건과 예외를 그대로 보존하세요.
- 담당자가 기록한다는 사실만으로 질문자의 조회 권한이나 조회 경로를 추정하지 마세요.
- 문의 창구를 실제 처리 메뉴나 처리 절차로 바꾸지 마세요.
- 질문에 필요한 내용만 답하고, 문서에 없는 메뉴·권한·순서·증빙 조건을 추가하지 마세요.
- 질문의 전제가 문서와 다르면 문서에 맞게 바로잡고, 확인할 수 없는 점은 분명히 구분하세요.
""".strip()

_SYNTHETIC_EXAMPLES = """

다음은 판단 방식만 보여 주는 합성 예시입니다. 예시의 정책이나 이름은 실제 사내 정책이 아니며,
실제 답변의 사실은 현재 제공된 참고 문서에서만 확인하세요.

예시 1 — 기록과 조회 권한
문서: 담당자는 처리 결과를 내부 기록에 남깁니다.
질문: 제가 그 기록을 포털에서 직접 볼 수 있나요?
답변: 문서에는 담당자의 기록 의무만 있고, 질문자의 조회 권한이나 경로는 안내되어 있지 않습니다.

문서: 직원은 [예시 메뉴] > [예시 요청]에서 접수 상태를 조회할 수 있습니다.
질문: 접수 상태는 어디에서 확인하나요?
답변: [예시 메뉴] > [예시 요청]에서 확인할 수 있습니다.

예시 2 — 개인 교육과 외부 강사 등록
문서: 직원 개인 교육비 신청은 [개인 학습 절차]에 따라 접수합니다.
질문: 외부 강사 등록 절차는 무엇인가요?
답변: 해당 문서는 직원 개인 교육비 신청만 설명하므로, 외부 강사 등록 방법은 확인할 수 없습니다.

문서: 외부 강사 등록은 [강사 등록 절차]에 따라 담당자가 처리합니다.
질문: 외부 강사 등록 절차는 무엇인가요?
답변: 문서에 명시된 [강사 등록 절차]를 안내합니다. 추가 승인이나 입력 항목은 문서에 없으면 덧붙이지 않습니다.

예시 3 — AND 조건과 예외
문서: 조건 X와 조건 Y가 모두 충족되어야 신청할 수 있습니다.
질문: 조건 X는 확인됐고 Y는 확인하지 못했는데 신청할 수 있나요?
답변: 문서는 X와 Y의 동시 충족을 요구합니다. Y가 확인되지 않아 요건 충족 여부를 판단할 수 없습니다.

문서: 조건 X와 조건 Y가 모두 충족되어야 신청할 수 있습니다.
질문: 조건 X와 Y가 모두 충족됐습니다. 문서상 요건이 되나요?
답변: 문서에 적힌 두 조건은 모두 충족됐습니다. 별도의 신청 경로나 예외는 문서에 명시된 경우에만 안내합니다.
""".strip()


_PROFILE_SUFFIXES = {
    "baseline": "",
    "concise": _CONCISE_RULES,
    "examples": f"{_CONCISE_RULES}\n\n{_SYNTHETIC_EXAMPLES}",
}


def build_profile_prompt(
    question: str,
    documents: list[str],
    profile: str = "baseline",
) -> GenerationPrompt:
    """Build a named prompt profile while preserving the baseline unchanged."""
    try:
        suffix = _PROFILE_SUFFIXES[profile]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"알 수 없는 프롬프트 프로필입니다: {profile!r}") from exc

    prompt = build_prompt(question, documents)
    if not suffix:
        return prompt

    return GenerationPrompt(
        system=f"{prompt.system.rstrip()}\n\n{suffix}\n",
        user=prompt.user,
    )
