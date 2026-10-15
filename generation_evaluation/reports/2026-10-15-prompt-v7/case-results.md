# 복구한 문항별 응답·판정·근거

답변 본문과 판정은 세션 로그에서 복구했다. 익명 매핑은 고정 실행 순서와 기록된 seed로 재구성했다. 원 provider JSON·호출별 토큰·시간 파일은 소실되어 이 문서에 임의 생성하지 않는다. 복구 출처와 한계는 recovery/ 자료를 따른다.

## development

### R01 — 너는 뭘 도와줄 수 있어?

**필수 기준**

1. Introduce Sanaebi as an assistant for Ieumworks internal work information, rules/procedures, and company-documented work tools.
2. Name several representative supported areas grounded in the company roles, such as leave/attendance, travel/expenses, accounts/permissions/tools, security/privacy, customer support/development.
3. State that it does not directly submit/change/cancel/approve requests or look up an individual's live status.
4. Invite the user to name the work topic they need help with.

**근거**

- ieum-053: 이음웍스는 업무·협업 SaaS를 만드는 회사다. 구성원은 팀 업무와 자료를 관리하고, 팀장은 팀의 일정·승인·업무 인계와 담당자 연결에 책임을 진다.
- ieum-053: | People팀 | 입사·이동·퇴사, 휴가·근태, 회사 제도, 성장·교육 기록, 일반 상담·신고 접수 |
- ieum-053: | 재무팀 | 구매·출장·경비·법인카드·비용 증빙과 지급 |
- ieum-053: | IT운영팀 | 회사 계정·기기·시스템 권한·업무 도구의 기술 처리 |
- ieum-053: | 보안·개인정보 담당자 | 정보 등급, 개인정보 처리 검토, 보안 사고 대응과 보호 조치 |
- ieum-053: | 고객지원팀 | 고객 문의 접수, 사실 확인, 고객에게 진행 상황 안내, 담당 팀 인계 |
- ieum-053: | 제품개발팀 | SaaS 기능·코드·결함·기술 변경과 서비스 복구 |
- generation/prompts.py: 사내비는 제공된 문서를 바탕으로 정보를 안내하며, 실제 신청·변경·취소·승인이나 개인별 상태 조회를 수행하지 않습니다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 partial / 중대한 오류 False

이음웍스의 사내 업무 정보·규정·절차와 문서에 설명된 업무 도구 사용법을 안내해 드릴 수 있습니다. 예를 들어 휴가·근태, 출장·경비, 계정·권한, 자료 공유·보안, 고객 문의·장애 대응 등을 도와드립니다. 다만 신청·변경·취소·승인이나 개인별 상태 조회를 직접 수행하지는 않습니다. 궁금하신 업무를 말씀해 주세요.

판정: 범위·대표 업무·직접 처리 한계·초대는 충족. 병렬 업무 영역을 요청된 compact bullet list 대신 인라인 예시로 제시함.


복구 ID: development-A032; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 partial / 중대한 오류 False

이음웍스의 사내 업무 규정과 절차, 문서에 설명된 업무 도구 사용법을 안내해 드릴 수 있습니다. 예를 들어 휴가·근태, 구매·출장·경비 정산, 계정·권한, 보안 신고, 자료 공유와 고객 문의 절차를 도와드릴 수 있습니다. 다만 실제 신청·변경·취소·승인이나 개인별 상태 조회는 할 수 없습니다. 어떤 업무가 궁금하신가요?

판정: 도움 범위·대표 영역·직접 처리 한계·후속 질문은 충족. 대표 영역을 요청된 간결한 병렬 목록 대신 한 문장에 넣음.


복구 ID: development-A014; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차, 회사 문서에 설명된 업무 도구 사용법을 안내해 드립니다.

- 휴가·근태·교육·퇴사 절차
- 출장·구매·경비 정산
- 계정·권한·기기·문서 공유
- 보안 사고·서비스 장애 대응
- 고객 문의·개발·배포 절차

신청·변경·취소·승인이나 개인별 상태 조회는 직접 처리할 수 없습니다. 어떤 업무가 궁금하신가요?

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A029; 호출별 시간·사용량: 미복구.

### R02 — 예정된 연차는 어디에서 언제까지 신청해?

**필수 기준**

1. State the portal route as 이음 포털 인사 > 휴가.
2. State the deadline as no later than three business days before the leave start date.

**근거**

- ieum-001: 예정된 연차는 사용 시작일 기준 3영업일 전까지 이음 포털의 **인사 > 휴가**에서 신청한다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예정된 연차는 이음 포털의 **인사 > 휴가**에서 사용 시작일 기준 3영업일 전까지 신청하시면 됩니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A009; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예정된 연차는 이음 포털의 **인사 > 휴가**에서 신청하며, 사용 시작일 기준 3영업일 전까지 제출하시면 됩니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A011; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예정된 연차는 사용 시작일 기준 3영업일 전까지 이음 포털의 **인사 > 휴가**에서 신청하시면 됩니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A008; 호출별 시간·사용량: 미복구.

### R03 — 국내 출장 계획부터 교통편 예약까지 어떤 순서로 진행해야 해?

**필수 기준**

1. Submit the domestic-trip request at least two business days before departure in 이음 포털 재무 > 국내 출장 신청, including purpose, dates, destination, itinerary, estimated transport/lodging, and project.
2. Wait until both the team lead and Finance approvals are recorded before booking.
3. After approval, use the booking link provided by Finance for the approved dates and route; contact Finance if the link is not displayed.
4. Do not book through a personal account or claim that approval guarantees reimbursement.

**근거**

- ieum-015: 구성원은 출발 예정일 2영업일 전까지 이음 포털의 **재무 > 국내 출장 신청**에 출장 목적, 날짜, 방문지, 일정, 예상 교통·숙박비와 비용 부담 프로젝트를 등록한다. 소속 팀장은 업무 필요와 일정을, 재무팀은 예산과 증빙 계획을 확인한다. 두 승인이 모두 포털에 기록된 뒤에만 예약한다.
- ieum-016: 먼저 국내 출장 사전 승인 (문서 ID: ieum-015)에서 팀장과 재무팀 승인이 모두 기록됐는지 확인한다. 승인 전 표를 구매하지 않는다. 승인된 출장 요청 안에서 예약 담당 재무팀이 제공한 예약 안내 링크를 사용해 승인된 날짜·구간을 예약한다. 안내 링크가 표시되지 않으면 재무팀에 문의한다. 임의로 개인 계정에서 구매하지 않는다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

국내 출장 계획부터 교통편 예약까지는 다음 순서로 진행하시면 됩니다.

1. 출발 예정일 2영업일 전까지 이음 포털 **재무 > 국내 출장 신청**에 출장 목적, 날짜, 방문지, 일정, 예상 교통·숙박비와 비용 부담 프로젝트를 등록합니다.
2. 소속 팀장과 재무팀의 승인이 모두 포털에 기록될 때까지 예약하지 않습니다.
3. 승인 후 재무팀이 해당 출장 요청에 제공한 예약 안내 링크로 승인된 날짜·구간을 예약합니다. 링크가 보이지 않으면 재무팀에 문의하고, 개인 계정으로 임의 구매하지 않습니다. 기차는 일반실, 항공은 이코노미석을 이용합니다.
4. 예약 확인서와 결제 증빙을 출장 기록에 연결하고, 방문 일정·비용 부담 프로젝트가 실제 예약과 일치하는지 확인합니다.

회사 예약 경로를 사용할 수 없어 대체 구매가 필요하면 결제 전에 팀장과 재무팀의 서면 승인을 모두 받아야 합니다. 날짜·방문지가 바뀌거나 승인 총액보다 20% 넘는 지출 증가가 예상되면 예약 변경 전에 두 역할의 재승인을 받으셔야 합니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A019; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

국내 출장은 다음 순서로 진행하시면 됩니다.
1. 출발 예정일 2영업일 전까지 이음 포털 **재무 > 국내 출장 신청**에 출장 목적, 날짜, 방문지, 일정, 예상 교통·숙박비와 비용 부담 프로젝트를 등록합니다.
2. 팀장과 재무팀의 승인이 모두 포털에 기록됐는지 확인합니다. 두 승인이 끝나기 전에는 예약하지 않습니다.
3. 승인된 출장 요청에 재무팀이 제공한 예약 안내 링크로 승인된 날짜와 구간을 예약합니다. 링크가 보이지 않으면 재무팀에 문의하고, 개인 계정으로 임의 구매하지 않습니다. 기차는 일반실, 항공은 이코노미석을 이용합니다. 회사 예약 경로를 사용할 수 없어 대체 구매가 필요하면 결제 전에 팀장과 재무팀의 서면 승인을 모두 받아야 합니다.
4. 예약 후 확인서와 결제 증빙을 출장 기록에 연결하고, 실제 예약이 승인된 일정·방문지·비용 부담 프로젝트와 일치하는지 확인합니다.
날짜나 방문지가 바뀌거나 승인 총액보다 20%를 넘는 지출 증가가 예상되면 예약을 변경하기 전에 팀장과 재무팀의 재승인을 받아야 합니다. (「국내 출장 사전 승인」, 「출장 교통편 예약」)

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A026; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

국내 출장 계획부터 교통편 예약까지는 다음 순서로 진행하시면 됩니다.

1. 출장 목적, 날짜, 방문지, 일정, 예상 교통·숙박비와 비용 부담 프로젝트를 정리합니다.
2. 출발 예정일 2영업일 전까지 이음 포털 **재무 > 국내 출장 신청**에 등록합니다.
3. 소속 팀장과 재무팀의 승인이 모두 포털에 기록됐는지 확인합니다. 두 승인이 완료되기 전에는 예약하지 않습니다.
4. 승인된 출장 요청에 재무팀이 제공한 예약 안내 링크로 승인된 날짜와 구간을 예약합니다. 링크가 보이지 않으면 재무팀에 문의하고, 임의로 개인 계정에서 구매하지 않습니다. 기차는 일반실, 항공은 이코노미석으로 예약합니다.

승인된 예약 경로를 사용할 수 없어 대체 구매가 필요하면 결제 전에 팀장과 재무팀의 서면 승인을 모두 받아야 합니다. 출발일·방문지가 바뀌거나 승인 총액보다 20% 넘는 지출 증가가 예상되면 예약 변경 전에 두 승인의 재승인을 받으세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A015; 호출별 시간·사용량: 미복구.

### R04 — 출장 예약 안내 링크가 보이지 않는 경우와 승인 총액보다 20% 넘게 비용이 늘어날 것으로 예상되는 경우 각각 어떻게 해야 해? 개인 계정으로 먼저 예약해도 돼?

**필수 기준**

1. Keep the two conditions distinct: a missing booking link means ask Finance; do not purchase through a personal account.
2. If spending is expected to exceed the approved total by more than 20%, obtain reapproval from both the team lead and Finance before changing the booking or incurring the extra expense.
3. Do not turn the alternative conditions into a mandatory sequence or imply either condition applies when it does not.

**근거**

- ieum-016: 안내 링크가 표시되지 않으면 재무팀에 문의한다. 임의로 개인 계정에서 구매하지 않는다.
- ieum-016: 출장 날짜·방문지가 달라지거나 승인 총액보다 20%를 넘는 증가가 예상되면 예약을 바꾸기 전에 팀장과 재무팀의 재승인을 받는다.
- ieum-015: 출발일·방문지 변경이나 승인 총액 대비 20%를 넘는 지출 증가가 예상되면 예약 변경 또는 추가 지출 전에 변경 신청을 하고 팀장과 재무팀의 재승인을 받는다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예약 안내 링크가 보이지 않으면 재무팀에 문의하고, 임의로 구매하지 마세요. 승인 총액보다 20% 넘게 비용이 늘어날 것으로 예상되면 예약 변경이나 추가 지출 전에 팀장과 재무팀의 재승인을 받아야 합니다. 개인 계정으로 먼저 예약하는 것도 안 됩니다. 회사 예약 경로를 사용할 수 없어 대체 구매가 필요하다면 결제 전에 팀장과 재무팀의 서면 승인을 모두 받으세요. (「출장 교통편 예약」, 「국내 출장 사전 승인」)

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A004; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예약 안내 링크가 보이지 않으면 재무팀에 문의하고 임의로 구매하지 마세요. 승인 총액보다 20% 넘게 비용이 늘어날 것으로 예상되면 예약을 변경하거나 추가 지출하기 전에 변경 신청을 하고 팀장과 재무팀의 재승인을 모두 받으셔야 합니다. 개인 계정으로 먼저 예약할 수 없으며, 승인 없이 구매한 금액은 자동으로 보전되지 않습니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A006; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

출장 예약 안내 링크가 보이지 않으면 재무팀에 문의하고, 개인 계정으로 임의 구매하지 마세요. 승인된 예약 경로를 사용할 수 없어 대체 구매가 필요하면 결제 전에 팀장과 재무팀의 서면 승인을 모두 받아야 합니다.

승인 총액보다 20% 넘게 비용이 늘어날 것으로 예상되면 예약을 변경하거나 추가 지출하기 전에 변경 신청을 하고 팀장과 재무팀의 재승인을 받으세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A012; 호출별 시간·사용량: 미복구.

### R05 — 연차를 언제 어디서 신청하는지와 남은 일수도 알려줘.

**필수 기준**

1. Answer the supported request route and deadline: 이음 포털 인사 > 휴가, three business days before the leave start date.
2. Do not calculate or look up the user's personal remaining leave balance.
3. Explain that if the balance/applicable basis is unclear, the user should check with People팀.

**근거**

- ieum-001: 예정된 연차는 사용 시작일 기준 3영업일 전까지 이음 포털의 **인사 > 휴가**에서 신청한다.
- ieum-001: 법령상 연차 부여 일수와 개인별 잔여 일수는 여기서 계산하지 않는다. 잔여 일수나 적용 기준이 포털 표시와 다르거나 불분명하면 People팀에 확인한다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예정된 연차는 사용 시작일 기준 3영업일 전까지 이음 포털의 **인사 > 휴가**에서 신청하시면 됩니다. 개인별 남은 일수는 현재 사내비에서 확인할 수 없습니다. 포털 표시가 불분명하거나 실제와 다르면 People팀에 확인해 주세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A001; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예정된 연차는 사용 시작일 기준 3영업일 전까지 이음 포털의 **인사 > 휴가**에서 신청하시면 됩니다. 개인별 남은 일수는 사내비에서 조회하거나 계산할 수 없습니다. 포털에 표시된 잔여 일수가 불분명하거나 적용 기준에 의문이 있으면 People팀에 확인해 주세요.

판정: 신청 경로/기한을 답하고 개인 잔여 일수는 조회·계산하지 않으며 포털 표시/기준이 불분명할 때 People팀 확인을 안내함.


복구 ID: development-A036; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

예정된 연차는 사용 시작일 기준 3영업일 전까지 이음 포털의 **인사 > 휴가**에서 신청하시면 됩니다. 개인별 남은 연차 일수는 현재 확인하기 어렵습니다. 잔여 일수는 People팀에 확인해 주세요.

판정: 신청 경로/기한과 잔여 일수 조회 불가, People팀 확인을 간결하게 분리함.


복구 ID: development-A035; 호출별 시간·사용량: 미복구.

### R06 — 블랙홀은 어떻게 형성돼?

**필수 기준**

1. Briefly explain that Sanaebi supports Ieumworks internal work information/procedures and company-documented tools, so a general astronomy explanation is outside this service's scope.
2. Optionally invite a company-work question.

**근거**

- generation/prompts.py: 당신은 이음웍스(ieum-works) 회사 임직원의 사내 업무 질문을 돕는 '사내비' 입니다.
- generation/profiles.py: 사내비는 이음웍스의 사내 업무 정보·규정·절차와 회사 문서에 설명된 업무 도구·기술의 사용을 안내합니다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라 블랙홀의 형성 과정 같은 일반 과학 설명은 도와드리기 어렵습니다. 사내 업무나 회사 시스템에 관한 질문을 도와드릴 수 있습니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A025; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라, 블랙홀의 형성 원리 같은 일반 과학 설명은 도와드리기 어렵습니다. 사내 업무나 회사 시스템 관련 질문을 남겨 주세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A018; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라 블랙홀의 형성에 관한 일반 지식 설명은 도와드리기 어렵습니다. 사내 업무 관련 질문이 있으시면 말씀해 주세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A005; 호출별 시간·사용량: 미복구.

### R07 — 트리 관련해서 도움받고 싶어.

**필수 기준**

1. Ask what kind of tree-related help or work context the user means before answering.
2. A brief inline example such as organization chart, file/folder structure, or code data structure is acceptable.

**근거**

- generation/profiles.py: 요청 대상·업무 맥락이 모호하면 필요한 점을 짧게 되물으세요.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 ‘트리’를 말씀하시는지 알려주시겠어요? 예를 들어 개발의 트리 자료구조, 조직도, 파일·폴더 구조 중 어떤 내용인지와 사내 업무나 시스템에서 어떤 점이 궁금하신지 적어 주세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A022; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 트리와 관련해 도움이 필요하신가요? 조직도, 파일·폴더 구조, 소프트웨어의 트리 구조 등 관련 업무나 시스템과 궁금한 점을 알려주세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A021; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

말씀하신 ‘트리’가 조직도, 시스템의 트리 구조, 자료구조 등 어떤 의미인지와 관련 업무나 상황을 알려주시겠어요?

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A027; 호출별 시간·사용량: 미복구.

### R08 — 고객 정보가 든 메일을 잘못 보냈을 때 개인정보 사고 신고와 수신자 대응 절차를 알려주세요.

**필수 기준**

1. Stop further sending/processing and promptly attempt any available recall/access restriction; verify what actually happened without claiming the recipient did not read/copy it, and preserve messages/files/logs.
2. Report immediately using #security-incident OR the portal security-report route; 30 minutes is the initial-report operating target and not a waiting period; the report path has 24-hour coverage.
3. Include discovery time, system, data kind/classification, potential affected people/work, actions already taken, and company-account contact; do not attach the customer's raw data, password, or authentication code.
4. The 15-minute acknowledgment/ownership handoff is a target, not a wait period. If the on-call person does not respond or accept handoff, do not hold the report; request the team-lead fallback. Contact the security/privacy owner directly if risk is present or the team lead cannot coordinate.
5. Record recipient, file/message, send time, and recall attempt/outcome where relevant, without claiming external copies were deleted.
6. Do not invent a required recipient message or deletion-confirmation workflow: the evidence permits a recall attempt and recording recipient/transfer/recall details, but does not specify exact recipient wording or a mandatory direct-contact step. Escalate recipient follow-up to the security/privacy owner; personal external/customer notification is not decided by the individual.

**근거**

- ieum-035: 인지하면 업무시간 여부와 관계없이 즉시 신고한다. 늦어도 인지 후 30분 안에 최초 접수를 남기는 것이 회사 운영 목표이며, 30분을 기다렸다 신고하라는 뜻이 아니다. 상시 24시간 사고 당직 연결 체계를 둔다. Slack의 #security-incident 또는 이음 포털의 보안 신고를 사용하고, 두 경로가 모두 작동하지 않을 때는 입사 시 오프라인으로 받은 비상연락카드를 따른다.
- ieum-035: 신고에는 발견 시각, 대상 시스템, 자료 종류와 등급, 영향을 받았을 수 있는 사람·업무, 이미 한 조치, 현재 연락 가능한 회사 계정만 기록한다. 비밀번호, 인증 코드, 고객 원본 자료를 신고 메시지에 붙이지 않는다.
- ieum-035: 당직 담당자는 신고를 받으면 목표로 15분 안에 신고를 확인하고 대응 책임자를 명시해 인수한다. 이 시간은 인계 목표이며 사고 해결 시간이나 법정 통지 기한을 뜻하지 않는다. 당직자가 응답하지 않거나 연결이 되지 않으면 신고자는 기다리며 신고를 보류하지 말고 팀장에게 대체 인계를 요청한다. 팀장도 대응을 조정할 수 없거나 보안·개인정보 위험이 있으면 보안·개인정보 담당자에게 직접 연결한다.
- ieum-035: 증거가 될 수 있는 메시지, 파일, 로그를 임의로 지우거나 편집하지 않는다. 본인이 할 수 있는 접근 회수 기능을 사용해도 회수 성공이나 외부 사본 삭제를 단정하지 않는다. IT운영팀은 승인된 범위에서 계정·세션·기기를 보호하고, 보안·개인정보 담당자는 영향과 추가 조치를 결정한다. 외부 기관·고객·언론 통지는 개인이 판단해 보내지 않는다.
- ieum-035: | 발견 | 추가 전송·접속을 중단하고 첫 신고 | 발견 시각, 영향 추정, 이미 한 조치 |
- ieum-031: 파일을 잘못 보냈다면 가능한 경우 접근을 회수하고, 회수 화면만으로 상대가 이미 복사·다운로드하지 않았다고 단정하지 않는다. 즉시 보안 사고 신고와 초동 대응 (문서 ID: ieum-035)에 알리고 수신자·파일·전송 시각·회수 시도 결과를 기록한다.
- ieum-040: 잘못 보낸 메시지나 링크를 발견하면 가능한 회수 조치를 시도하고 실제 회수 여부를 확인한다. 상대가 이미 열람·복사하지 않았다고 추정하지 말고 민감 정보면 즉시 보안 신고한다.

#### examples_answer_scope_v5 · 반복 1

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

고객 정보가 잘못 전송된 경우 개인정보 노출 가능성이 있는 보안 사고로 보고, 즉시 신고하세요. 이음 포털의 **보안 > 사고 신고** 또는 Slack **#security-incident**를 이용하고, 두 경로를 모두 사용할 수 없으면 입사 때 받은 오프라인 비상연락카드를 따르세요. 최초 접수는 인지 후 30분 이내가 운영 목표이며, 30분을 기다리라는 뜻은 아닙니다. 24시간 신고·당직 연결 체계가 있습니다.

추가 전송을 중단하고, 가능한 경우 메일 회수나 접근 권한 회수를 시도한 뒤 실제 결과를 확인하세요. 수신자가 이미 열람·복사하지 않았다고 단정하지 마세요. 신고에는 발견 시각, 수신자, 전송한 자료와 정보의 종류·등급, 영향받았을 수 있는 사람·업무, 회수 시도와 결과, 이미 취한 조치를 적으세요. 고객 원본 정보·비밀번호·인증 코드는 신고 메시지에 붙이지 말고, 메일·첨부·로그 등 증거를 임의로 삭제하거나 편집하지 마세요.

수신자에게 삭제 요청을 하거나 회신을 요구하는 구체적인 절차는 현재 사내비에서 확인하기 어렵습니다. 수신자 대응과 추가 조치는 신고 기록에 상황을 남겨 보안·개인정보 담당자의 안내를 받으세요. 외부 고객·기관 통지도 개인 판단으로 보내지 말고 담당자가 검토하도록 하세요.

판정: 신고 경로·30분/24시간, 중단·회수·증거 보존은 정확하지만 15분 인수와 대체 인계가 빠졌고 신고 기록의 시스템/연락 계정/전송 시각도 불완전함. 15분 대체 경로 누락은 중대한 절차 누락으로 판단.

- 필수 3: missing — 정보 종류·등급과 영향은 적지만 대상 시스템 및 현재 연락 가능한 회사 계정을 적으라는 항목은 빠짐.
- 필수 4: missing — 15분 인수 목표, 응답 부재 시 팀장 대체 인계, 위험 시 담당자 직접 연결이 없음.
- 필수 5: missing — 수신자와 전송 자료·회수 결과는 언급하지만 전송 시각을 기록하라는 항목은 없음.

복구 ID: development-A007; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

고객 정보가 잘못 전송됐다면 보안·개인정보 사고로 보고 즉시 신고하세요. 업무시간 여부와 관계없이 Slack의 #security-incident 또는 이음 포털의 보안 신고를 이용할 수 있습니다. 늦어도 인지 후 30분 안에 최초 접수를 남기는 것은 운영 목표이며, 30분을 기다리라는 뜻은 아닙니다. 포털을 사용할 수 없으면 Slack 등으로 먼저 신고하고, 복구 후 포털 기록을 보완하세요. 두 경로 모두 사용할 수 없으면 입사 때 받은 오프라인 비상연락카드를 이용하세요.

신고와 함께 추가 전송·공유를 중단하고, 가능한 접근 회수 조치가 있으면 시도하세요. 다만 회수했다고 수신자가 이미 복사·다운로드한 자료까지 삭제됐다고 단정하지 마세요. 원본 메일·파일·로그를 임의로 삭제하거나 편집하지 마세요.

신고에는 발견 시각, 전송 시각, 수신자, 대상 파일·자료의 종류와 등급, 영향을 받았을 수 있는 사람·업무, 이미 한 조치와 회수 시도 결과를 적으세요. 고객 원본 자료, 비밀번호, 인증 코드는 신고 메시지에 붙이지 마세요.

당직 담당자의 확인·인수는 15분 안을 목표로 합니다. 응답이나 인수가 확인되지 않으면 기다리지 말고 팀장에게 대체 인계를 요청하고, 팀장이 조정할 수 없거나 보안·개인정보 위험이 있으면 보안·개인정보 담당자에게 직접 연결하세요.

수신자에게 삭제·회신을 요청하는 구체 절차나 문안, 담당자는 현재 확인하기 어렵습니다. 고객 등 외부 통지는 개인 판단으로 보내지 마시고, 보안·개인정보 담당자가 필요한 통지와 대응을 검토하도록 연결하세요. 이 안내는 「보안 사고 신고와 초동 대응」 및 「업무 파일 공유와 외부 제공」의 기준입니다.

판정: 즉시 신고·24시간 경로, 15분 대체 인계, 담당자 검토와 전송 시각 기록은 명확. 실제 회수 여부 확인 지시와 신고 연락용 회사 계정은 빠짐.

- 필수 1: missing — 추가 전송 중단과 회수 시도, 결과 기록 및 과장 금지는 있으나 실제 회수 여부를 확인하라는 지시는 명시되지 않음.
- 필수 3: missing — 대상 메일·자료와 정보 유형, 영향/조치는 있으나 현재 연락 가능한 회사 계정을 적으라는 항목은 없음.

복구 ID: development-A020; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

고객 정보가 잘못 발송된 경우 개인정보 노출 가능성이 있는 보안 사고로 보고, 즉시 신고하세요.

1. 추가 전송이나 자료 접근을 중단하고, 이음 포털의 보안 신고 또는 Slack `#security-incident`로 알리세요. 두 경로를 모두 사용할 수 없으면 입사 때 받은 오프라인 비상연락카드를 이용합니다. 최초 신고는 인지 후 30분 안이 운영 목표지만, 30분을 기다리지 말고 바로 신고하세요.
2. 발견 시각, 잘못 발송한 메일과 수신자, 고객 정보의 종류와 영향 가능 범위, 이미 한 조치, 회수 시도와 결과를 알리세요. 고객 원본 자료나 비밀번호·인증 코드 등은 신고 메시지에 첨부하지 마세요. 원본 메일이나 증거가 될 수 있는 자료를 임의로 삭제·수정하지 마세요.
3. 가능한 회수 조치가 있으면 시도하고 실제 회수 여부를 확인하세요. 회수했다고 해서 수신자가 이미 열람·복사하지 않았다고 단정하면 안 됩니다. 담당자의 접수 확인이 15분 안에 없으면 기다리지 말고 팀장에게 대체 인계를 요청하고, 연결이 어렵거나 보안·개인정보 위험이 있으면 보안·개인정보 담당자에게 직접 연결하세요.

수신자에게 별도로 삭제를 요청하거나 안내할 구체 절차는 현재 사내비에서 확인하기 어렵습니다. 외부 통지는 개인 판단으로 보내지 말고 보안·개인정보 담당자의 안내를 따르세요. 관련 기준은 「보안 사고 신고와 초동 대응」과 「업무 이메일과 메신저 사용」에 있습니다.

판정: 즉시 신고·30분 목표, 15분 대체 인계, 위험 시 담당자 연결과 수신자 대응 경계는 충족. 24시간 커버리지, 현재 회사 계정, 전송 시각이 빠짐.

- 필수 2: missing — 즉시 신고와 30분 목표 및 오프라인 비상연락카드 대체는 안내하지만, 업무시간 밖을 포함한 24시간 신고·당직 커버리지는 명시하지 않음.
- 필수 3: missing — 시간·수신자·자료·영향·조치는 제시하지만 신고 때 현재 연락 가능한 회사 계정을 적으라는 항목은 없음.
- 필수 5: missing — 수신자·메일·발견 시각과 회수 시도/결과는 기록하지만, 전송 시각을 기록하라는 항목은 없음.

복구 ID: development-A016; 호출별 시간·사용량: 미복구.

### D09 — 회의에서 결정된 내용과 후속 일을 어떤 방식으로 기록해야 해?

**필수 기준**

1. Record what was decided, why, owner, deadline, and remaining risks, then confirm the record with attendees.
2. After the meeting, save outcomes and follow-up tasks in the team/project source document and share its link in Slack.
3. Assign an owner and next check time to unresolved questions; do not treat unrecorded or unassigned discussion as a completed decision.
4. Do not treat silence as approval; items requiring legal/security/privacy review are not complete before that review.

**근거**

- ieum-041: 결정이 나면 무엇을 결정했는지, 선택 이유, 담당자, 기한, 남은 위험을 읽어 참석자와 확인한다.
- ieum-041: 참석자에게 동의 여부를 묻지 않은 채 침묵을 승인으로 기록하지 않는다.
- ieum-041: 회의 뒤 주최자는 핵심 결과와 후속 작업을 Google Workspace의 프로젝트·팀 기준 문서에 기록하고 Slack에 링크를 공유한다.
- ieum-041: 미해결 질문은 담당자와 다음 확인 시점을 지정한다. 기록이 없거나 담당자가 정해지지 않은 논의를 완료된 결정으로 취급하지 않는다.

#### examples_answer_scope_v5 · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

회의 중에는 결정 사항과 보류 사항을 구분하고, 결정 내용·선택 이유·담당자·기한·남은 위험을 참석자와 확인하세요. 침묵을 동의로 기록하지 않습니다. 회의 후 주최자가 핵심 결과와 후속 작업을 Google Workspace의 프로젝트·팀 기준 문서에 기록하고 Slack에 링크를 공유합니다. 개발 변경은 관련 GitHub 이슈나 변경 기록에도 연결합니다. 미해결 질문은 담당자와 다음 확인 시점을 남기세요.

판정: 회의 중 필수 결정 항목과 기록 위치, 후속 담당은 있으나 법률·보안·개인정보 검토 전 완료 금지 조건이 빠짐.

- 필수 4: missing — 검토가 필요한 항목을 검토 전 결정 완료로 보지 않는 조건이 없음.

복구 ID: development-A002; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

회의 주최자가 회의 후 Google Workspace의 프로젝트·팀 기준 문서에 핵심 결과를 기록하고, Slack에 문서 링크를 공유합니다. 결정 사항은 결정 내용과 선택 이유를, 후속 업무는 담당자와 기한을 적고 남은 위험이나 미해결 질문도 구분해 기록하세요. 논의·보류 사항을 확정된 결정과 섞지 말고, 참석자의 침묵을 동의로 기록하지 않습니다. 미해결 질문에는 담당자와 다음 확인 시점을 지정하며, 개발 변경은 관련 GitHub 이슈나 변경 기록에도 연결합니다.

판정: 기준 문서·Slack 기록, 후속 담당과 확인 시점은 제시하지만 참석자 확인 및 검토 전 완료 금지 조건이 빠짐.

- 필수 1: missing — 결정 항목은 기록하지만 그 기록을 참석자와 확인하라는 단계는 없음.
- 필수 4: missing — 침묵 승인 금지는 있으나 필요한 법률·보안·개인정보 검토가 끝나기 전 완료로 보지 않는다는 점은 없음.

복구 ID: development-A010; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

회의 중 결정·보류 사항을 구분하고, 후속 작업마다 담당자와 기한을 확인합니다. 참석자에게 동의를 묻지 않은 침묵은 승인으로 기록하지 않습니다.

회의 후 주최자가 핵심 결과를 Google Workspace의 프로젝트·팀 기준 문서에 기록하고 Slack에 링크를 공유합니다. 결정 내용과 선택 이유, 담당자, 기한, 남은 위험을 남기고, 개발 변경은 관련 GitHub 이슈나 변경 기록에도 연결합니다.

판정: 기준 문서 기록과 Slack 링크, 침묵 승인 금지는 정확. 참석자 확인, 미해결 후속 담당/시점, 법률·보안·개인정보 검토 조건이 빠짐.

- 필수 1: missing — 결정 내용·이유·담당·기한·위험 기록은 있으나 참석자 확인 단계가 없음.
- 필수 3: missing — 미해결 질문의 담당자·다음 확인 시점 및 미기록 논의 처리 기준이 없음.
- 필수 4: missing — 침묵을 승인으로 보지 않지만 필수 검토 전 완료 금지 조건은 없음.

복구 ID: development-A031; 호출별 시간·사용량: 미복구.

### D10 — 공유드라이브 파일이 덮어써진 걸 발견했어. 복구하려면 무엇부터 해야 해?

**필수 기준**

1. Stop further editing, moving, or deleting the affected file.
2. Record the name/link, last known normal time, storage location, discovery time, affected users, and actions already attempted.
3. Do not restore alone or change sharing scope; notify the file owner and IT operations promptly because recovery windows/ranges may be limited.
4. Have the owner verify recovered content and permissions; record missing parts before saying recovery is complete.

**근거**

- ieum-038: 문서가 사라지거나 덮어써졌다면 추가 편집·이동·삭제를 멈춘다.
- ieum-038: 문서 이름이나 링크, 마지막으로 정상 확인한 시각, 저장 위치, 발견 시각, 영향받은 사용자, 이미 시도한 조치를 적는다.
- ieum-038: 파일이 Google Drive 휴지통이나 버전 기록에 보이면 혼자 복원해 공유 범위를 바꾸지 말고 자료 소유자와 IT운영팀에 먼저 알린다. 관리 복구는 가능한 기간과 날짜 범위가 제한될 수 있고 공유드라이브 자료는 별도 절차를 따르므로 즉시 요청한다.
- ieum-038: 시스템이 확인한 복구 가능 범위와 대상 버전을 받은 뒤 자료 소유자가 내용·권한을 확인한다. 복원 결과와 빠진 부분을 기록하기 전에는 복구 완료로 알리지 않는다.

#### examples_answer_scope_v5 · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

먼저 파일의 추가 편집·이동·삭제를 멈추세요. 파일명과 링크, 공유드라이브 위치, 마지막으로 정상 확인한 시각, 덮어쓴 것을 발견한 시각, 영향받은 사용자와 이미 시도한 조치를 기록해 자료 소유자와 IT운영팀에 즉시 알리세요. 버전 기록이나 휴지통에 파일이 보여도 직접 복원하지 말고 먼저 확인을 요청하세요. IT운영팀이 실제 복구 가능 범위와 대상 버전을 확인하고, 복원 후에는 자료 소유자가 내용과 접근 권한을 확인해야 합니다. 복구가 확인되기 전에는 완료로 단정하지 마세요. (「업무 자료 보관과 복구」, 「업무 기록 보존표와 복구 안내」)

판정: 초기 중단·기록·통지 및 소유자 검증은 있으나 복구 창 제한과 복구 결과/누락 기록 조건이 빠짐.

- 필수 3: missing — 소유자·IT 통지는 즉시 요구하지만 복구 기간/날짜 범위가 제한될 수 있다는 이유는 제시하지 않음.
- 필수 4: missing — 소유자의 내용·권한 확인은 있으나 복구 결과와 빠진 부분을 기록한 뒤 완료로 알리라는 조건은 없음.

복구 ID: development-A013; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

먼저 해당 파일의 편집·이동·삭제를 중단하세요. 파일명과 링크, 공유드라이브 위치, 마지막으로 정상 확인한 시각, 덮어쓴 사실을 발견한 시각, 영향받은 사용자와 이미 시도한 조치를 기록한 뒤 자료 소유자와 IT운영팀에 즉시 알리세요. 버전 기록에 이전 내용이 보여도 직접 복원하거나 공유 범위를 바꾸지 마세요. 복구 가능성과 범위는 이음 포털의 **IT > 복구 가능성 확인**으로 요청할 수 있습니다. 복구 후에는 자료 소유자가 내용과 권한을 확인하고, 복원 결과와 누락된 부분을 기록하기 전에는 완료로 처리하지 마세요.

판정: 중단·기록·소유자/IT 통지와 소유자 검증은 충족. 복구 가능 기간·날짜 범위의 제한 가능성이 빠짐.

- 필수 3: missing — 소유자·IT에 즉시 알리고 복구 범위를 요청하지만, 기간/날짜 범위가 제한될 수 있다는 설명은 없음.

복구 ID: development-A003; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 fail / 가독성 pass / 구조 pass / 중대한 오류 False

먼저 해당 파일의 추가 편집·이동·삭제를 멈추세요. 파일명이나 링크, 저장 위치, 마지막으로 정상 확인한 시각과 덮어쓴 사실을 발견한 시각, 영향받은 사용자, 이미 시도한 조치를 기록해 자료 소유자와 IT운영팀에 바로 알리세요.

파일이 Google Drive의 버전 기록이나 휴지통에 보이더라도 직접 복원하지 말고 먼저 알리세요. 복구 가능 기간과 범위가 제한될 수 있으니 이음 포털의 **IT > 복구 가능성 확인**으로 요청하고, 공유드라이브 파일은 별도 복구 절차를 확인해야 합니다. 복구 여부는 IT운영팀의 확인 전에는 단정하기 어렵습니다.

판정: 중단·기록·소유자/IT 통지와 제한된 복구 기간은 정확하지만 완료 전 소유자 검증 및 복구 누락 기록이라는 핵심 완료 조건이 빠짐.

- 필수 4: missing — IT 확인 전 완료를 단정하지 말라고만 하고 소유자의 복구 내용·권한 검증과 결과/누락 기록을 요구하지 않음.

복구 ID: development-A034; 호출별 시간·사용량: 미복구.

### D11 — 고객이 버그를 신고했어. 개발팀에 넘길 정보와 인계 완료 기준은 뭐야?

**필수 기준**

1. Record customer goal, observed impact, occurrence time/timezone, expected versus actual behavior, and a minimal reproduction when available.
2. Include only information needed for investigation; never put passwords, tokens, session cookies, or raw customer data in GitHub.
3. A GitHub issue/message alone does not complete handoff; the receiving person must explicitly accept it and current customer owner remains responsible until acceptance.
4. Do not promise a fix or release date; give the customer the confirmed facts and next update target.

**근거**

- ieum-065: 오류라면 발생 시각과 시간대, 영향을 받는 기능, 예상 동작과 실제 동작, 재현 여부를 묻는다.
- ieum-066: 암호, 인증 코드, 토큰, 세션 쿠키, 전체 요청·응답 본문, 고객 원본 데이터, 개인의 실제 이메일 주소나 전화번호를 GitHub 이슈에 넣지 않는다.
- ieum-065: 수신자가 명시적으로 수락할 때까지 기존 담당자가 고객 문의를 맡는다.
- ieum-066: 이슈가 생성되거나 개발팀에 전달됐다는 사실은 수정 약속이 아니다.

#### examples_answer_scope_v5 · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

개발팀에 전달할 때는 다음 정보를 기록해 주세요.
- 문제 요약: 고객이 하려던 일과 실제로 발생한 결과
- 기대 동작과 실제 동작을 구분한 설명
- 테스트 데이터로 확인할 수 있는 최소 재현 단계와 선행 조건, 반복 여부
- 발생 시각과 시간대, 조사에 필요한 기능·제품 버전·브라우저·운영체제 등 환경
- 업무상 영향, 영향 범위, 가능한 우회 방법
- 이미 확인하거나 안내한 조치와 결과, 고객이 기대하는 후속 조치

확인되지 않은 항목은 추정하지 말고 ‘미확인’으로 표시하고, 재현되지 않았거나 버그 여부가 확정되지 않았다면 ‘버그 의심’으로 전달해 주세요. 고객의 비밀번호·인증 코드·토큰·원본 데이터나 불필요한 식별정보는 GitHub 이슈에 넣지 말고, 필요한 자료는 식별정보를 제거해 안전한 포털 첨부로 제한해 주세요.

인계 기록에는 문의 번호, 담당 팀·역할과 수신자, 인계 시각, 고객에게 안내한 내용과 다음 안내 목표 시점, 다음 행동도 포함합니다. 수신자가 인계를 명시적으로 수락해야 완료입니다. GitHub 이슈를 만들거나 Slack 메시지를 보내는 것만으로는 인계가 완료되지 않으며, 수락 전까지 기존 담당자가 고객 문의를 계속 맡습니다. (「고객 문의 접수와 인계」, 「버그·기능 요청 전달」)

판정: 접수 정보와 안전한 자료 제한, 수신 수락 및 기존 담당자 책임은 충족. 토큰 금지는 세션 자격 토큰을 포함하는 의미로 판단했으며, 고객에게 다음 안내 목표를 실제 전달하라는 지시는 암시적임.

- 필수 4: uncertain — 다음 안내 목표를 기록하도록 하지만 고객에게 확인 사실과 다음 시점을 실제 전달하라는 지시는 암시적임.

복구 ID: development-A030; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

버그가 확정되지 않았다면 ‘버그 의심’으로 전달하고, 확인된 사실과 미확인 사항을 구분해 주세요. 개발팀에는 다음 정보를 전달합니다.
- 고객이 하려던 일과 문제 요약, 기대한 동작과 실제 동작
- 테스트 데이터로 재현 가능한 최소 단계와 선행 조건, 재현 여부
- 발생 시각과 시간대, 조사에 필요한 기능·제품 버전·브라우저·운영체제 등 환경 정보
- 막힌 업무와 영향 범위, 확인된 우회 방법, 이미 확인하거나 시도한 조치와 결과
- 고객지원 문의 번호와 필요한 자료의 위치·접근 범위

문의와 내부 논의는 포털의 고객지원 기록을 기준으로 하고, GitHub 이슈를 만들기 전 담당 저장소와 접근 범위를 확인하고 중복 이슈를 검색합니다. 이슈에는 비밀번호·인증 코드·토큰·고객 원본 데이터 등을 넣지 마세요. 캡처나 로그가 필요하면 식별정보를 제거해 안전한 포털 첨부로 제한합니다.

인계는 개발팀의 수신자가 명시적으로 수락해야 완료입니다. GitHub 이슈를 만들거나 Slack에 전달한 것만으로는 완료가 아니며, 수락 전까지 기존 담당자가 고객 문의와 진행 안내를 계속 맡습니다. 포털 문의에는 담당 팀·역할과 수신자, 인계 시각, 전달 정보와 자료 위치, 고객에게 안내한 내용·다음 안내 목표 시점, 인계 수락 여부와 다음 행동을 기록하세요.

판정: 고객 목표·영향·재현 정보와 명시적 인수 기준 및 기존 담당 책임은 분명함. 토큰 금지는 세션 자격 토큰을 포함하는 의미로 판단했으며, 다음 안내 목표를 고객에게 실제 전달하라는 지시는 암시적임.

- 필수 4: uncertain — 다음 안내 목표를 포털에 기록하고 기존 담당자의 진행 안내를 유지하지만, 고객에게 확인 사실과 다음 시점을 직접 알리라는 지시는 암시적임.

복구 ID: development-A028; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

개발팀에는 확인된 사실과 미확인 사항을 구분해, 다음 정보를 전달하세요.

- 고객이 하려던 일과 실제로 발생한 결과
- 기대 동작과 실제 동작, 필요한 경우 민감정보를 제거한 오류 문구
- 테스트 자료로 확인할 수 있는 최소 재현 단계와 선행 조건, 반복 여부
- 발생 시각·시간대와 조사에 필요한 제품 버전·브라우저·운영체제 등 환경
- 영향을 받는 기능과 업무상 영향, 우회 방법 및 확인되지 않은 범위
- 이미 확인하거나 안내한 조치와 그 결과
- 요청 유형과 고객이 기대하는 후속 판단

확인하지 못한 항목은 추정하지 말고 미확인으로 표시하세요. 비밀번호·토큰·고객 원본 데이터 등은 GitHub 이슈나 Slack에 넣지 말고, 필요한 자료는 안전한 포털 첨부로 제한하세요. 기존 이슈가 있으면 고객별 정보 대신 문의 번호와 권한이 확인된 링크만 연결합니다.

인계할 때는 포털 문의에 문의 번호, 담당 팀·역할과 수신자, 인계 시각, 확인된 영향·재현 정보, 자료 위치와 접근 제한, 고객에게 안내한 내용과 다음 안내 목표, 다음 행동을 기록하세요. 개발팀에 이슈를 만들거나 Slack으로 전달한 것만으로는 인계가 완료되지 않습니다. 수신자가 명시적으로 인수해야 완료이며, 인수 확인 전까지 기존 담당자가 고객 문의와 진행 안내를 계속 맡습니다.

판정: 필수 재현 정보와 수락/기존 담당 책임은 잘 분리됨. 토큰 금지는 세션 자격 토큰을 포함하는 의미로 판단했으며, 확인 사실·다음 안내 목표를 고객에게 실제 전달하라는 지시는 암시적임.

- 필수 4: uncertain — 고객에게 한 안내와 다음 목표를 포털에 기록하도록 하지만 실제 고객 안내 지시는 암시적임.

복구 ID: development-A033; 호출별 시간·사용량: 미복구.

### D12 — 회사 업무에 생성형 AI를 쓰려면 어떤 자료를 넣을 수 있고 결과를 어떻게 확인해야 해?

**필수 기준**

1. Use only the company-managed ChatGPT Business workspace for company work.
2. Input only information that is publicly accessible and whose use conditions/licence are confirmed; internal documents, customer data, personal data, code, credentials, and secrets are prohibited.
3. If publicness or licence is uncertain, do not input the material; do not bypass with a personal account or another AI service.
4. Check output facts, calculations, citations, and code against source material; check source/IP/confidentiality classification and required review before using it in company work.

**근거**

- ieum-033: 회사 업무에서 생성형 AI가 필요할 때는 회사 관리 계정으로 접속하는 ChatGPT Business 회사 워크스페이스만 사용한다. 입력 자료는 공개된 정보로 제한한다.
- ieum-033: 공개 정보인지 확실하지 않거나 공개 조건·라이선스를 확인할 수 없으면 입력하지 않는다. 개인 계정, 다른 AI 사이트, 브라우저 확장으로 우회하지 않는다.
- ieum-033: 결과의 사실·계산·인용·코드를 사람이 원자료와 비교한다. 근거를 찾을 수 없는 내용은 사실로 전달하지 않는다.
- ieum-033: 결과를 회사 산출물에 반영할 때 출처·저작권·기밀 분류를 다시 확인하고, 해당 문서의 검토·승인 절차를 따른다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

회사 업무에서는 회사 관리 계정의 ChatGPT Business 회사 워크스페이스만 사용하고, 누구나 공개적으로 볼 수 있으며 이용 조건을 확인한 자료만 입력할 수 있습니다. 질문에 필요한 부분만 입력하고 출처·권리 표시를 보존하세요. 사내 전용 문서, 고객 자료, 개인정보, 소스 코드, 기밀정보는 식별자를 지우거나 요약해도 입력할 수 없습니다.

입력 전 자료의 공개 범위와 이용 조건을 확인하고, 공개 여부가 확실하지 않으면 입력하지 마세요. 결과는 사실·계산·인용·코드를 원자료와 대조해 확인하고, 근거가 확인되지 않는 내용은 사실로 전달하지 마세요. 회사 산출물에 반영할 때는 출처·저작권·기밀 분류를 다시 확인하고 해당 문서의 검토·승인 절차를 따르세요. 공개 자료만 입력해도 결과의 정확성이나 저작권 적합성이 보장되는 것은 아닙니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A023; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

「생성형 AI 업무 사용」 안내에 따르면, 업무용 생성형 AI는 회사 관리 계정으로 접속하는 ChatGPT Business 회사 워크스페이스만 사용하고, 누구나 공개적으로 볼 수 있으며 이용 조건을 확인한 자료만 입력할 수 있습니다. 질문에 필요한 부분만 입력하고 출처·권리 표시를 보존하세요. 사내 전용 문서, 고객 자료, 개인정보·인사 자료, 소스 코드와 비밀정보는 식별자를 지운 경우에도 입력할 수 없으며, 개인 계정이나 다른 AI 서비스로 우회해서도 안 됩니다.

결과는 원자료와 대조해 사실·계산·인용·코드를 직접 확인하고, 근거를 찾을 수 없는 내용은 사실로 전달하지 마세요. 회사 산출물에 반영할 때는 출처·저작권·기밀 분류를 다시 확인하고 해당 문서의 검토·승인 절차를 따르세요.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A017; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_readability · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

회사 업무에서 생성형 AI는 회사 관리 계정의 ChatGPT Business 회사 워크스페이스만 사용하며, 입력 자료는 공개 여부와 이용 조건을 확인한 정보로 제한합니다. 사내 전용 문서, 고객·계약·개인정보, 소스 코드와 비밀정보는 입력할 수 없습니다. 공개 여부나 이용 조건이 불분명하면 입력하지 마세요.

사용 전 자료의 공개 범위와 이용 조건을 확인하고, 질문에 필요한 최소한의 내용만 입력하세요. 결과는 원자료와 대조해 사실·계산·인용·코드를 사람이 확인하고, 근거가 없는 내용은 사실로 전달하지 않아야 합니다. 회사 산출물에 반영할 때는 출처·저작권·기밀 분류를 다시 확인하고 해당 문서의 검토·승인 절차를 따르세요. 자세한 내용은 「생성형 AI 업무 사용」 안내를 참고하시면 됩니다.

판정: 문항의 필수 항목을 충족하며 근거와 요청된 구조에 맞게 직접 답함.


복구 ID: development-A024; 호출별 시간·사용량: 미복구.

## final

### H01 — 다음 주 입사하는 신입 구성원에게 사내비가 어떤 회사 업무를 안내할 수 있는지 짧은 소개 문구를 만들어줘. 직접 처리할 수 없는 일도 밝혀줘.

**필수 기준**

1. Introduce the assistant as providing guidance from company work information/rules/procedures and company-documented tools.
2. Give a few grounded areas useful to a new hire, such as onboarding, leave/attendance, accounts/permissions, or security.
3. State it cannot directly submit/change/approve requests or look up individual live status.
4. Invite the new hire to ask about a concrete work topic.

**근거**

- ieum-050: People팀은 공통 체크리스트와 제도·문의 안내를 준비한다.
- generation/profiles.py: 사내비는 이음웍스의 사내 업무 정보·규정·절차와 회사 문서에 설명된 업무 도구·기술의 사용을 안내합니다.
- ieum-050: 입사자는 첫 로그인 과정에서 다중 인증 등록을 완료한다. MFA 설정이 끝나기 전에는 업무 시스템과 자료에 접근하지 않는다.
- ieum-027: 구성원은 이음 포털의 IT > 접근 권한에서 시스템 이름, 필요한 역할, 업무 사유, 시작일과 종료일을 적는다.
- generation/prompts.py: 사내비는 제공된 문서를 바탕으로 정보를 안내하며, 실제 신청·변경·취소·승인이나 개인별 상태 조회를 수행하지 않습니다.

#### examples_answer_scope_v5 · 반복 1

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

안녕하세요, 사내비입니다. 입사·계정·근태·휴가·비용·보안 등 이음웍스의 사내 절차와 업무 도구 사용을 안내해 드립니다. 신청·변경·취소·승인이나 개인별 상태 조회는 직접 처리하지 않으니, 실제 업무 처리는 안내된 경로를 이용해 주세요.

판정: 짧고 명확하지만 다음 질문을 권하는 문장이 없고, 영역 목록도 요구된 병렬 목록 구조가 아니다.

- 필수 4: missing — 신입에게 구체적인 업무 질문을 해 보라고 초대하지 않았다.

복구 ID: final-1-A007; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

사내비는 이음웍스의 사내 규정과 업무 절차, 문서에 안내된 업무 도구 사용법을 알려드립니다. 입사·계정·권한·근태·휴가, 출장·구매·경비, 자료·보안 등 업무를 안내할 수 있습니다. 다만 신청·변경·취소·승인 같은 실제 처리나 개인별 처리 상태 조회는 할 수 없으니, 안내된 포털이나 담당 경로를 이용해 주세요.

판정: 짧고 명확하지만 요구된 후속 질문 초대가 없고 병렬 영역을 불릿으로 분리하지 않았다.

- 필수 4: missing — 포털이나 담당 경로를 쓰라고 했지만 구체적인 업무 질문을 사내비에 해 보라는 초대는 없다.

복구 ID: final-2-A006; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

사내비는 이음웍스의 사내 규정과 업무 절차, 회사 문서에 안내된 업무 도구 사용법을 도와드립니다. 입사·휴가·근태·교육, 구매·출장·경비, 계정·권한, 보안·사무실 관련 정보를 안내할 수 있습니다. 다만 신청·변경·취소·승인이나 개인별 상태 조회는 직접 처리하지 않습니다.

판정: 핵심 소개와 한계는 명확하지만 후속 질문 초대가 빠졌다.

- 필수 4: missing — 구체적인 회사 업무 질문을 해 달라는 초대 문장이 없다.

복구 ID: final-3-A002; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

안녕하세요, 사내비입니다. 입사 절차, 계정·권한과 업무 도구, 휴가·근태, 출장·경비, 보안 신고 등 이음웍스의 사내 업무 절차와 도구 사용 방법을 안내해 드립니다. 다만 신청·변경·취소·승인, 계정·권한 처리, 개인별 상태나 잔여 일수 조회는 직접 할 수 없으니 안내된 포털 절차와 담당 부서를 이용해 주세요.

판정: 범위와 처리 한계는 명확하지만 후속 질문 초대가 없고 병렬 영역이 문장 안에 나열됐다.

- 필수 4: missing — 신입에게 구체적인 업무 질문을 요청하거나 초대하지 않았다.

복구 ID: final-1-A010; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

사내비는 이음웍스의 입사·휴가·근태·교육, 출장·구매·경비, 업무 도구·권한, 보안·협업 절차를 안내합니다. 신청 경로와 필요한 단계를 설명할 수 있지만, 신청·변경·취소·승인이나 개인별 상태 조회를 직접 하지는 않습니다.

판정: 짧고 분야 목록과 한계는 분명하지만 문서 근거 범위와 다음 질문 초대가 빠졌다.

- 필수 1: missing — 회사 업무 분야와 도구·절차는 열거했으나 회사 문서에 근거한 안내라고 밝히지 않았다.
- 필수 4: missing — 구체적인 업무 주제를 질문해 보라는 초대가 없다.

복구 ID: final-2-A022; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

안녕하세요, 사내비입니다. 입사·계정·업무 도구, 휴가·근태, 출장·구매·경비, 문서·보안 등 이음웍스의 사내 업무 절차와 회사 도구 사용을 안내해 드립니다. 다만 신청·변경·취소·승인이나 개인별 상태 조회는 직접 할 수 없으며, 관련 절차와 처리 경로를 안내해 드립니다.

판정: 이해하기 쉽지만 병렬 업무 영역을 문장 안에 나열했고 다음 질문 초대가 없다.

- 필수 4: missing — 구체적인 업무 주제를 질문해 달라는 초대가 없다.

복구 ID: final-3-A005; 호출별 시간·사용량: 미복구.

### H02 — 팀원들에게 사내비를 권한 신청 전에 어떻게 활용할 수 있는지 소개해줘. 권한이 이미 부여됐는지 대신 확인할 수 있는지도 포함해줘.

**필수 기준**

1. Introduce company-work guidance, with account/permission procedures as a relevant example.
2. Mention that the assistant can explain how to request access and who/what must review it, based on company documents.
3. State it cannot check an individual’s live access or directly grant/change/approve access.
4. Ask the team member to specify the system or access question.

**근거**

- ieum-027: 권한은 현재 업무에 필요한 시스템·자료에 한해 개인별 회사 계정으로 부여한다. 직함이나 팀 소속만으로 모든 자료를 볼 수 있는 것은 아니다.
- ieum-027: 구성원은 이음 포털의 IT > 접근 권한에서 시스템 이름, 필요한 역할, 업무 사유, 시작일과 종료일을 적는다.
- ieum-027: 접근 거부 시 로그인한 회사 계정, 파일·시스템 주소, 필요한 업무 역할, 오류 시각을 확인한다.
- ieum-027: 팀장은 업무 필요를 확인한다. 해당 시스템 담당자는 역할 범위와 기술 조건을 검토하고, 고객 운영 환경·기밀 자료·개인정보 접근에는 자료 소유자 및 보안·개인정보 담당자의 확인도 받는다.
- generation/profiles.py: 사내비는 이음웍스의 사내 업무 정보·규정·절차와 회사 문서에 설명된 업무 도구·기술의 사용을 안내합니다.
- generation/prompts.py: 사내비는 제공된 문서를 바탕으로 정보를 안내하며, 실제 신청·변경·취소·승인이나 개인별 상태 조회를 수행하지 않습니다.

#### examples_answer_scope_v5 · 반복 1

내용 partial / 가독성 partial / 구조 partial / 중대한 오류 False

팀원들에게는 이렇게 소개하시면 됩니다.

“권한을 신청하기 전에 사내비에 필요한 시스템과 업무를 설명하면, 관련 신청 절차와 필요한 역할·신청 정보를 확인하는 데 도움을 받을 수 있습니다. 시스템 접근 권한 신청에는 시스템 이름, 필요한 역할, 업무 사유, 시작일과 종료일이 필요합니다. 사내비는 개인별 권한을 조회하거나 권한을 신청·부여하지는 않습니다.

권한이 이미 부여됐는지는 사내비가 대신 확인할 수 없습니다. 본인이 포털에서 신청 처리 결과를 확인하고, 접근 오류가 있으면 로그인한 회사 계정과 시스템 주소, 필요한 업무 역할을 확인하세요. 원인을 구분하기 어렵다면 민감한 정보를 포함하지 않고 #it-helpdesk에 문의하면 됩니다.”

신청은 이음 포털의 **IT > 접근 권한**에서 하며, 자세한 기준은 「시스템 접근 권한 신청과 회수」에서 확인할 수 있습니다.

판정: 질문에서 벗어나지는 않지만 상세 신청 절차·처리 기한·오류 대응이 소개 문구에 비해 길다. 권한 작업이나 조회를 실제로 수행한다고 주장하지는 않았다.

- 필수 3: missing — 조회·신청·부여는 부인했지만 권한 변경·승인도 직접 할 수 없다는 범위가 빠졌다.

복구 ID: final-1-A022; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 partial / 가독성 partial / 구조 partial / 중대한 오류 False

팀원 안내 문구로는 이렇게 소개하실 수 있습니다.

권한 신청 전에 사내비에 필요한 시스템과 업무를 알려주시면, 관련 신청 절차와 준비할 항목을 확인하는 데 활용할 수 있습니다. 권한 신청은 이음 포털의 IT > 접근 권한에서 시스템명, 필요한 역할, 업무 사유, 시작일과 종료일을 적어 진행합니다. 팀장이 업무 필요를 확인하고 시스템 담당자가 역할과 기술 조건을 검토합니다. 고객 운영 환경·기밀 자료·개인정보 접근에는 자료 소유자와 보안·개인정보 담당자의 확인도 필요합니다.

사내비가 개인별 권한 부여 여부를 대신 조회하거나 신청을 처리할 수는 없습니다. 신청 후에는 이음 포털에서 본인 요청의 처리 결과를 확인해 주세요. 접근이 되지 않으면 로그인한 회사 계정, 파일·시스템 주소, 필요한 업무 역할과 오류 시각을 확인한 뒤 #it-helpdesk에 문의하시면 됩니다.

판정: 질문의 권한 신청 사례에는 답하지만 소개 문구의 회사 문서 기반 범위와 직접 처리 한계 일부가 빠지고 오류 해결 절차가 길다.

- 필수 1: missing — 권한 신청 활용만 설명해 회사 업무 정보·절차 전반의 안내 범위를 소개하지 않았다.
- 필수 2: missing — 신청 경로와 검토 역할은 상세히 말했지만 회사 문서에 근거해 설명한다는 점은 제시하지 않았다.
- 필수 3: missing — 개별 조회와 신청 처리는 부정했으나 직접 권한 부여·변경·승인을 할 수 없다는 전체 한계가 빠졌다.

복구 ID: final-2-A020; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 partial / 가독성 partial / 구조 partial / 중대한 오류 False

팀원들에게는 이렇게 소개하실 수 있습니다.

“권한을 신청하기 전에 사내비에 필요한 시스템과 업무 역할을 알려 주시면, 신청에 적을 항목과 승인 절차를 정리하는 데 활용할 수 있습니다. 권한 신청은 이음 포털의 IT > 접근 권한에서 시스템명, 필요한 역할, 업무 사유, 시작일과 종료일을 입력해 진행합니다. 팀장과 시스템 담당자가 확인하며, 고객 운영 환경·기밀 자료·개인정보 접근에는 자료 소유자와 보안·개인정보 담당자의 확인도 필요할 수 있습니다. 사내비는 절차를 안내하지만 실제 신청이나 권한 부여는 처리하지 않습니다.”

개인별 계정에 권한이 이미 부여됐는지는 사내비가 대신 조회할 수 없습니다. 신청한 권한의 처리 결과는 이음 포털에서 확인해 주세요. 접근이 되지 않는다면 로그인한 회사 계정, 시스템 주소, 필요한 역할과 오류 시각을 확인한 뒤 #it-helpdesk에 문의하실 수 있습니다.

판정: 한계는 분명하나 소개 문구 뒤에 개인별 접근 오류 진단과 문의 경로까지 붙어 복사해 쓸 소개로는 길다.

- 필수 3: missing — 신청 대행·권한 부여와 개인별 조회는 부정하지만 권한 변경·승인도 직접 하지 않는다는 경계는 명시하지 않는다.

복구 ID: final-3-A015; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 partial / 가독성 partial / 구조 partial / 중대한 오류 False

팀원들에게는 이렇게 소개하실 수 있습니다. “권한 신청 전에 사내비에 문의하면 관련 절차와 신청에 필요한 정보, 검토 주체를 안내받을 수 있습니다. 다만 실제 신청이나 개인별 권한 상태 확인은 대신할 수 없습니다.”

시스템 권한은 이음 포털의 **IT > 접근 권한**에서 시스템명, 필요한 역할, 업무 사유, 시작일과 종료일을 적어 신청합니다. 팀장이 업무 필요를 확인하고 시스템 담당자가 역할 범위와 기술 조건을 검토합니다. 고객 운영 환경·기밀 자료·개인정보 접근에는 자료 소유자와 보안·개인정보 담당자의 확인도 필요합니다. 필수 확인이 끝나면 IT운영팀이 2영업일 안에 처리하거나 지연 사유를 남기며, 신청자는 포털에서 처리 결과를 확인합니다.

사내비는 권한이 이미 부여됐는지 대신 조회할 수 없으므로, 개인별 상태는 포털에서 직접 확인해 주세요. 권한 부여를 확인하기 전에는 다른 사람의 계정으로 대신 작업하지 마세요.

판정: 소개 문구보다 신청 상세·처리 기한·오류 대응까지 길게 설명해 핵심 소개와 후속 질문이 흐려진다. 근거 없는 상태 조회나 권한 조작 주장은 없다.

- 필수 3: missing — 개별 상태 조회는 부인했으나 직접 권한 부여·변경·승인을 할 수 없다는 한계를 모두 밝히지 않았다.
- 필수 4: missing — 팀원에게 구체적인 시스템이나 권한 질문을 알려 달라는 후속 요청이 없다.

복구 ID: final-1-A020; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 partial / 가독성 partial / 구조 partial / 중대한 오류 False

팀원들에게는 이렇게 소개하시면 됩니다.

“사내비는 사내 문서에 근거해 업무 절차와 승인된 도구의 사용 범위를 안내합니다. 권한을 신청하기 전에 해당 도구에서 허용되는 자료와 신청에 필요한 정보·확인 단계를 알아보는 데 활용할 수 있습니다. 다만 실제 권한 신청이나 개인별 권한 조회는 대신할 수 없습니다.”

예를 들어 사내비에 해당 시스템의 신청 절차, 필요한 역할과 승인 확인 단계를 물어보세요. 권한 신청은 이음 포털의 **IT > 접근 권한**에서 시스템명, 필요한 역할, 업무 사유, 시작일과 종료일을 적어 요청합니다. 팀장과 시스템 담당자가 확인하며, 고객 운영 환경·기밀 자료·개인정보 접근에는 자료 소유자와 보안·개인정보 담당자의 확인도 필요할 수 있습니다. 승인 전에는 접근을 시도하지 마세요.

사내비가 이미 권한이 부여됐는지 대신 확인할 수는 없습니다. 신청 결과는 포털에서 확인하시고, 접근이 안 되면 로그인한 회사 계정·시스템 주소·필요한 역할·오류 시각을 확인해 보세요. 원인이 불분명하면 민감한 내용을 복사해 보내지 말고 **#it-helpdesk**에 문의하시면 됩니다. 자세한 기준은 「시스템 접근 권한 신청과 회수」와 「승인된 업무 도구와 데이터 범위」에 안내되어 있습니다.

판정: 핵심 안내는 맞지만 권한 처리 한계의 일부가 빠졌고, 긴 신청·오류 해결 절차가 소개 문구의 초점을 흐린다.

- 필수 3: missing — 조회와 신청 대행 불가는 말했으나 직접 부여·변경·승인을 할 수 없다는 전체 경계는 명시하지 않았다.

복구 ID: final-2-A003; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 partial / 가독성 partial / 구조 partial / 중대한 오류 False

팀원 안내: 권한을 신청하기 전에 사내비에 필요한 시스템·자료와 하려는 업무를 설명하면, 관련 절차를 바탕으로 신청할 권한 범위와 신청 항목, 승인에 필요한 확인 단계를 안내받을 수 있습니다. 예를 들어 “이 업무를 위해 어떤 시스템 권한이 필요하고 어디서 신청하나요?”라고 물어보세요.

일반 시스템 권한은 이음 포털의 IT > 접근 권한에서 시스템명, 필요한 역할, 업무 사유, 시작일과 종료일을 적어 신청합니다. 팀장과 시스템 담당자 확인이 필요하고, 고객 운영 환경·기밀 자료·개인정보 접근에는 자료 소유자와 보안·개인정보 담당자 확인도 필요할 수 있습니다. 필수 확인이 끝나기 전에는 접근을 시도하지 않습니다. 사내비는 신청을 대신 제출하거나 개인 계정의 현재 권한을 조회할 수 없습니다. 신청 후에는 포털의 처리 결과와 실제 접근 여부를 직접 확인해 주세요. 접근이 안 되면 로그인 계정, 시스템·파일 주소, 필요한 역할과 오류 시각을 확인하고, 원인을 구분하기 어려우면 민감한 정보를 포함하지 않고 #it-helpdesk에 문의하세요. (「시스템 접근 권한 신청과 회수」, 「Google Drive 저장·공유·접근 문제 해결」)

판정: 요청 전 활용 예는 있지만 긴 신청·오류 해결 절차가 소개 문구의 범위를 넘고 직접 변경/승인 한계가 빠졌다.

- 필수 3: missing — 신청 대행과 실시간 조회는 부정하지만 직접 권한 부여·변경·승인도 하지 않는다는 경계는 명시하지 않는다.

복구 ID: final-3-A019; 호출별 시간·사용량: 미복구.

### H03 — 방문객 등록은 어디에서 언제까지 해야 해?

**필수 기준**

1. State the portal route as 총무 > 방문객 등록.
2. State the deadline as one business day before the visit.

**근거**

- ieum-014: 방문일 1영업일 전까지 이음 포털의 **총무 > 방문객 등록**에 방문객 이름, 소속, 목적, 예정 시간과 동행자를 입력한다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

방문 주관자가 이음 포털의 **총무 > 방문객 등록**에서 방문일 1영업일 전까지 등록하시면 됩니다.

판정: 짧은 문장 안에서 경로와 마감이 모두 쉽게 확인된다.


복구 ID: final-1-A018; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

방문 주관자가 이음 포털의 **총무 > 방문객 등록**에서 방문일 1영업일 전까지 등록하시면 됩니다. 당일 긴급 방문은 방문객 도착 전에 총무 담당자와 팀장의 확인을 받아야 합니다. (「방문객 등록과 동행」)

판정: 직접 답한 뒤 관련 긴급 방문 확인 조건을 덧붙였고 그 내용도 snapshot과 맞는다.


복구 ID: final-2-A024; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

방문 주관자가 이음 포털의 **총무 > 방문객 등록**에서 방문일 1영업일 전까지 등록하면 됩니다. 당일 긴급 방문은 방문객이 도착하기 전에 총무 담당자와 팀장의 확인을 받아야 합니다.

판정: 경로와 기한을 빠르게 찾을 수 있다. 당일 긴급 방문 예외도 근거가 있다.


복구 ID: final-3-A011; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음 포털의 **총무 > 방문객 등록**에서 방문일 1영업일 전까지 등록하시면 됩니다. 당일 긴급 방문은 방문객이 도착하기 전에 총무 담당자와 팀장의 확인을 받아야 합니다.

판정: 요청한 경로와 기한이 바로 보이며, 추가한 당일 긴급 방문 조건도 snapshot에 있다.


복구 ID: final-1-A014; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음 포털의 **총무 > 방문객 등록**에서 방문일 1영업일 전까지 등록하시면 됩니다. 당일 긴급 방문은 방문객 도착 전에 총무 담당자와 팀장의 확인을 받아야 하며, 등록이나 확인이 끝나지 않은 방문객은 제한 구역에 들어갈 수 없습니다.

판정: 정답이 먼저 보이며 추가한 긴급 방문 조건도 snapshot과 일치한다.


복구 ID: final-2-A007; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

방문 주관자가 방문일 1영업일 전까지 이음 포털의 **총무 > 방문객 등록**에서 등록합니다. 당일 긴급 방문은 방문객 도착 전에 총무 담당자와 팀장의 확인을 받아야 합니다.

판정: 직접 답하고 당일 긴급 방문의 확인 조건도 근거에 맞게 덧붙인다.


복구 ID: final-3-A017; 호출별 시간·사용량: 미복구.

### H04 — 소프트웨어 구매를 추진하려고 해. 신청부터 계약 전 승인까지 순서와 금액별 승인 기준을 알려줘.

**필수 기준**

1. Submit through 이음 포털 재무 > 업무 구매 before ordering, signing, or paying, including purpose, quantity, expected total, budget code, supplier, and recurring cost.
2. Under 300,000 KRW: team lead; 300,000 to under 2,000,000 KRW: team lead and Finance; 2,000,000 KRW or more: three comparable quotes plus written approval by both.
3. Software/cloud/customer-data services also need IT operations and security/privacy review before contract/payment.
4. Approval does not automatically grant a service account or permission.

**근거**

- ieum-021: 업무 물품, 외부 서비스, 소프트웨어는 주문·서명·결제 전에 이음 포털의 **재무 > 업무 구매**로 신청한다.
- ieum-021: | 세금 포함 예상 총액 | 필요한 승인 | |---|---| | 300,000원 미만 | 팀장 | | 300,000원 이상, 2,000,000원 미만 | 팀장과 재무팀 모두 | | 2,000,000원 이상 | 비교 가능한 견적 3곳과 팀장·재무팀의 서면 승인 |
- ieum-021: 소프트웨어, 클라우드 서비스, 네트워크 장비 또는 고객 정보를 다루는 서비스는 계약·결제 전에 IT운영팀과 보안·개인정보 담당자의 검토를 받는다.
- ieum-021: 구매 검토가 끝났다는 사실만으로 서비스 계정·권한이 자동 발급되지는 않는다.

#### examples_answer_scope_v5 · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

소프트웨어 구매는 **주문·계약·결제 전에** 이음 포털의 **재무 > 업무 구매**에서 신청합니다. 신청에는 목적, 수량, 세금 포함 예상 총액, 예산 코드, 공급업체, 반복 유지 비용을 적고, 소프트웨어의 데이터 종류·사용 인원·계약 조건·자동 갱신·자료 반환 및 삭제 방식도 기재합니다.

금액별 승인 기준은 다음과 같습니다.
- **세금 포함 300,000원 미만:** 팀장 승인
- **300,000원 이상, 2,000,000원 미만:** 팀장과 재무팀 모두 승인
- **2,000,000원 이상:** 비교 가능한 견적 3곳과 팀장·재무팀의 서면 승인이 필요합니다.

소프트웨어는 금액과 별도로 계약·결제 전에 **IT운영팀과 보안·개인정보 담당자의 검토**도 받아야 합니다. 견적 3곳을 받기 어려운 단일 공급 구매는 사유와 대안을 적고 재무팀의 별도 승인을 요청합니다. 승인 기준을 피하려고 구매를 여러 건으로 나누면 안 됩니다. 관련 안내는 「업무용 구매와 공급업체 선택」과 「출장·구매·정산 실무 안내」를 참고하세요.

판정: 신청·금액별 승인·기술 검토 순서가 명확하고 구간도 읽기 쉽지만 계정·권한 경계가 누락됐다.

- 필수 4: missing — 구매 승인이 서비스 계정이나 접근 권한을 자동으로 주지 않는다는 경계를 말하지 않았다.

복구 ID: final-1-A008; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

소프트웨어 구매는 **주문·계약·결제 전에** 아래 절차를 진행하시면 됩니다.

1. 이음 포털 **재무 > 업무 구매**에 목적, 수량, 세금 포함 예상 총액, 예산 코드, 공급업체, 반복 유지 비용을 적어 신청합니다.
2. 소프트웨어·클라우드 서비스 등은 계약·결제 전에 **IT운영팀과 보안·개인정보 담당자의 기술·정보 처리 검토**도 받아야 합니다. 새 유료 도구나 목록에 없는 서비스, 외부 업로드·연동이 포함되면 **IT > 소프트웨어 요청**도 별도로 접수합니다. 이 신청과 구매 신청의 선후 순서는 정해져 있지 않지만, 관련 검토와 승인이 계약·결제 전에 기록되어야 합니다.
3. 예상 총액별 승인 기준은 다음과 같습니다.
   - **300,000원 미만:** 팀장 승인
   - **300,000원 이상, 2,000,000원 미만:** 팀장과 재무팀 모두 승인
   - **2,000,000원 이상:** 비교 가능한 견적 3곳과 팀장·재무팀의 서면 승인. 단일 공급처라 3개 견적을 받을 수 없다면 사유와 대안을 적고 재무팀의 별도 승인을 받습니다.

이는 「업무용 구매와 공급업체 선택」 및 「승인된 업무 도구와 데이터 범위」의 절차입니다.

판정: 구매 신청, 기술·정보 검토, 금액별 승인과 계약·결제 전 완료 조건은 보존했다. 두 신청의 선후가 정해져 있지 않다는 표현은 전체 snapshot에 명시된 규칙이 아니라 근거가 확인되지 않는 단정으로 남는다. 다만 승인 전 구매를 허용하거나 승인 주체·금액 구간을 바꾸지는 않았으며, 구매 승인이 계정·권한을 자동 부여하지 않는다는 required 항목이 빠져 content는 partial이다.

- 필수 4: missing — 구매 승인이 서비스 계정이나 권한을 자동으로 부여하지 않는다는 조건은 빠졌다.

복구 ID: final-2-A023; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

소프트웨어 구매는 주문·계약·결제 전에 신청과 해당 검토·승인을 모두 마쳐야 합니다. 「업무용 구매와 공급업체 선택」 기준은 다음과 같습니다.

1. 이음 포털의 **재무 > 업무 구매**에서 신청합니다. 목적, 수량, 세금 포함 예상 총액, 예산 코드, 공급업체, 반복 유지 비용을 적습니다. 소프트웨어는 데이터 종류, 사용자 수, 계약 조건, 자동 갱신 여부, 자료 반환·삭제 방식과 총비용도 기재합니다.
2. 계약·결제 전에 **IT운영팀과 보안·개인정보 담당자**의 기술·정보 처리 검토를 받습니다. 이 검토는 금액별 승인과 별도로 필요합니다.
3. 세금 포함 예상 총액에 따라 승인받습니다.
   - **300,000원 미만:** 팀장 승인
   - **300,000원 이상, 2,000,000원 미만:** 팀장과 재무팀 모두 승인
   - **2,000,000원 이상:** 비교 가능한 견적 3곳과 팀장·재무팀의 서면 승인

2,000,000원 이상인데 단일 공급업체라 비교 견적 3곳을 받을 수 없다면 사유와 대안을 적고 재무팀의 별도 승인을 받아야 합니다. 승인 기준을 피하려고 신청을 나누면 안 되며, 필요한 검토와 승인이 기록되기 전에는 계약하거나 결제하지 마세요.

판정: 신청 순서와 세 금액 구간은 정확하지만 승인과 계정 발급의 별도성을 빠뜨렸다.

- 필수 4: missing — 구매 승인이 계정이나 권한을 자동 부여하지 않는다는 경계가 없다.

복구 ID: final-3-A008; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

소프트웨어 구매는 주문·계약 서명·결제 전에 신청과 필요한 승인을 모두 마쳐야 합니다.

1. 이음 포털 **재무 > 업무 구매**에서 목적, 수량, 세금 포함 예상 총액, 예산 코드, 공급업체, 반복 유지 비용을 적어 신청합니다. 승인 기준을 피하려고 요청을 여러 건으로 나누면 안 됩니다.
2. 예상 총액에 따라 승인받습니다.
   - **300,000원 미만:** 팀장 승인
   - **300,000원 이상~2,000,000원 미만:** 팀장과 재무팀 모두 승인
   - **2,000,000원 이상:** 비교 가능한 견적 3곳과 팀장·재무팀의 서면 승인
   - 단일 공급업체라 비교 견적 3곳을 받을 수 없다면 사유와 대안을 적고 재무팀의 별도 승인을 받습니다.
3. 소프트웨어는 계약·결제 전에 **IT운영팀과 보안·개인정보 담당자의 검토도** 받아야 합니다. 신청에는 데이터 종류, 사용 인원, 계약 조건, 자동 갱신, 자료 반환·삭제 방식과 총비용을 포함합니다. 구매 승인과 기술·정보 처리 검토가 모두 확인되기 전에는 계약하거나 결제하지 마세요.

구매 신청·금액별 승인은 「업무용 구매와 공급업체 선택」, 소프트웨어 검토 항목은 「출장·구매·정산 실무 안내」에 안내되어 있습니다.

판정: 구매 승인 단계와 기준은 모두 맞지만 필수 권한 경계가 누락됐다.

- 필수 4: missing — 구매 승인이 계정·권한을 자동 부여하지 않는다는 제한이 빠졌다.

복구 ID: final-1-A017; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

소프트웨어 구매는 주문·계약 서명·결제 전에 필요한 검토와 승인을 모두 받아야 합니다.

1. 이음 포털의 **재무 > 업무 구매**에서 목적, 수량, 세금 포함 예상 총액, 예산 코드, 공급업체, 반복 유지 비용을 신청합니다. 소프트웨어는 추가로 데이터 종류, 사용 인원, 계약 조건, 자동 갱신 여부, 자료 반환·삭제 방식과 총비용을 기재합니다.
2. 계약·결제 전에 **IT운영팀과 보안·개인정보 담당자**의 기술·정보 처리 검토를 받습니다.
3. 세금 포함 예상 총액에 따라 아래 승인과 견적 요건을 충족합니다.
   - **300,000원 미만:** 팀장 승인
   - **300,000원 이상, 2,000,000원 미만:** 팀장과 재무팀 모두 승인
   - **2,000,000원 이상:** 비교 가능한 견적 3곳과 팀장·재무팀의 서면 승인
4. 필요한 검토와 승인이 기록된 뒤 주문·계약·결제를 진행합니다.

단일 공급 구매라 비교 견적 3곳을 받을 수 없다면 그 사유와 대안을 적고 재무팀의 별도 승인을 받아야 합니다. 승인 기준을 피하려고 구매 요청을 여러 건으로 나누면 안 됩니다.

판정: 신청·검토·금액 기준 순서는 명확하지만 승인과 계정 발급의 분리 조건을 누락했다.

- 필수 4: missing — 구매 승인이 서비스 계정이나 권한을 자동 발급하지 않는다는 경계가 없다.

복구 ID: final-2-A017; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

소프트웨어 구매는 **주문·계약 서명·결제 전에** 이음 포털의 **재무 > 업무 구매**에서 신청합니다.

1. 신청서에 목적, 수량, 세금 포함 예상 총액, 예산 코드, 공급업체, 반복 유지 비용을 적습니다. 소프트웨어는 데이터 종류, 사용 인원, 계약 조건, 자동 갱신 여부, 자료 반환·삭제 방식과 총 비용도 기재합니다.
2. 세금 포함 예상 총액에 따라 승인을 받습니다.
   - **300,000원 미만:** 팀장 승인
   - **300,000원 이상~2,000,000원 미만:** 팀장과 재무팀 모두 승인
   - **2,000,000원 이상:** 비교 가능한 견적 3곳과 팀장·재무팀의 서면 승인
3. 금액과 관계없이 소프트웨어는 **계약·결제 전에 IT운영팀과 보안·개인정보 담당자의 검토**도 받아야 합니다. 비교 견적 3곳을 받을 수 없는 단일 공급 구매라면 사유와 대안을 적고 재무팀의 별도 승인을 받습니다.

해당 승인과 검토가 모두 끝나기 전에는 주문·계약 서명·결제를 진행하지 마세요. 승인 기준을 피하려고 구매 요청을 나누면 안 됩니다. (「업무용 구매와 공급업체 선택」)

판정: 금액 기준과 선행 검토는 명확하지만 승인과 접근 권한은 별도라는 경계가 없다.

- 필수 4: missing — 승인만으로 서비스 계정/권한이 자동 발급되지 않는다는 점을 빠뜨렸다.

복구 ID: final-3-A016; 호출별 시간·사용량: 미복구.

### H05 — 작은 코드 변경을 배포하려고 해. 변경을 시작한 뒤 운영 반영까지 무엇을 확인해야 하는지 순서대로 정리해줘.

**필수 기준**

1. Record change purpose, affected users/components, compatibility, and data effects before work.
2. Submit a PR and complete required automated checks and independent review; a PR is not itself approval.
3. Use approved deployment automation/runbook only after required merge/approval/checks.
4. After deployment, verify service owner’s stated normal conditions; do not call deployment successful before verification.

**근거**

- ieum-067: 먼저 연결된 GitHub 이슈 또는 변경 목적을 기록한다. 어떤 동작이 바뀌는지, 영향을 받는 사용자와 구성 요소, 기존 호환성, 데이터 변경 여부를 확인한다.
- ieum-067: 최소 독립 승인 1건과 저장소에서 지정한 필수 검사 통과가 모두 필요하다.
- ieum-068: 배포는 해당 저장소·서비스가 승인한 자동화나 runbook에 적힌 방법으로만 수행한다.
- ieum-068: 확인 전에 “배포 성공”이나 고객 문제 해결을 선언하지 않는다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

작은 변경이라도 코드 리뷰와 배포 전후 확인은 생략되지 않습니다. 순서는 다음과 같습니다.

1. **변경 범위 정리:** 연결할 GitHub 이슈나 변경 목적을 기록하고, 바뀌는 동작, 영향받는 사용자·구성요소, 호환성 및 데이터 변경 여부를 확인합니다. 테스트에는 합성 데이터를 우선 사용하고, 운영자료가 필요하면 승인된 접근 절차와 최소 권한을 따릅니다.
2. **PR 작성:** 변경 이유와 범위, 주요 파일·데이터·설정, 실제 실행한 검사와 결과, 실행하지 못한 검사의 사유를 적습니다. 실패 시 동작과 복구 가능성, 배포 후 확인할 정상 조건과 담당 역할도 기록합니다.
3. **독립 리뷰와 검사:** 작성자와 다른 사람의 독립 리뷰를 최소 1건 받고 저장소의 필수 자동 검사를 모두 통과시킵니다. 인증·권한, 고객 데이터, 개인정보, 데이터 변경 등 위험 변경이면 서비스 책임자의 추가 확인도 받습니다. 필수 검사나 저장소 설정을 확인할 수 없으면 확인 전 병합하지 않습니다.
4. **병합:** 해결되지 않은 차단 의견이 없는지 확인하고, PR을 통해서만 `main`에 병합합니다. 리뷰 승인과 필수 검사 통과가 모두 필요합니다.
5. **배포 전 준비:** 일반 배포 시간은 평일 10:00~16:00입니다. 배포 담당자와 서비스 소유 팀, 영향받는 다른 팀과의 협의를 확인하고, 대상·사용자 영향·의존성·데이터 변경 순서를 점검합니다. 정상 확인 방법, 중단 조건, 승인된 복구 경로와 결정 권한자도 정합니다. 데이터 변경이 되돌릴 수 없거나 복구 방안이 확인되지 않으면 배포를 시작하지 않습니다.
6. **운영 반영과 기록:** 해당 저장소·서비스에서 승인된 자동화나 runbook에 적힌 방법만 사용합니다. 기록에는 PR·버전, 담당 역할, 환경, 시작·종료 시각, 검사 결과와 실제 차이·후속 작업을 남깁니다.
7. **배포 후 확인:** 서비스 소유자가 정한 정상 조건을 확인합니다. 확인 방법이나 관찰 시간이 정해져 있지 않다면 배포 전에 담당자가 정해야 합니다. 확인이 끝나기 전에는 배포 성공이나 고객 문제 해결을 선언하지 않습니다. 이상 징후가 있으면 사전에 정한 중단·복구 경로를 따르세요. 실패 시 세부 처리 단계는 현재 확인하기 어렵습니다.

근거는 「개발 변경과 코드 리뷰」 및 「배포·실패·롤백 안내」입니다.

판정: 요청한 단계가 순서대로 구분된다. 실패 처리에 관한 짧은 한계 설명은 비정상적으로 작성된 snapshot 문구를 정책으로 확장하지 않았다.


복구 ID: final-1-A015; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

‘개발 변경과 코드 리뷰’ 및 ‘배포·실패·롤백 안내’ 기준으로 다음 순서로 확인하시면 됩니다.

1. **변경 범위와 목적을 정리합니다.** 연결된 GitHub 이슈나 변경 목적을 기록하고, 바뀌는 동작과 영향받는 사용자·구성요소, 호환성, 데이터 변경 여부를 확인합니다. 한 번에 안전하게 검토하기 어려운 범위라면 독립적으로 확인할 수 있게 나눕니다.
2. **변경과 검증을 준비합니다.** 고객 자료·비밀번호·토큰 등은 코드나 테스트 자료에 넣지 말고 합성 데이터를 우선 사용합니다. 새 의존성이 있으면 출처·라이선스·권한·보안 위험과 검사를 확인합니다. 별도 도구나 관리자 권한이 필요한 설치는 해당 검토를 먼저 받아야 합니다.
3. **PR을 작성합니다.** 연결 이슈와 변경 이유, 사용자에게 보이는 변경, 주요 파일·데이터·설정, 실행한 검사와 결과, 실행하지 못한 검사의 사유, 실패 시 동작과 복구 가능성, 위험 검토, 배포 후 정상 여부를 확인할 조건과 담당 역할을 적습니다. 실행하지 않은 검사를 통과했다고 표시하지 않습니다.
4. **리뷰와 병합 조건을 확인합니다.** 작성자와 다른 사람의 독립 리뷰 1건 이상과 필수 자동 검사 통과가 필요합니다. 권한·인증, 고객 데이터, 데이터 삭제·마이그레이션, 청구, 암호화, 외부 전송, 공개 API 호환성, 공통 배포·복구 절차에 영향을 주면 서비스 책임자의 추가 확인도 받습니다. 차단 의견이나 필수 확인이 남아 있으면 병합하지 않습니다. `main`은 PR을 통해서만 변경하며, 저장소의 필수 검사와 보호 설정이 실제로 확인되지 않으면 저장소 관리자에게 확인합니다.
5. **배포 전 준비를 점검합니다.** 일반 배포 시간은 평일 10:00~16:00입니다. 배포 담당자와 서비스 소유 제품개발팀, 필요한 타 팀 협의, 변경 영향과 데이터 변경 순서, 배포 직후 확인할 정상 조건, 중단 조건, 승인된 복구 경로와 결정 권한자를 정합니다. 데이터 변경을 코드만 되돌려 복구할 수 있는지도 별도로 확인하고, 복구 방안이 불분명하면 배포를 시작하지 않습니다. 고객 문의나 장애가 진행 중이면 담당자에게 일정과 위험을 알립니다.
6. **승인된 방법으로 배포합니다.** 해당 저장소·서비스에서 승인한 자동화나 runbook만 사용합니다. 접근 권한이 없으면 다른 사람의 계정으로 우회하지 말고 서비스 소유자와 IT운영팀에 요청합니다. 배포 식별자, 담당 역할, 환경, 시작·종료 시각과 실제 검사 결과를 기록합니다.
7. **운영 반영 결과를 확인합니다.** 서비스 소유자가 정한 정상 조건을 확인하고, 오류·지연·데이터 이상과 후속 작업을 기록합니다. 확인 창구·관찰 시간·지표가 정해져 있지 않다면 배포 전에 정해 기록해야 합니다. 실제 확인 전에는 배포 성공이나 고객 문제 해결을 선언하지 않습니다.

변경 규모가 작더라도 위험 변경 여부는 변경의 종류와 영향으로 확인해야 합니다. 실제 배포 명령이나 특정 도구 사용법은 해당 서비스의 승인된 runbook과 현재 설정을 확인해야 합니다.

판정: 세부 내용은 많지만 각 단계가 명확히 순서화되어 있고 필수 검증 경계가 정확하다.


복구 ID: final-2-A013; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

작은 변경도 문서상 코드 변경·배포의 기본 흐름에 따라 다음을 확인하세요.

1. **변경 범위 확인:** 연결된 GitHub 이슈나 변경 목적을 기록하고, 바뀌는 동작·영향받는 사용자와 구성요소·호환성·데이터 변경 여부를 확인합니다. 범위가 커서 안전하게 검토하기 어렵다면 나눕니다. 테스트에는 합성 데이터를 우선 사용하고 고객 자료나 비밀정보를 코드·이슈·PR에 넣지 않습니다.
2. **PR 작성:** 연결 이슈와 변경 이유, 사용자에게 보이는 변경, 수정 파일·데이터·설정, 실제 실행한 검사 결과, 실패 시 동작과 복구 가능성, 보안·개인정보·의존성 위험, 배포 후 확인할 조건과 담당 역할을 적습니다. 실행하지 않은 검사를 통과했다고 표시하지 않습니다.
3. **리뷰와 병합:** 작성자와 다른 사람의 독립 리뷰 최소 1건과 필수 자동 검사 통과를 확인합니다. 권한·고객 데이터·삭제·청구·외부 전송 등 위험 변경이면 서비스 책임자의 추가 확인도 필요합니다. 차단 의견이나 필수 확인이 남아 있으면 병합하지 않고, `main`에는 PR을 통해서만 반영합니다. 저장소의 필수 검사나 보호 설정을 확인할 수 없으면 활성화됐다고 가정하지 말고 저장소 관리자에게 확인합니다.
4. **배포 전 점검:** 일반 배포 시간은 평일 10:00~16:00입니다. PR 병합·리뷰·검사 상태, 배포 담당자와 서비스 소유 팀, 다른 팀과의 협의 여부를 확인합니다. 변경 대상과 사용자 영향, 데이터 변경 순서, 정상 상태를 확인할 방법, 중단 조건·복구 경로·결정 권한자를 정합니다. 데이터 변경을 코드만 되돌려 복구할 수 있는지도 확인하고, 복구 방안이 불명확하면 시작하지 않습니다. 진행 중인 고객 문의나 장애가 있으면 담당자에게 일정과 위험을 알립니다.
5. **배포 실행과 기록:** 해당 서비스가 승인한 자동화나 runbook으로만 배포합니다. 권한이 없으면 서비스 소유자와 IT운영팀에 요청하고 다른 사람 계정으로 우회하지 않습니다. PR·버전, 환경, 담당 역할, 시작·종료 시각, 실제 검사 결과와 후속 작업을 기록합니다.
6. **운영 반영 확인:** 서비스 소유자가 정한 정상 조건과 관찰 방법으로 결과를 확인합니다. 확인 창구·관찰 시간·지표가 정해져 있지 않다면 배포 전에 정하고 기록합니다. 확인 전에는 배포 성공이나 고객 문제 해결을 선언하지 않습니다. PR 병합만으로 운영 반영이나 문제 해결이 완료된 것은 아닙니다.

참고로 「배포·실패·롤백 안내」의 ‘실패 또는 이상 징후’ 항목에는 기술적 복구 절차가 확인되지 않아, 실패 후의 구체적인 조치 방법은 현재 확인하기 어렵습니다. 위 순서는 「개발 변경과 코드 리뷰」와 「배포·실패·롤백 안내」의 내용입니다.

판정: 요청된 흐름을 순서대로 제시한다. 실패 섹션의 이상 문구를 기술 복구 절차로 보지 않은 판단은 자료 경계 검토에 기록했다.


복구 ID: final-3-A018; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

작은 변경이라도 아래 순서와 확인 기준은 동일하게 적용됩니다.

1. **변경 시작 전**: 연결된 GitHub 이슈나 변경 목적을 기록하고, 바뀌는 동작·영향받는 사용자와 구성 요소·호환성·데이터 변경 여부를 확인합니다. 테스트에는 합성 자료를 우선 사용하고 고객 자료나 자격정보를 코드·이슈·PR에 넣지 않습니다.
2. **PR 작성**: 연결 이슈와 변경 이유, 사용자에게 보이는 변화, 주요 파일·데이터·설정, 실제 실행한 검사와 실행하지 못한 검사의 사유, 실패 시 동작·복구 가능성, 보안·개인정보·의존성 위험, 배포 후 정상 확인 조건과 담당 역할을 적습니다.
3. **리뷰와 병합**: 작성자와 다른 사람의 독립 승인 1건 이상과 필수 자동 검사 전체 통과를 확인하고, 해결되지 않은 차단 의견이 있으면 병합하지 않습니다. 권한·인증, 고객 데이터, 삭제·마이그레이션, 청구, 암호화, 외부 전송, 공개 API 호환성, 공통 배포·복구 절차에 영향이 있으면 서비스 책임자의 추가 확인도 받습니다. `main`에는 PR로만 반영하며, 보호 설정이나 검사 상태를 확인할 수 없으면 저장소 관리자에게 확인합니다.
4. **배포 전 준비**: 일반 배포 시간은 평일 10:00~16:00입니다. PR 병합·승인·검사 결과, 배포 담당자와 서비스 소유 제품개발팀, 변경 영향·의존성·데이터 변경, 다른 팀과의 협의 여부를 확인합니다. 적용 직후의 정상 조건과 확인 방법, 중단 조건, 안전한 이전 버전 또는 대체 복구 경로, 결정 권한자도 정합니다. 데이터 변경은 코드 롤백만으로 데이터가 복구되는지 별도로 확인하고, 복구 방안이 불명확하면 배포를 시작하지 않습니다. 진행 중인 고객 문의나 장애가 있으면 담당자에게 일정과 위험을 알립니다.
5. **운영 반영**: 해당 저장소·서비스에서 승인된 자동화나 runbook에 적힌 방법만 사용합니다. 기록에는 PR·버전, 환경, 담당 역할, 시작·종료 시각, 실제 검사 결과와 차이를 남깁니다.
6. **반영 후 확인**: 서비스 소유자가 사전에 정한 정상 조건을 확인합니다. 관찰 시간이나 측정 지표가 정해져 있지 않다면 배포 전에 담당자와 정해 기록합니다. 확인 전에는 배포 성공이나 고객 문제 해결을 선언하지 않습니다.

진행 중인 서비스 장애의 피해를 줄이기 위한 긴급 변경이라면 일반 배포 시간표 대신 사고 지휘자의 승인과 긴급 변경 절차를 따릅니다. (「개발 변경과 코드 리뷰」, 「배포·실패·롤백 안내」)

판정: 요청한 변경 시작부터 운영 확인까지 단계가 순서대로 보이며 필수 선행 조건과 성공 판정 경계가 유지됐다.


복구 ID: final-1-A004; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

작은 변경에도 별도 예외가 안내되어 있지 않아, 아래 순서로 진행하시면 됩니다.

1. **변경 범위 확인:** 연결된 GitHub 이슈나 변경 목적을 기록하고, 바뀌는 동작·영향받는 사용자와 구성 요소·호환성·데이터 변경 여부를 확인합니다. 리뷰하기 어려울 만큼 범위가 크면 독립적으로 확인할 수 있도록 나눕니다. 고객 자료와 비밀정보는 코드·이슈·PR에 넣지 않습니다.
2. **PR 작성:** 변경 이유와 범위, 주요 파일·데이터·설정, 실제 실행한 검사와 결과, 실행하지 못한 검사의 사유, 실패 시 동작과 복구 가능성 등을 적습니다. 실행하지 않은 검사를 통과했다고 표시하지 않습니다.
3. **리뷰와 검사:** 작성자와 다른 사람의 독립 리뷰 1건 이상과 저장소의 필수 자동 검사 통과를 확인합니다. 인증·권한, 고객 데이터, 삭제·마이그레이션 등 문서에 정한 위험 변경이면 서비스 책임자의 추가 확인도 필요합니다. 차단 의견이나 필수 확인이 남아 있으면 병합하지 않습니다.
4. **main 병합:** PR이 승인되고 필수 검사가 통과한 뒤 PR을 통해 병합합니다. 저장소의 보호 설정이나 검사 상태를 확인할 수 없으면 활성화된 것으로 가정하지 말고 저장소 관리자에게 확인합니다.
5. **배포 전 준비:** 일반 배포 시간인 평일 10:00~16:00에 진행할 수 있도록 배포 담당자와 서비스 책임자를 확인합니다. 변경 대상·영향·의존성·데이터 변경 순서, 배포 직후 정상 여부를 확인할 방법, 중단 조건·복구 경로·결정권자를 정합니다. 데이터 변경이 있으면 코드만 되돌렸을 때 데이터도 복구되는지 확인하고, 복구 방안이 불분명하면 배포를 시작하지 않습니다.
6. **배포:** 해당 저장소와 서비스에서 승인된 자동화 또는 runbook에 적힌 방법만 사용합니다. 문서와 실제 설정이 다르거나 도구·권한이 확인되지 않으면 추측하거나 계정을 우회하지 말고 담당자에게 확인합니다.
7. **검증과 기록:** 서비스 책임자가 사전에 정한 정상 조건을 확인하고, PR·버전, 담당자, 환경, 시작·종료 시각, 실제 검사 결과와 후속 작업을 기록합니다. 검증 전에는 배포 성공이나 문제 해결을 선언하지 않습니다.

배포 실패 시의 구체적인 기술 조치 순서는 현재 확인하기 어렵습니다. 따라서 실패에 대비해 배포 전에 중단 조건과 승인된 복구 경로를 정하고, 그 경로를 담당자와 확인해 두셔야 합니다. 관련 기준은 「개발 변경과 코드 리뷰」와 「배포·실패·롤백 안내」입니다.

판정: 요구된 단계가 순서대로 드러나며 실제 운영 검증 전 성공을 주장하지 않는다.


복구 ID: final-2-A004; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

작은 변경도 다음 순서로 확인하시면 됩니다. 기준은 「개발 변경과 코드 리뷰」와 「배포·실패·롤백 안내」입니다.
1. **변경 범위 확인:** 연결된 GitHub 이슈나 변경 목적을 기록하고, 바뀌는 동작·영향받는 사용자와 구성요소·호환성·데이터 변경 여부를 확인합니다. 코드와 테스트에 고객 자료나 비밀정보를 넣지 말고, 테스트에는 합성 자료를 우선 사용합니다.
2. **PR 작성:** 연결 이슈와 변경 이유, 주요 변경 파일·데이터·설정, 실제 실행한 검사와 결과(실행하지 못한 검사는 사유), 실패 시 동작과 되돌리기 가능성, 배포 후 확인할 정상 조건과 담당 역할을 적습니다.
3. **검토 및 병합 준비:** 작성자와 다른 사람의 독립 리뷰 1건 이상과 필수 자동 검사 통과를 확인합니다. 권한·인증, 고객 데이터, 삭제·마이그레이션 등 위험 변경이면 서비스 책임자의 추가 확인도 필요합니다. 차단 의견이나 검사 실패가 있으면 병합하지 말고, 저장소 보호·필수 검사 설정을 실제로 확인합니다.
4. **`main`에 병합:** PR을 통해서만 병합합니다. 병합은 운영 반영이나 문제 해결을 뜻하지 않습니다.
5. **배포 전 점검:** 일반 배포는 평일 10:00~16:00에 진행합니다. 배포 담당자와 서비스 책임자, 변경 영향·의존성·데이터 변경 순서, 정상 확인 방법, 중단 조건과 승인된 복구 경로 및 결정권자를 확인합니다. 다른 팀에 영향이 있거나 고객 문의·장애가 진행 중이면 관련 담당자와 일정·위험을 공유합니다.
6. **운영 반영:** 해당 저장소·서비스에서 승인한 자동화나 runbook에 적힌 방법만 사용합니다. 권한이 없거나 실제 도구 설정이 문서와 다르면 추측해 진행하지 말고 서비스 소유자와 IT운영팀에 확인합니다.
7. **결과 확인 및 기록:** 배포 기록에 PR·버전, 담당자, 환경, 시작·종료 시각, 실제 검사 결과와 후속 작업을 남깁니다. 서비스 책임자가 정한 정상 조건을 확인하고, 확인 전에는 배포 성공이나 고객 문제 해결을 선언하지 않습니다.

배포 실패 시 구체적인 기술 복구 단계는 현재 확인하기 어렵습니다. 배포 전에 정한 중단 조건과 승인된 복구 경로를 따르고, 경로가 불명확하면 임의로 복구하지 말고 서비스 책임자에게 확인하세요.

판정: 순서와 검증 조건이 보인다. 배포 실패 절차가 문서에서 확인되지 않는다는 말은 snapshot의 해당 문단이 비기술적 오류 문구이므로 환각으로 세지 않았다.


복구 ID: final-3-A009; 호출별 시간·사용량: 미복구.

### H06 — 프로젝트 잠금파일의 패키지를 설치하는 것과 브라우저 확장을 설치하는 것은 절차가 어떻게 달라?

**필수 기준**

1. For a dependency fixed in the project lockfile and installed in the approved development environment, per-install IT approval is not required; team code review/project procedures still apply.
2. A browser extension/plugin that reads account/page data or sends information externally requires IT and security/privacy review.
3. Submit such review through 이음 포털 IT > 소프트웨어 요청 and do not install/connect real data before review is recorded.

**근거**

- ieum-037: 승인된 개발환경에서 잠금파일에 고정된 의존성을 설치하는 행위 자체에 매번 별도 신청을 요구하지 않는다.
- ieum-037: 브라우저 확장·플러그인 또는 계정·페이지 내용을 읽거나 외부로 보내는 도구
- ieum-037: 이음 포털의 IT > 소프트웨어 요청에 제품·게시자·공식 배포 주소, 업무 목적, 필요한 권한·자료 접근, 비용을 적는다.
- ieum-037: 검토가 기록되기 전 설치하거나 실제 자료를 연결하지 않는다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

프로젝트 잠금파일에 고정된 패키지는 승인된 개발환경에서 프로젝트 의존성 변경으로 다룹니다. 공식 출처·목적·라이선스·새 네트워크나 권한 동작을 확인하고, 잠금파일 변경을 코드 리뷰와 프로젝트 절차에 따라 반영합니다. 고정된 의존성을 설치하는 것 자체에는 매번 별도 신청이 필요하지 않습니다.

브라우저 확장은 별도 검토 대상입니다. 이음 포털의 **IT > 소프트웨어 요청**에 제품·게시자·공식 주소, 업무 목적, 필요한 권한·자료 접근과 비용을 적어 IT운영팀 및 보안·개인정보 담당자의 검토를 받아야 합니다. 검토 결과가 기록되기 전에는 설치하거나 실제 자료를 연결하지 않습니다.

판정: 두 소프트웨어 유형을 별도 문단으로 비교해 의존성 설치 절차를 확장 설치에 적용하지 않도록 했다.


복구 ID: final-1-A006; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

승인된 개발환경에서 잠금파일에 이미 고정된 패키지를 설치하는 것 자체는 매번 별도 신청하지 않습니다. 다만 패키지를 추가하거나 버전을 바꾸는 경우에는 공식 출처·라이선스·권한 및 외부 전송 여부를 확인하고, 프로젝트 변경으로 PR을 올려 독립 리뷰와 필수 검사를 거쳐야 합니다. 관리자 권한이 필요하거나 외부 서비스·자료 연결이 포함되면 별도 검토도 필요합니다.

브라우저 확장은 별도 검토 대상입니다. 이음 포털의 **IT > 소프트웨어 요청**에 제품·게시자·공식 배포 주소, 업무 목적, 필요한 권한·자료 접근 및 비용을 적어 요청하고, IT운영팀과 보안·개인정보 담당자의 검토가 기록되기 전에는 설치하거나 실제 자료를 연결하지 않습니다.

근거: 「회사 기기 소프트웨어 설치」, 「개발 도구와 비밀정보 관리」

판정: 두 소프트웨어 유형을 분리했고 검토 전 사용·연결 금지 조건도 정확하다.


복구 ID: final-2-A001; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

승인된 개발환경에서 프로젝트 잠금파일에 고정된 패키지를 설치하는 것 자체는 매번 별도 신청하지 않습니다. 다만 패키지를 추가하거나 버전을 바꿀 때는 공식 출처·라이선스·권한·외부 전송 여부 등을 확인하고, 잠금파일 변경을 PR로 제출해 독립 리뷰와 필수 검사를 거칩니다.

브라우저 확장은 별도 검토 대상입니다. 이음 포털의 IT > 소프트웨어 요청에 제품·게시자·공식 주소, 업무 목적, 필요한 권한·자료 접근, 비용을 적고 IT운영팀과 보안·개인정보 담당자의 검토가 기록된 뒤 설치해야 합니다. 이는 확장이 계정이나 페이지 내용을 읽거나 외부로 보낼 수 있기 때문입니다.

관련 기준은 「회사 기기 소프트웨어 설치」와 「개발 도구와 비밀정보 관리」입니다.

판정: 두 소프트웨어 유형의 조건과 선행 검토를 분리해 설명한다.


복구 ID: final-3-A006; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

프로젝트 잠금파일에 이미 고정된 패키지를 승인된 개발환경에서 설치하는 것은 매번 별도 신청하지 않습니다. 새 패키지를 추가하거나 버전을 바꾸는 경우에는 공식 출처·목적·라이선스·권한 및 네트워크 동작을 확인하고, 잠금파일을 갱신해 팀 코드 리뷰와 테스트를 거쳐 프로젝트 절차에 반영합니다.

브라우저 확장은 별도 검토 대상입니다. 설치 전에 이음 포털의 **IT > 소프트웨어 요청**에 제품·게시자·공식 주소, 업무 목적, 필요한 권한·자료 접근 범위와 비용을 적어 요청하고, IT운영팀과 보안·개인정보 담당자의 검토가 기록된 뒤 설치해야 합니다. 잠금파일 패키지의 일반 설치 절차를 브라우저 확장에 적용해 바로 설치할 수는 없습니다. (「회사 기기 소프트웨어 설치」, 「개발 도구와 비밀정보 관리」)

판정: 두 경우를 분리했고 검토 전에 설치하거나 실제 자료를 연결하라고 안내하지 않았다.


복구 ID: final-1-A012; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

프로젝트 잠금파일의 패키지는 승인된 개발환경에서 프로젝트에 필요한 의존성으로 관리합니다. 공식 배포처·목적·라이선스·새 네트워크나 권한 동작을 확인하고, 변경을 잠금파일 등 의존성 기록과 함께 제안해 팀 코드 리뷰와 테스트를 거칩니다. 잠금파일에 고정된 의존성을 설치하는 것 자체는 매번 별도 신청이 필요하지 않지만, 관리자 권한 설치나 외부 서비스 연결 등은 별도 검토 대상입니다.

브라우저 확장은 별도 소프트웨어 검토가 필요합니다. 설치 전에 이음 포털의 IT > 소프트웨어 요청에 제품·게시자·공식 주소, 업무 목적, 필요한 권한·자료 접근, 비용을 적어 요청하고, IT운영팀과 보안·개인정보 담당자의 검토가 기록될 때까지 설치하거나 실제 자료를 연결하지 않습니다. 특히 계정·페이지 내용을 읽거나 외부로 보내는 확장도 이 별도 검토 대상입니다.

관련 기준은 「회사 기기 소프트웨어 설치」와 「개발 도구와 비밀정보 관리」입니다.

판정: 정상 의존성과 확장 검토의 두 경로가 분리되고 사전 검토 조건이 정확하다.


복구 ID: final-2-A021; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

프로젝트 잠금파일에 선언된 패키지는 승인된 개발환경에서 설치·갱신할 때마다 별도 IT 신청을 하지 않습니다. 다만 패키지의 출처·목적·라이선스·권한 및 외부 전송 여부를 확인하고, 잠금파일 변경과 검사 결과를 코드 리뷰 절차에 포함해야 합니다.

브라우저 확장 프로그램은 일반 패키지 설치와 달리 IT운영팀과 보안·개인정보 담당자의 별도 검토가 필요합니다. 이음 포털의 **IT > 소프트웨어 요청**에 제품·게시자·공식 주소, 목적, 필요한 권한·자료 접근과 비용을 적어 요청하고, 검토가 기록되기 전에는 설치하거나 실제 자료를 연결하지 않습니다.

관련 기준은 「회사 기기 소프트웨어 설치」와 「개발 도구와 비밀정보 관리」입니다.

판정: 유형별 조건과 선행 검토를 명확히 대비한다.


복구 ID: final-3-A012; 호출별 시간·사용량: 미복구.

### H07 — 재택근무 중 회사 자료를 출력해도 돼? 불가피한 경우와 폐기 방법도 알려줘.

**필수 기준**

1. Printing company documents at home is normally prohibited/not done.
2. If unavoidable, obtain security/privacy approval before printing and store the document locked with access limited to necessary people.
3. If storage/destruction method is not in the approval record, do not print and ask the responsible person.
4. Dispose by office secure-shred bin or approved safe pickup; not household waste or ordinary recycling.

**근거**

- ieum-011: 재택 중 회사 문서의 출력은 원칙적으로 하지 않는다. 업무상 불가피하게 출력해야 하면 출력 전에 보안·개인정보 담당자의 승인을 받고, 문서를 잠금 보관하며 필요한 사람만 접근하게 한다.
- ieum-011: 보관·파쇄 방법이 승인 기록에 명시되지 않았다면 출력하지 말고 담당자에게 확인한다.
- ieum-011: 사용한 출력물은 첫 사무실 방문 때 보안 파쇄함에 넣거나, 승인된 경우 IT운영팀·총무 담당자에게 안전한 회수·파쇄를 요청한다.
- ieum-011: 가정용 쓰레기나 일반 재활용으로 버리지 않는다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

재택근무 중 회사 문서는 원칙적으로 출력하지 않습니다. 업무상 불가피하다면 출력 전에 보안·개인정보 담당자의 승인을 받고, 문서를 잠금 보관하며 필요한 사람만 접근하게 해야 합니다. 보관·파쇄 방법이 승인 기록에 명시되지 않았다면 출력하지 말고 담당자에게 확인해 주세요. 사용한 출력물은 처음 사무실에 방문할 때 보안 파쇄함에 넣거나, 승인을 받은 경우 IT운영팀·총무 담당자에게 안전한 회수·파쇄를 요청할 수 있습니다. 같은 날 사무실에 반납할 수 없더라도 가정용 쓰레기나 일반 재활용으로 버리면 안 됩니다. (「재택근무 중 정보보호」)

판정: 기본 원칙과 조건부 예외, 서로 대안인 두 폐기 경로가 명료하다.


복구 ID: final-1-A021; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

재택근무 중 회사 문서는 원칙적으로 출력하지 않습니다. 업무상 불가피하면 **출력 전에 보안·개인정보 담당자의 승인을 받고**, 출력물은 잠금 보관해 필요한 사람만 접근하도록 해야 합니다. 승인 기록에 보관·파쇄 방법이 명시되지 않았다면 출력하지 말고 담당자에게 확인하세요. 사용한 출력물은 첫 사무실 방문 때 보안 파쇄함에 넣거나, 승인을 받은 경우 IT운영팀·총무 담당자에게 안전한 회수·파쇄를 요청할 수 있습니다. 같은 날 사무실에 반납할 수 없더라도 가정용 쓰레기나 일반 재활용으로 버리면 안 됩니다.

판정: 예외 조건과 대안 폐기 방법을 연속 절차로 잘못 합치지 않았다.


복구 ID: final-2-A016; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

재택근무 중 회사 문서 출력은 원칙적으로 하지 않습니다. 업무상 불가피하면 출력 전에 보안·개인정보 담당자의 승인을 받아야 합니다. 출력물은 잠금 보관하고 필요한 사람만 접근하게 하세요. 승인 기록에 보관·파쇄 방법이 명시되지 않았다면 출력하지 말고 담당자에게 확인해야 합니다.

사용한 출력물은 첫 사무실 방문 때 보안 파쇄함에 넣거나, 승인을 받은 경우 IT운영팀·총무 담당자에게 안전한 회수·파쇄를 요청할 수 있습니다. 같은 날 사무실에 반납할 수 없다는 이유만으로 가정용 쓰레기나 일반 재활용으로 버리면 안 됩니다.

판정: 기본 원칙, 예외 선행조건과 두 폐기 대안을 잘 구분한다.


복구 ID: final-3-A014; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

재택근무 날짜와 장소가 포털에 승인 기록된 경우에도 회사 자료 출력은 원칙적으로 하지 않습니다. 업무상 불가피하다면 **출력 전에 보안·개인정보 담당자의 승인을 받고**, 출력물을 잠금 보관해 필요한 사람만 접근하도록 해야 합니다. 승인 기록에 보관·파쇄 방법이 명시되지 않았다면 출력하지 말고 담당자에게 확인하세요.

사용한 출력물은 첫 사무실 방문 때 보안 파쇄함에 넣거나, 승인된 경우 IT운영팀·총무 담당자에게 안전한 회수·파쇄를 요청할 수 있습니다. 같은 날 사무실에 반납할 수 없더라도 가정용 쓰레기나 일반 재활용으로 버리면 안 됩니다. (「재택근무 중 정보보호」)

판정: 기본 금지, 사전 승인 예외, 폐기 대안을 각각 구분했고 대안 두 가지를 연속 단계로 만들지 않았다.


복구 ID: final-1-A005; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

재택근무 중 회사 자료 출력은 원칙적으로 하지 않습니다. 업무상 불가피하면 출력 전에 보안·개인정보 담당자의 승인을 받고, 문서를 잠금 보관하며 필요한 사람만 접근할 수 있게 해야 합니다. 승인 기록에 보관·파쇄 방법이 명시되지 않았다면 출력하지 말고 담당자에게 확인하세요. 사용한 출력물은 첫 사무실 방문 때 보안 파쇄함에 넣거나, 승인된 경우 IT운영팀·총무 담당자에게 안전한 회수·파쇄를 요청할 수 있습니다. 같은 날 사무실에 반납할 수 없더라도 가정용 쓰레기나 일반 재활용으로 버리면 안 됩니다.

판정: 기본 금지, 승인 예외와 두 대체 폐기 경로를 구분했다.


복구 ID: final-2-A012; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

재택근무 중 회사 자료는 원칙적으로 출력하지 않습니다. 업무상 불가피하다면 출력 전에 보안·개인정보 담당자의 승인을 받고, 문서를 잠금 보관하며 필요한 사람만 접근하게 해야 합니다. 승인 기록에 보관·파쇄 방법이 명시되지 않았다면 출력하지 말고 담당자에게 확인하세요.

사용한 출력물은 첫 사무실 방문 때 보안 파쇄함에 넣거나, 승인된 경우 IT운영팀·총무 담당자에게 안전한 회수·파쇄를 요청할 수 있습니다. 같은 날 사무실에 반납하지 못하더라도 가정용 쓰레기나 일반 재활용으로 버려서는 안 됩니다.

판정: 조건과 대체 폐기 경로가 정확하며 가정용 폐기를 명확히 금한다.


복구 ID: final-3-A024; 호출별 시간·사용량: 미복구.

### H08 — 거래처가 7만원짜리 식사를 제안했어. 회사 신고 절차와 법적으로 허용되는 금액을 알려줘.

**필수 기준**

1. State that the company sets no blanket permitted amount and even a low-value offer should be reported if it may affect or appear to affect impartial judgment.
2. Before accepting/attending, report through 이음 포털 인사 > 외부 혜택 신고 with provider, purpose/content, date, and related transaction/evaluation; do not accept while review is pending.
3. Explain that the exact applicable legal/national limit is not supplied and requires a separate People-team legal review.
4. Company reporting does not waive legal or contract restrictions.

**근거**

- ieum-045: 업무 판단의 공정성이나 외관에 영향을 줄 수 있으면 금액이 작아 보여도 신고한다. 이음웍스는 일괄 허용 금액을 정하지 않는다.
- ieum-045: 받거나 참석하기 전에 이음 포털의 **인사 > 외부 혜택 신고**에 제공자, 제안 내용·목적, 예정 날짜와 관련 거래·평가 업무를 기록한다.
- ieum-045: 신청 상태가 검토 중이면 수락하지 않는다.
- ieum-045: 회사 신고만으로 적용될 수 있는 법률·계약상 제한이 해제되는 것은 아니다.
- ieum-045: 공직자나 특정 계약에 적용될 수 있는 국가별 제한은 내부 승인이 아니라 People팀의 별도 법률 검토 대상이다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

회사 기준으로는 일괄 허용 금액을 정하지 않아, 7만 원이라는 금액만으로 수락 가능 여부를 판단할 수 없습니다. 식사 참석 전 이음 포털 **인사 > 외부 혜택 신고**에 제공자, 제안 내용·목적, 예정 날짜와 관련 거래·평가 업무를 기록하고, 팀장과 People팀에 검토를 요청하세요. 검토 중에는 수락하거나 참석하지 마세요. 법적으로 허용되는 금액은 현재 사내비에서 확인하기 어렵습니다. 회사 신고만으로 법률·계약상 제한이 해제되는 것은 아니며, People팀의 별도 법률 검토가 필요합니다. 자세한 절차는 「외부 선물과 접대 제안 처리」를 참고하세요.

판정: 절차와 법률상 미확인 사항을 분리했고, 검토 중 수락 금지와 법률·계약 제한을 보존했다.


복구 ID: final-1-A001; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

거래처 식사 제안은 금액이 작아 보여도 업무 판단의 공정성에 영향을 줄 수 있으면 신고 대상입니다. 수락하거나 참석하기 전에 이음 포털의 **인사 > 외부 혜택 신고**에 제공자, 제안 내용·목적, 예정 날짜와 관련 거래·평가 업무를 기록하세요. 업무상 참석이 필요할 수 있다면 참석 전에 팀장과 People팀에 검토를 요청하시고, 검토 중에는 수락하지 마세요. 회사는 일괄 허용 금액을 정하지 않으므로 7만 원이라는 금액만으로 회사 기준상 허용 여부를 판단할 수 없습니다. 법적으로 허용되는 금액도 현재 사내비에서 확인하기 어렵습니다. 적용될 수 있는 법률·계약상 제한은 회사 신고나 내부 검토만으로 해제되지 않으며, People팀의 별도 법률 검토가 필요합니다.

판정: 회사 기준과 알 수 없는 법률 한도를 잘 분리했으나 외관상 공정성 영향 기준이 누락됐다.

- 필수 1: missing — 회사 일괄 허용 금액이 없고 낮은 금액도 공정성에 영향을 줄 수 있으면 신고한다고 했지만, 공정성에 영향을 주는 것처럼 보이는 경우는 빠졌다.

복구 ID: final-2-A009; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

7만 원이라는 금액만으로 허용 여부를 판단할 수는 없습니다. 회사는 선물·접대에 일괄 허용 금액을 두지 않으며, 회사 신고만으로 법률·계약상 제한이 해제되는 것도 아닙니다. 받거나 참석하기 전에 이음 포털 **인사 > 외부 혜택 신고**에 제공자, 제안 내용·목적, 예정 날짜, 관련 거래·평가 업무를 기록하세요. 식사 참석이 필요할 수 있으면 참석 전에 팀장과 People팀에 검토를 요청하고, 검토 중에는 수락하지 마세요. 법적으로 허용되는 금액이나 이 제안에 적용되는 제한은 현재 사내비에서 확인하기 어려우므로 People팀에 별도 법률 검토를 요청하셔야 합니다.

판정: 회사 절차와 법률상 미확인 영역을 나누지만 공정성에 영향을 줄 저액 제안 신고 기준이 빠졌다.

- 필수 1: missing — 일괄 허용 금액이 없다고 하나, 적은 금액이어도 공정성에 영향을 주거나 그렇게 보일 수 있으면 신고한다는 기준은 없다.

복구 ID: final-3-A021; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

7만 원 식사 제안도 금액이 작다고 보고 절차를 생략할 수는 없습니다. 받거나 참석하기 전에 이음 포털 **인사 > 외부 혜택 신고**에 제공자, 제안 내용·목적, 예정 날짜와 관련 거래·평가 업무를 기록해 신고하세요. 업무상 식사 참석이 필요할 수 있다면 참석 전에 팀장과 People팀에 검토를 요청하고, 검토 중에는 수락하지 마세요. 검토가 늦어지면 제안을 보류하거나 정중히 거절하는 것이 안내되어 있습니다.

회사는 일괄 허용 금액을 정하지 않으며, 이 절차만으로 법률·계약상 제한이 해제되는 것도 아닙니다. 현재 사내비에서는 법적으로 허용되는 구체적인 금액을 확인하기 어렵습니다. 공직자나 특정 계약 관련 제한이 적용될 수 있는지는 People팀의 별도 법률 검토가 필요합니다. (「외부 선물과 접대 제안 처리」)

판정: 7만 원에 대한 법률상 허용 여부를 꾸며내지 않고 회사 절차와 법률 검토 경계를 모두 전달했다.


복구 ID: final-1-A016; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

회사에서 정한 일괄 허용 금액은 없으므로 7만 원 식사도 금액만으로 수락 가능하다고 볼 수 없습니다. 참석 전에 이음 포털 **인사 > 외부 혜택 신고**에 제공자, 제안 내용·목적, 예정 날짜와 관련 거래·평가 업무를 기록하고 검토를 요청하세요. 업무상 참석이 필요할 수 있는 식사는 팀장과 People팀의 사전 검토가 필요하며, 검토 중에는 수락하지 마세요. 법률·계약상 허용 금액은 현재 사내비에서 확인하기 어렵습니다. 내부 신고나 승인이 법률·계약상 제한을 해제하지 않으며, People팀의 별도 법률 검토가 필요할 수 있습니다. 자세한 절차는 「외부 선물과 접대 제안 처리」를 참고하세요.

판정: 회사 절차와 법률 불확실성은 나누었으나 공정성 신고 기준과 법률 검토 필요성을 충분히 말하지 않았다.

- 필수 1: missing — 일괄 허용 금액이 없다는 점은 맞지만 낮은 금액도 공정성에 영향을 주거나 그렇게 보일 수 있으면 신고해야 한다는 기준은 빠졌다.
- 필수 3: missing — 법적 금액을 알 수 없다고 했으나 별도 법률 검토는 필요할 수 있다고 약화했다.

복구 ID: final-2-A014; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 partial / 가독성 pass / 구조 pass / 중대한 오류 False

회사 기준에는 일괄 허용 금액이 없어 7만 원이라는 금액만으로 수락 가능 여부를 판단할 수 없습니다. 받거나 참석하기 전에 이음 포털 **인사 > 외부 혜택 신고**에 제공자, 제안 내용·목적, 예정 날짜와 관련 거래·평가 업무를 기록하세요. 업무상 식사 참석이 필요할 수 있으면 참석 전에 팀장과 People팀의 검토도 요청하고, 검토 중에는 수락하지 마세요. 회사 신고로 법률·계약상 제한이 해제되는 것은 아니며, 법적으로 허용되는 금액은 현재 사내비에서 확인하기 어렵습니다. 적용될 수 있는 법률·계약 제한은 People팀에 별도 법률 검토를 요청해 확인하셔야 합니다.

판정: 신고 절차와 법적 한계는 명확하지만 저액이어도 공정성에 영향을 줄 가능성이 있으면 신고한다는 기준이 빠졌다.

- 필수 1: missing — 일괄 허용 금액이 없고 7만원만으로 판단할 수 없다고 하나, 적은 금액이어도 공정성 판단에 영향을 주거나 그렇게 보일 수 있으면 신고한다는 기준은 없다.

복구 ID: final-3-A013; 호출별 시간·사용량: 미복구.

### H09 — 집에서 키우는 강아지를 위한 간식 레시피를 알려줘.

**필수 기준**

1. Briefly state that the assistant is for Ieumworks company work information, rules/procedures, and company-documented work tools.
2. Decline the pet-recipe request without answering it.
3. Keep the response brief and direct; no unsupported company-policy claim.

**근거**

- generation/prompts.py: 사내비는 제공된 문서를 바탕으로 정보를 안내하며, 실제 신청·변경·취소·승인이나 개인별 상태 조회를 수행하지 않습니다.
- generation/profiles.py: 사내비는 이음웍스의 사내 업무 정보·규정·절차와 회사 문서에 설명된 업무 도구·기술의 사용을 안내합니다. 회사 업무와 관계없는 일반 지식 강의·조리법·오락 요청에는 자료가 없다고 설명하지 말고, '이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라 해당 일반 지식 설명은 도와드리기 어렵습니다'처럼 서비스 범위를 짧게 알리고 관련 업무 질문을 유도하세요.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라, 반려견 간식 레시피 같은 일반 조리법은 도와드리기 어렵습니다. 사내 업무나 회사 문서에 관한 질문이 있으시면 말씀해 주세요.

판정: ‘회사 문서’ 안내를 포함한 사내 업무 범위 설명은 업무 도구의 문서 기반 안내까지 포괄한다.


복구 ID: final-1-A011; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라 강아지 간식 레시피는 도와드리기 어렵습니다. 사내 업무나 회사 절차에 관한 질문이 있으시면 말씀해 주세요.

판정: 짧은 상위 범위 표현이 업무 도구 안내를 배제하지 않으므로 의미상 required를 충족한다.


복구 ID: final-2-A005; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

사내비는 이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라 반려견 간식 레시피는 도와드리기 어렵습니다. 관련된 사내 업무 질문이 있으시면 말씀해 주세요.

판정: 사내 업무에 관한 안내 범위가 회사 도구 사용 안내까지 의미상 포함한다.


복구 ID: final-3-A004; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라 강아지 간식 레시피는 안내해 드리기 어렵습니다. 사내 업무 관련 질문이 있으시면 도와드리겠습니다.

판정: 회사 업무 정보·절차라는 상위 범위 표현이 도구 안내까지 의미상 포함하므로 고정 scope 요건을 충족한다.


복구 ID: final-1-A003; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라, 강아지 간식 레시피는 도와드리기 어렵습니다. 사내 업무나 회사 절차에 관한 질문이 있으시면 도와드리겠습니다.

판정: 문자 그대로 ‘도구’라는 낱말은 없어도 회사 업무 정보·절차 범위가 문서 기반 도구 안내를 포함한다.


복구 ID: final-2-A011; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

이음웍스의 사내 업무 정보와 절차를 안내하는 서비스라 강아지 간식 레시피 같은 일반 조리법은 도와드리기 어렵습니다. 사내 업무나 회사 절차에 관한 질문이 있으시면 말씀해 주세요.

판정: 같은 범위 표현을 사용한 반복 응답에 같은 의미 판정을 적용했다.


복구 ID: final-3-A023; 호출별 시간·사용량: 미복구.

### H10 — 승인이 안 되고 있는데 어떻게 해야 해?

**필수 기준**

1. Ask which request/process is awaiting approval and what status or error is shown.
2. Do not assume the request is leave, travel, purchase, access, or deployment.
3. Avoid requiring sensitive personal/customer details; ask only what is needed to identify the process.

**근거**

- ieum-027: 팀장은 업무 필요를 확인한다. 해당 시스템 담당자는 역할 범위와 기술 조건을 검토하고, 고객 운영 환경·기밀 자료·개인정보 접근에는 자료 소유자 및 보안·개인정보 담당자의 확인도 받는다.
- ieum-027: 필수 확인이 끝나면 IT운영팀은 2영업일 안에 계정을 처리하거나 지연 사유를 포털에 남긴다.
- generation/prompts.py: 사내비는 제공된 문서를 바탕으로 정보를 안내하며, 실제 신청·변경·취소·승인이나 개인별 상태 조회를 수행하지 않습니다.

#### examples_answer_scope_v5 · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 신청의 승인이 지연되고 있나요? 연차·경비·접근 권한 등 신청 종류와 포털에 표시된 상태를 알려주시면 해당 절차를 안내해 드리겠습니다.

판정: 간단한 확인 질문으로 흐름을 특정하지 않고 필요한 최소 정보만 요청했다.


복구 ID: final-1-A013; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 신청의 승인이 지연되고 있나요? 휴가·근태, 구매·경비, 시스템 접근 권한 등 신청 종류와 포털에 표시된 상태나 반려 사유를 알려주시면 해당 절차를 안내해 드리겠습니다.

판정: 짧은 확인 질문으로 필요한 범주와 표시 상태를 요청한다.


복구 ID: final-2-A008; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 신청의 승인이 지연되고 있나요? 휴가, 근태, 출장·경비, 계정 권한 등 신청 종류와 포털에 표시된 상태를 알려주시면 해당 절차와 다음 조치를 안내해 드리겠습니다.

판정: 짧은 확인 질문으로 범위를 좁힌다.


복구 ID: final-3-A001; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 신청의 승인이 지연되고 있나요? 연차·병가, 출장·경비, 구매, 권한 요청 등 업무 종류와 현재 포털 상태를 알려주시면 해당 절차에 맞춰 안내해 드리겠습니다.

판정: 짧은 확인 질문으로 절차를 특정하지 않고 개인별 상태를 조회한다고도 주장하지 않았다.


복구 ID: final-1-A023; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 신청의 승인이 지연되고 있는지 알려주시겠어요? 연차·근태, 구매·경비, 권한 신청 등 업무 종류와 포털에 표시된 현재 상태를 알려주시면 해당 절차와 다음 조치를 안내해 드리겠습니다.

판정: 짧은 확인 질문으로 모호성을 좁히며 개인별 상태를 조회한다고 주장하지 않는다.


복구 ID: final-2-A002; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 pass / 가독성 pass / 구조 pass / 중대한 오류 False

어떤 신청의 승인이 지연되고 있나요? 연차·병가, 출장·경비, 업무 구매, 시스템 접근 권한 등 신청 종류와 포털에 표시된 상태를 알려주시면 해당 절차에 맞춰 다음 단계를 안내해 드리겠습니다. 개인별 승인 상태를 직접 조회할 수는 없습니다.

판정: 짧은 확인 질문과 개인별 조회 한계를 함께 제시한다.


복구 ID: final-3-A007; 호출별 시간·사용량: 미복구.

### H11 — 배포 뒤 핵심 기능이 멈추고 데이터가 사라졌을 가능성이 있어. 15분이 지나도 당직자가 인수하지 않았는데 롤백하고 고객에게 공지해도 돼?

**필수 기준**

1. Treat service/core-function interruption or possible data loss as P1 immediately, even if scope is uncertain; alert #service-incident without waiting.
2. Report immediately rather than waiting for acknowledgement. If the on-call person has not accepted within 15 minutes, contact the team-lead fallback; 15 minutes is an acknowledgement target, not a reason to delay initial reporting.
3. Do not perform rollback unless the incident commander approves the emergency change; use an approved automation or runbook as the method. Record the target/affected service and data, rollback condition, and verification before if possible, or promptly after stabilization if urgency prevents it.
4. Customer notice is sent by designated Customer Support through the official channel; state confirmed impact, unknowns, and next update target. For P1, the update goal is every 30 minutes; this is an operational goal, not a contractual SLA.
5. Do not declare resolved until customer impact stops, core flow works, data has no unresolved issue, and recurrence signs are checked.

**근거**

- ieum-069: 서비스 전체 또는 핵심 기능이 중단됐거나, 데이터 손실 가능성이 있다. 영향 범위가 아직 불명확해도 핵심 흐름을 사용할 수 없거나 손실 징후가 보이면 우선 P1로 시작한다.
- ieum-069: 발견자는 시간, 기능, 관찰한 증상, 현재 영향을 기록해 `#service-incident`에 알린다.
- ieum-069: 시간과 관계없이 즉시 서비스 당직에 연락한다.
- ieum-069: 당직자가 수락하지 않으면 기다리기만 하지 말고 팀장 대체 경로로 연락한다.
- ieum-069: 당직자에게 호출을 보낸 뒤 **15분 안에 수락 확인을 받는 것을 인계 목표**로 한다. 이는 응답 SLA 보증이 아니다.
- ieum-069: 고객지원팀은 최초 공지와 이후 상태 공지를 포함해 **30분 간격 갱신 목표**로 안내한다.
- ieum-068: 이 경우 **사고 지휘자**가 긴급 사유와 범위를 확인하고 승인하며, 제품개발팀이 영향을 평가한다.
- ieum-068: 배포는 해당 저장소·서비스가 승인한 자동화나 runbook에 적힌 방법으로만 수행한다.
- ieum-068: 긴급 변경 전에 가능하면 변경 대상, 실행 담당자, 영향을 받는 서비스·데이터, 되돌리기 조건과 검증 방법을 기록한다.
- ieum-068: 급박해서 일부 항목을 미리 적지 못했다면 안정화 후 지체 없이 기록하고 독립 리뷰·검사를 보완한다.
- ieum-069: 외부 공지는 고객지원팀의 지정 담당자가 계약·제품에서 안내한 공식 고객 채널을 통해 전달한다.
- ieum-069: 고객 영향이 멈췄는지, 핵심 흐름이 정상인지, 데이터 상태에 미해결 확인이 없는지, 재발 징후가 없는지를 확인한다.
- ieum-069: 목표 시간은 회사의 운영 목표이지 계약상 SLA 보증이 아니다.

#### examples_answer_scope_v5 · 반복 1

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

핵심 기능 중단과 데이터 손실 가능성이 있으면 원인 분석을 기다리지 말고 P1로 대응하세요. 15분은 당직 인수 목표이므로 그 시간을 넘겼다고 기다리지 말고 팀장에게 대체 인계를 요청하세요. 즉시 #service-incident에 알리고 이음 포털의 고객지원 > 장애 기록에도 남기세요. 보안·개인정보 노출 가능성도 있으면 해당 사고 경로로 별도 신고해야 합니다.

롤백은 바로 단독 실행하기보다 사고 지휘자가 긴급 변경의 사유와 범위를 승인하고 제품개발팀이 영향을 평가해야 합니다. 승인된 복구 경로와 데이터 상태를 확인하세요. 코드 롤백만으로 데이터가 복구되지 않을 수 있으며, 안전한 복구 방법이 확인되지 않았다면 서비스 책임자와 순서를 정하기 전에는 시작하지 않습니다.

고객 공지는 고객지원팀의 지정 담당자가 공식 고객 채널로 전달합니다. 확인된 영향과 증상, 안전한 우회 방법, 조사 중인 점과 다음 안내 목표 시점을 알리되, 데이터 손실이나 복구 완료를 확인 전에 단정하지 마세요. P1 고객 안내는 30분 간격 갱신을 목표로 합니다. (「서비스 장애와 고객 공지」, 「배포·실패·롤백 안내」)

판정: 초동 대응과 권한 경계는 분명하다. 다만 필수 복구 기록·검증 및 종료 조건을 빠뜨려 복합 필수사항이 충족되지 않았다. 무단 롤백이나 복구 완료를 주장하지는 않았다.

- 필수 3: missing — 사고 지휘자 승인과 승인된 복구 경로는 언급했지만, 자동화/runbook 사용 및 영향 서비스·데이터, 되돌리기 조건, 검증 기록 기준은 빠졌다.
- 필수 5: missing — 고객 영향, 핵심 흐름, 데이터 미해결 여부, 재발 징후라는 종료 확인 조건을 제시하지 않았다.

복구 ID: final-1-A002; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

핵심 기능 중단과 데이터 손실 가능성이 있으면 P1로 대응해야 합니다. 15분은 당직 인수 목표이지 기다려야 하는 시간이 아니므로, 지금 #service-incident와 이음 포털의 고객지원 > 장애 기록에 알리고 팀장에게 대체 인계를 요청하세요.

롤백은 임의로 실행하지 마세요. 사고 지휘자가 긴급 변경의 사유와 범위를 승인하고 제품개발팀이 영향을 평가해야 합니다. 데이터 변경이 포함됐다면 코드 롤백만으로 데이터가 복구된다고 볼 수 없으므로, 승인된 복구 경로와 데이터 영향을 확인한 뒤 진행해야 합니다.

고객 공지는 지정된 고객소통 담당자가 고객지원팀의 공식 고객 채널로 전달해야 합니다. 확인된 영향과 현재 상태, 미확인 사항, 다음 안내 목표를 알리고, 원인이나 데이터 복구를 확인하기 전에는 단정하지 마세요. P1은 최초 공지와 이후 상태 공지를 30분 간격으로 갱신하는 것이 목표입니다.

판정: 즉시 신고·대체 인계와 롤백 승인 경계는 맞다. 다만 롤백 기록과 종결 확인의 하위 조건이 빠졌고, 30분 갱신을 목표라고만 해 비 SLA 구분도 누락했다.

- 필수 3: missing — 사고 지휘자 승인과 승인 복구 경로는 있지만 영향 대상·데이터, 되돌리기 조건·검증 기록의 하위 항목이 없다.
- 필수 4: missing — 지정 역할·공식 채널·확인 사실·미확인 사항·다음 안내 목표와 30분 목표는 있으나, 그 목표가 계약상 SLA가 아니라는 구분은 답변에 없다.
- 필수 5: missing — 영향 종료·핵심 흐름·데이터·재발 징후를 확인하기 전 해결 선언 금지 기준이 빠졌다.

복구 ID: final-2-A018; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

이 상황은 핵심 기능 중단 또는 데이터 손실 가능성이 있어 P1로 대응해야 합니다. 15분 내 당직자 인수가 없으면 기다리지 말고 팀장에게 대체 인계를 요청하고, 인수될 때까지 연락 시도와 상황을 기록하세요. 장애는 #service-incident와 이음 포털의 고객지원 > 장애 기록에 남기고, 보안·개인정보 노출도 의심되면 보안 사고 경로에도 별도로 신고하세요.

롤백은 임의로 진행하지 마세요. 사고 지휘자의 긴급 변경 승인과 제품개발팀의 영향 검토가 필요하며, 승인된 복구 경로와 데이터 변경이 롤백으로 복구되는지를 확인해야 합니다. 데이터 상태나 복구 가능성이 불분명하면 기술 책임자와 사고 지휘자에게 안전한 조치를 확인하세요.

고객 공지는 지정된 고객소통 담당자가 공식 고객 채널로 안내합니다. P1 공지는 최초 안내와 이후 30분 간격 갱신이 목표이며, 확인된 영향과 다음 안내 시점을 알리되 원인·복구 시각·데이터 상태는 확인 전 단정하지 않습니다. 관련 절차는 「서비스 장애와 고객 공지」 및 「배포·실패·롤백 안내」를 참고하세요.

판정: 15분을 초기 신고 대기 의무로 바꾸지는 않지만 신고 시점은 모호하다. 롤백 기록과 종료 확인 조건이 빠졌다.

- 필수 1: uncertain — P1 분류와 #service-incident 경로는 나오지만, 15분 수락 대기와 무관하게 즉시 채널에 알리라는 순서가 명시되지 않는다.
- 필수 2: uncertain — 미수락 시 팀장 대체 경로를 안내하고 기다리지 말라고 하지만, 초기 신고가 수락 확인을 기다리지 않는다는 점은 문장 순서상 불명확하다.
- 필수 3: missing — 사고 지휘자 승인과 영향 검토, 승인된 복구 경로 및 데이터 확인은 있으나 자동화/runbook 사용 방법이 명시되지 않고, 영향 서비스·데이터, 되돌리기 조건과 검증을 언제 기록할지 빠졌다.
- 필수 4: uncertain — 공식 채널·확인/미확인 사실·다음 안내 시점·30분 목표는 맞지만, 고객지원팀 지정 담당자와 답변의 고객소통 담당자 역할이 같은지 자료만으로 확정하기 어렵다.
- 필수 5: missing — 영향 중단, 핵심 흐름, 데이터 미해결 사항, 재발 징후를 확인하기 전 해결 선언을 하지 말라는 조건이 없다.

복구 ID: final-3-A003; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

핵심 기능 중단 또는 데이터 손실 가능성이 있으면 **P1 장애로 우선 대응**하고, `#service-incident`에 알린 뒤 이음 포털의 **고객지원 > 장애 기록**을 여세요. 당직자가 15분 안에 인수하지 않았다면 더 기다리지 말고 팀장에게 대체 인계를 요청하세요.

다만 그 사실만으로 직접 롤백을 시작해도 된다고 판단할 수는 없습니다. 긴급 변경은 사고 지휘자의 승인과 제품개발팀의 영향 평가가 필요합니다. 데이터 변경이 있었다면 코드 롤백으로 데이터까지 복구되는지 별도로 확인하고, 안전한 복구 경로가 확인되지 않으면 실행을 시작하지 말고 서비스 책임자와 순서를 정하세요.

고객 공지는 고객지원팀의 지정 담당자가 공식 고객 채널로 안내합니다. 확인된 영향과 사실, 안전하게 확인된 우회 방법, 다음 안내 목표 시점을 알리며, P1은 최초 공지와 이후 상태를 **30분 간격 갱신 목표**로 안내합니다. 본인의 담당 역할이 확인되지 않았다면 팀장에게 공지 담당자를 지정해 달라고 요청하세요.

판정: 즉시 신고, 팀장 대체 경로, 롤백 승인 경계는 지켰다. 그러나 필수 복구 절차·기록과 고객 공지·종료 확인 조건이 누락되어 복합 필수사항을 충족하지 못했다.

- 필수 3: missing — 사고 지휘자 승인과 안전 경로는 언급했지만 승인된 자동화/runbook 및 영향·되돌리기·검증 기록 조건은 빠졌다.
- 필수 4: missing — 확인 사실과 다음 갱신 목표는 제시했지만 미확인 사항을 함께 알리라는 조건과 운영 목표가 SLA가 아님을 분명히 하지 않았다.
- 필수 5: missing — 고객 영향·핵심 흐름·데이터 미해결 여부·재발 징후의 종료 확인 조건이 빠졌다.

복구 ID: final-1-A024; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

현재 상황은 핵심 기능 중단과 데이터 손실 가능성이 있으므로 P1로 우선 대응해야 합니다. 당직자가 15분 안에 인수하지 않았다면 기다리지 말고 팀장에게 대체 인계를 요청하세요. 15분은 인계 목표이지, 직접 조치해도 된다는 승인 기준은 아닙니다. 장애는 #service-incident와 이음 포털의 고객지원 > 장애 기록에 남기세요. 보안·개인정보 노출 우려도 있으면 보안 사고 경로에 별도로 신고해야 합니다.

롤백은 임의로 실행하지 마세요. 사고 지휘자의 긴급 변경 승인과 제품개발팀의 영향 평가를 거치고, 배포 기록이나 승인된 runbook에 정해진 복구 경로를 따라야 합니다. 데이터 변경이 있었다면 코드 롤백만으로 데이터가 복구된다고 볼 수 없습니다. 데이터 상태와 안전한 복구 방법이 확인되지 않았다면 롤백을 시작하지 말고 담당자와 확인하세요.

고객 공지는 지정된 고객소통 담당자가 공식 고객 채널로 안내합니다. 본인이 그 역할을 맡은 경우에도 확인된 영향·증상, 안전한 우회 방법, 조사 중인 점과 다음 안내 목표 시점을 전달하고, 원인·복구 시각·데이터 상태는 확인 전 단정하지 마세요. P1은 30분 간격 갱신이 운영 목표이며 계약상 SLA 보증은 아닙니다.

판정: 초동 보고·대체 인계·롤백 승인·고객 공지는 대체로 정확하지만 롤백 기록과 종료 확인의 필수 세부가 빠졌다.

- 필수 3: missing — 사고 지휘자 승인과 승인된 runbook은 언급했지만 영향 서비스·데이터, 되돌리기 조건, 검증 방법을 기록하라는 하위 조건이 빠졌다.
- 필수 5: missing — 서비스 영향 중단·핵심 흐름 정상·데이터 미해결 없음·재발 징후 확인 전 해결 선언 금지 기준을 제시하지 않았다.

복구 ID: final-2-A010; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 partial / 가독성 pass / 구조 partial / 중대한 오류 False

핵심 기능 중단 또는 데이터 손실 가능성은 P1로 즉시 대응해야 합니다. 당직자가 15분 안에 인수하지 않았다면 기다리지 말고 지금 팀장에게 대체 인계를 요청하고, 연락 시도와 인수 여부를 장애 기록에 남기세요.

문서상 임의로 바로 롤백해도 된다고 정해져 있지는 않습니다. 사고 지휘자가 긴급 사유와 범위를 승인하고 제품개발팀이 영향을 평가한 뒤, 해당 서비스의 승인된 배포 방법이나 runbook에 따라야 합니다. 데이터 변경이 있었다면 코드 롤백으로 데이터 상태도 복구되는지 확인해야 하며, 복구 경로가 불명확하면 안전한 순서를 정하기 전에는 진행하지 마세요.

고객 공지는 고객지원팀의 지정 담당자가 공식 고객 채널로 전달합니다. 확인된 영향과 증상, 확인되지 않은 사항, 안전한 우회 방법이 있다면 그 방법과 다음 안내 시점을 알리고, 데이터 손실이나 원인·복구 시각은 확인 없이 단정하지 마세요. P1 상태 공지는 30분 간격 갱신을 목표로 합니다. 장애 기록은 이음 포털의 고객지원 > 장애 기록과 #service-incident에 남기세요.

판정: 승인 전 롤백은 금하고 15분 뒤 팀장 연락은 즉시 안내한다. 초기 신고 시점의 문장상 모호함과 기록/종료 체크가 남는다.

- 필수 1: uncertain — P1 즉시 대응과 #service-incident 경로가 모두 나오지만, 최초 신고를 수락 확인과 무관하게 지금 하라는 시점이 명확하지 않다.
- 필수 2: uncertain — 15분 미수락이면 지금 팀장 대체 경로로 가라고 하므로 목표를 대기 의무로 만들지는 않는다. 다만 최초 신고가 수락 확인 전임을 명시하지 않는다.
- 필수 3: missing — 승인된 변경 경로와 runbook, 데이터 복구 확인은 있으나 영향을 받는 서비스/데이터, 되돌리기 조건과 검증을 언제 기록할지 없다.
- 필수 5: missing — 영향 중단, 핵심 흐름 정상, 데이터 확인, 재발 징후 확인 전 해결 선언을 금하는 조건은 없다.

복구 ID: final-3-A022; 호출별 시간·사용량: 미복구.

### H12 — 사무실 화재 경보가 울렸고 한 명이 다쳤으며 동료 한 명이 보이지 않아. 무엇을 먼저 해야 해?

**필수 기준**

1. Prioritize evacuation and on-scene instructions; do not delay evacuation for internal reporting or belongings.
2. Call 119 for fire/rescue needs within the bounds of not delaying evacuation.
3. At a safe location, account for people and tell rescuers the missing person’s last known location.
4. Do not re-enter until firefighters or actual building management explicitly confirm safety and direct re-entry.
5. Do not send someone back into the building to search.

**근거**

- ieum-048: 대피를 늦추지 않는 범위에서 119에 화재나 구조 필요를 알린다.
- ieum-048: 안전한 장소에 도착한 뒤 팀장은 가능한 출석·방문 기록으로 동행자의 안전을 확인하고, 확인되지 않은 사람이 있으면 마지막으로 알려진 위치를 구조자에게 알린다.
- ieum-048: 사람을 찾으러 건물 안으로 되돌아가지 않는다.
- ieum-048: 소방관 또는 실제 건물 관리자가 안전을 확인하고 재입장을 명시적으로 안내하기 전에는 건물로 돌아가지 않는다.
- ieum-048: 위급 시 회사 내부 보고보다 119 등 지역 긴급 지원이 우선한다.

#### examples_answer_scope_v5 · 반복 1

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

먼저 경보가 오작동처럼 느껴져도 현장 대피 안내에 따라 대피하세요. 화재 상황에서는 엘리베이터를 이용하지 말고, 대피를 늦추지 않는 범위에서 119에 부상자와 구조가 필요한 동료가 있다고 알리세요. 안전한 장소에 도착하면 팀장이 인원 확인을 돕고, 보이지 않는 동료의 마지막으로 알려진 위치를 구조대에 전달하도록 하세요. 직접 찾으러 건물 안으로 돌아가지 말고, 소방관이나 건물 관리자가 재입장을 명시적으로 안내할 때까지 들어가지 마세요.

판정: 대피·신고·안전 지점 인원 확인 순서는 명료하다. 안전 확인 조건과 타인을 보내지 말라는 중대한 안전 항목은 빠졌다.

- 필수 4: missing — 소방관·건물 관리자의 명시적 재입장 안내는 요구했지만, 그 전에 안전을 확인해야 한다는 조건은 말하지 않았다.
- 필수 5: missing — 응답자 본인이 찾으러 돌아가지 말라고 했을 뿐, 다른 사람을 보내 수색하지 말라는 지시는 없다.

복구 ID: final-1-A009; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 2

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

먼저 주변에 알리고 실제 건물의 대피도·방송·관리자 지시에 따라 안전한 곳으로 대피하세요. 화재가 의심되면 엘리베이터를 사용하지 말고, 동료를 찾으러 건물 안으로 되돌아가지 마세요. 대피를 늦추지 않는 범위에서 119에 부상자와 실종된 동료가 있음을 알리고, 동료의 마지막으로 알려진 위치를 전달하세요. 안전한 곳에 도착한 뒤 팀장이 인원을 확인하도록 하고, 소방관이나 건물 관리자가 안전을 확인해 재입장을 안내하기 전에는 돌아가지 마세요.

판정: 긴급 신고와 재입장 경계는 정확하지만, 안전 장소에서 위치를 구조자에게 전달하는 단계와 타인 수색 금지가 빠졌다.

- 필수 3: missing — 실종자의 위치는 앞선 119 연락에서 전달하고, 안전 장소에서는 인원 확인만 말해 위치 전달을 안전 장소 단계에 두지 않았다.
- 필수 5: missing — 응답자가 직접 되돌아가지 말라는 내용만 있고 다른 사람을 보내 수색하지 말라는 내용은 없다.

복구 ID: final-2-A015; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v5 · 반복 3

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

먼저 개인 물품을 챙기거나 동료를 찾으러 되돌아가지 말고, 주변에 알린 뒤 사무실에 게시된 대피도와 방송·건물 관리자 안내에 따라 대피하세요. 화재 의심 시 엘리베이터는 이용하지 마세요. 대피를 늦추지 않는 범위에서 119에 연락해 화재와 부상자, 보이지 않는 동료의 마지막으로 알려진 위치를 알리세요. 출구가 연기나 열기로 위험하면 무리하게 통과하지 말고 문을 닫을 수 있는 안전한 장소에서 구조를 요청하세요. 안전한 곳에 도착한 뒤 팀장이 인원 확인을 돕고, 미확인된 동료의 마지막 위치를 구조대에 전달하도록 하세요. 소방관이나 건물 관리자가 안전과 재진입을 명시적으로 확인하기 전에는 건물로 돌아가지 마세요.

판정: 신고·안전 지점 확인·재입장 조건은 충족하지만 다른 사람을 보내지 말라는 critical safety item을 누락했다.

- 필수 5: missing — 개인적으로 돌아가지 말라는 표현이며 다른 사람을 보내 수색하지 말라는 지시는 아니다.

복구 ID: final-3-A010; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 1

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

먼저 주변에 알리고, 개인 물품을 챙기느라 지체하지 말고 실제 건물 대피 안내에 따라 안전한 장소로 이동하세요. 화재가 의심되면 엘리베이터를 사용하지 말고, 다친 사람이 있거나 구조가 필요하면 대피를 늦추지 않는 범위에서 119에 알리세요. 동료를 찾으러 건물 안으로 돌아가지는 마세요. 안전한 장소에 도착한 뒤 팀장에게 동료가 보이지 않는다는 사실과 마지막으로 알려진 위치를 알려 구조자에게 전달하도록 하세요. 소방관이나 실제 건물 관리자가 안전을 확인하고 재입장을 명시적으로 안내하기 전에는 건물에 돌아가지 마세요.

판정: 필수 대피 흐름과 재입장 조건은 충족한다. 타인을 보내 수색하지 말라는 별도 안전 경계가 빠져 critical omission으로 판정했다.

- 필수 5: missing — 본인이 돌아가지 말라는 지시는 있으나 다른 사람에게 수색을 맡기지 말라는 지시는 없다.

복구 ID: final-1-A019; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 2

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

먼저 주변에 알리고 현장 대피도·방송·건물 관리자의 안내에 따라 즉시 안전한 곳으로 대피하세요. 물건을 챙기느라 지체하거나 엘리베이터를 이용하지 마세요. 다친 사람이 즉각적인 도움이 필요하면 대피를 늦추지 않는 범위에서 119에 신고하세요. 안전한 장소에 도착한 뒤 팀장에게 알리면 인원을 확인하고, 보이지 않는 동료의 마지막으로 알려진 위치를 구조대에 전달하도록 하세요. 동료를 찾으러 건물 안으로 다시 들어가지는 마세요.

판정: 안전 지점의 인원 확인은 맞지만 119 신고 범위와 재입장 조건이 불완전하고 타인 수색 금지도 빠졌다.

- 필수 2: missing — 119 신고를 부상자가 즉시 도움을 필요로 하는 경우로만 한정해, 실종자 구조를 위한 신고 범위를 다루지 않았다.
- 필수 4: missing — 소방관·실제 건물 관리자의 안전 확인과 재입장 안내를 대기 조건으로 제시하지 않았다.
- 필수 5: missing — 응답자가 찾으러 돌아가지 말라는 지시만 있으며 다른 사람을 보내 수색하지 말라는 내용은 없다.

복구 ID: final-2-A019; 호출별 시간·사용량: 미복구.

#### examples_answer_scope_v7_completeness · 반복 3

내용 fail / 가독성 pass / 구조 partial / 중대한 오류 False

먼저 대피를 늦추지 말고 주변에 알린 뒤, 현장 대피도와 건물 안내에 따라 안전한 곳으로 이동하세요. 화재가 의심되면 엘리베이터를 이용하지 말고, 출구가 연기나 열기로 위험하면 무리하게 통과하지 마세요. 대피를 지체하지 않는 범위에서 119에 부상자와 실종된 동료의 구조가 필요하다고 알리세요. 안전한 장소에 도착한 뒤 팀장이 인원을 확인하도록 하고, 동료가 확인되지 않으면 마지막으로 알려진 위치를 구조대에 전달하세요. 동료를 찾으러 건물 안으로 다시 들어가지는 마세요.

판정: 대피와 신고 순서는 명료하지만 재입장 허가 조건과 타인 수색 금지가 빠져 있다.

- 필수 4: missing — 소방관·실제 건물 관리자의 안전 확인과 재입장 지시라는 조건을 말하지 않았다.
- 필수 5: missing — 응답자가 직접 찾으러 들어가지 말라고 했을 뿐 다른 사람을 보내 수색하지 말라는 내용은 없다.

복구 ID: final-3-A020; 호출별 시간·사용량: 미복구.

