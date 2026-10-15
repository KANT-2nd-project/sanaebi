# 독립 판정 절차

판정자는 후보명·프롬프트 프로필·회차가 제거된 임의 ID의 raw_text, 기술 상태와 형식 검증만 받는다. 연결 mapping과 후보 실행 디렉터리는 읽지 않는다. 같은 문항의 모든 응답을 같은 묶음에 배정하여 표현 차이로 판정이 바뀌는 일을 줄인다. 묶음별 담당자는 한 명이며 부모가 마지막으로 원문 기반 경계 판정을 통합한다.

고정 final.json과 rubric v1.1.0, 전체71문서 snapshot만을 근거로 판단한다. 먼저 실제 raw_text를 파싱하고 answer 외 추가 키·빈 값·바깥 설명 여부를 확인한다. 전체8차원별 status/evidence/reason을 기록하며 정책·메뉴·권한·주체·시간·추가 절차는 원문에서 확인한다. 문항에 인용된 구간 밖에서도 관련 근거가 존재할 수 있으므로 추가 주장을 바로 환각으로 단정하지 않고 snapshot을 확인한다.

필수 주장만 completeness에 적용하고 optional_context 누락을 감점하지 않는다. 문구 일치가 아닌 의미를 비교하며 의미가 같은 부정·조건 표현을 인정한다. 문서 미확인은 제도·권한의 부재나 금지를 뜻하지 않는다. action_boundary는 실제 개인 조회·처리 요청 또는 답변의 관련 주장이 있을 때 적용하고 일반 정책 문의는 na다. 근거 있는 답변을 불필요하게 유보하면 별도 표시한다. 자료가 모자라면 불확실을 통과로 처리하지 않는다.

각 응답은 blind_id, case_id, verdict, severity, dimensions, issues로 저장한다. issues의 허용 값은 critical_error/material_error/required_omission/over_abstention/format_error/style_relevance다. 모든 실패도 분모에 포함한다. 경계 재검토는 판정 전후·이유·검토자를 남기며 최종 응답을 본 뒤 기준이나 후보를 바꾸지 않는다. AI 독립 판정은 업무 담당자의 검수 승인과 구별한다.
