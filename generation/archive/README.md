# 보관된 프롬프트 프로필

현재 활성 프로필은 `examples_answer_scope_v5`와 `examples_answer_scope_v5_rag_service_v1`이다.
`prompt_profiles.json`의 14개 프로필은 이전 기준점·대체 후보·미채택 v6/v7의 정확한 추가 본문을 보존한다. 새 실행 구성으로 권장하지 않는다.

과거 평가 재현을 위해 `build_profile_prompt`에 이름을 명시하면 지연 로드한다. 원응답·실험 설정·평가 판정은 변경하지 않는다. 공통 본문은 `generation/prompts.py`를 사용한다.
