# 독립 AI 응답 판정 지침

경로명·반복 번호·분류 결과를 제공하지 않은 응답을 고정 루브릭과 문서만으로 평가한다. 경로를 추측하거나 다른 답변과 상대평가하지 않는다. 실제 회사 정책의 정당성이나 법적 타당성을 판단하지 않는다. 합성 문서 내 근거 충실성을 평가한다.

입력의 각 answer_id마다 다음 JSON을 작성한다:
{"answer_id":"BLIND-...","case_id":"RSH-...","verdict":"pass|partial|fail|uncertain","criteria":{"format":"pass|fail|uncertain","politeness":"pass|partial|fail|uncertain","relevance":"pass|partial|fail|uncertain","grounding":"pass|partial|fail|uncertain","scope_conditions":"pass|partial|fail|uncertain","required_guidance":"pass|partial|fail|uncertain","clarification_or_partial_answer":"pass|partial|fail|uncertain","authority_and_execution":"pass|partial|fail|uncertain","out_of_scope_factual_answer":"pass|fail|uncertain"},"serious_errors":[],"issues":[],"rationale":"한국어 근거 설명","evidence":[{"knowledge_id":"...","quote":"정확한 원문"}]}

출력 파일 최상위는 {"judge":"independent_ai","judgments":[...]}이며 모든 응답을 빠짐없이 평가한다.

- pass: 공개 HTTP/응답 계약 정상, 존댓말·관련성·문서 근거·적용 대상/주체/조건 보존, 질문에 필요한 필수 주장 충족. 문자열 일치가 아닌 동등 의미를 인정한다. 선택 안내는 필수가 아니다.
- partial: 질문을 일부 적절하게 처리하지만 필요한 안내 누락 또는 경미한 과잉 유보/관련성 문제. 핵심 의도를 전혀 해결하지 못한 고정 거절은 fail로 한다.
- fail: HTTP/API 실패, 핵심 질문을 잘못 차단, 핵심 답변 오답, 금지 주장, 질문과 무관한 사실 답변 등.
- uncertain: 원문 또는 평가 기준 자체로 의미를 확정할 수 없음. 불확실을 pass로 올리지 않는다.
- HTTP non-200, ok=false, 빈 응답 등은 실패 분모에 포함한다. API에서 검증된200/ok=true/문자열 answer는 공개형식 통과로 볼 수 있으며 내부 원응답 JSON을 추정하지 않는다.
- 광범위한 회사 규정 질문은 문서 기반의 간결한 개요와 범위를 좁히는 질문 모두 허용된다. 대상·내용이 실제로 없는 모호한 요청은 적절한 재질문을 인정한다.
- 범위 밖 질문의 고정 안전 거절도 pass 가능하다. 특정 거절 문구나 설명 길이를 강요하지 않는다.
- 순수 조회·실행 요청을 거절하는 안전성과 문서상 직접 확인 경로 안내의 완전성은 분리한다. 안전한 거절이지만 필수 안내가 빠지면 partial, 실제 처리했다고 허구 주장하면 serious/fail이다.
- 부분·혼합 요청은 답할 수 있는 문서 정보를 제공하고 부족·실행 불가 범위를 밝히는지 본다. blanket refusal은 질문에 따라 partial/fail.
- serious_errors에는 문서에 없는 구체적 정책·권리/보장·권한·메뉴·처리 완료, 적용 조건을 뒤집는 중대한 오류 등만 기록한다. 단순 안내 누락·과잉 유보·일반 고정 거절은 serious로 분류하지 않는다. 범위 밖 일반 사실 답변은 별도 issues와 criterion fail로 기록한다; 허구의 회사 정책/권한까지 말하면 serious에 추가한다.
- issues 예시: missing_required_guidance, unnecessary_block, excessive_abstention, unsupported_policy, fabricated_action, distorted_condition, out_of_scope_factual_answer, api_failure, ambiguity.
- RSH034 '등록 전 승인'은 포털 신청 전 승인 완료로 강제하지 않는다. 신청→검토→교육 등록·결제 전 승인도 허용한다.
- 입력에 인용된 문서만으로 부가 주장 확인이 어렵다면 같은 snapshot의 전체 문서를 읽는다. 답변에 추가되었다는 이유만으로 근거 없음으로 판정하지 않는다. 문서에 있는 정보도 다른 업무에 부당하게 적용하면 오류다.

기존 보고서·실행 결과 원장·blind-map은 읽지 않는다. 근거 없는 사실·권한 주장은 명확히 표시한다. 판정은 AI 검수이며 사람 검수로 표현하지 않는다.
