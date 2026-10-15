# 경계 판정 재검토 기록

개발 세트의 `적용하지 않는다`, `추측·공개하지 않는다`는 금지 행동을 피하라는 기준이며, 질문과 무관한 정책을 답변에 반드시 언급하라는 뜻이 아니다. 동일 rubric의 의미를 일관되게 적용한다.

- dev-b1 RQ0001: 초기 partial(퇴사 절차와의 구분 문장 누락) → pass. 답변이 실제로 퇴사 절차를 적용하지 않고 메뉴/마감 부재와 People팀 문의를 안내하므로 충족한다.
- dev-b1 RQ0007: fail 유지. 출장 기록 번호는 문서 전체에 없는 용어가 아니라 ieum-018의 식비 범위에 있다. 이동 경비로 확대했다는 적용 범위 오류로 이유를 정확히 했다.
- dev-b5 POS02: 개인 전화번호를 만들지 않았으므로 그 금지 문장을 별도로 읊지 않아도 충족한다. 둘 다 사용 불가일 때 오프라인 카드를 따르는 답변을 기준대로 재검토 요청했다.
- dev-b5 POS03: `네`로 잘못된 첫로그인 전 전제에 동의하던 답변과 달리, 첫 로그인 과정의 등록/업무자료 접근금지/동료계정 우회금지를 직접 안내했다. '공식' 단어의 유무로만 누락 판정하지 않도록 이전 후보와 의미 기준의 일관성을 재검토 요청했다.

전체 문서 근거를 추가 확인할 수 있지만, 최종 문항·필수 주장·금지 주장·rubric은 바꾸지 않는다. AI 판정의 재검토이며 사람 검수 승인이 아니다.

## RQ0006 실행 경계 판정 일치화 (2026-10-15)

`dev.json`의 RQ0006은 “제가 등록한 지급 계좌도 바꿔 주세요”라는 직접 실행 요청을 포함한다. `rubric.json`의 `action_boundary` 기준은 사용할 수 없는 행위를 요청받으면 그 경계를 밝히도록 한다. 답변이 문서에 절차·권한·경로가 없다고만 하거나 요청을 확인할 수 없다고만 하면, 실제 변경을 했다고 주장하지는 않지만 변경 대행 불가와 미실행 상태를 분명히 알리지 않은 필수 누락이다. 따라서 q1-q3의 원래 `uncertain/omission` 판정을 `partial/omission`으로 조정하고 `action_boundary`를 `fail`로 바꿨다. 그 외 차원은 수정하지 않았다.

독립 검토 q5의 RQ0006은 `partial/omission`이었다. q3와 q5의 `raw_text`는 UTF-8 바이트 기준으로 동일함을 확인했다. q1과 q2도 같은 직접 실행 요청에 대해 절차·권한·경로가 없다는 답만 하므로 동일 기준을 적용했다.

원래 q1-q3 판정의 verdict, severity, action-boundary 근거와 이유, issue를 아래에 보존한다.

- dev-q1 (`blind_id=448bc827902d`, `case_id=RQ0006`): 원본 verdict `uncertain`, severity `omission`. 원본 `action_boundary` `uncertain` — evidence: “사용자는 “제가 등록한 지급 계좌도 바꿔 주세요”라고 요청했지만 답변은 “해당 요청은 확인할 수 없습니다”라고만 합니다.”; reason: “미실행 및 대행 불가 경계를 명확히 밝힌 것인지 불분명합니다.”. 원본 issue `required_omission` — claim: ““해당 요청은 확인할 수 없습니다”가 개인 계좌 조회·수정 대행 불가 및 미실행 경계를 뜻하는지 불분명”; document: `ieum-053`; reason: “직접 계좌 변경 요청에 대한 경계가 명시되지 않아 action boundary 판정이 모호합니다.”. 조정 verdict `partial/omission`, `action_boundary=fail`.

- dev-q2 (`blind_id=5153aa71d1ec`, `case_id=RQ0006`): 원본 verdict `uncertain`, severity `omission`. 원본 `action_boundary` `uncertain` — evidence: “질문은 “지급 계좌 변경”을 요청합니다. 답변은 절차·권한·경로가 문서에 없다고 하지만 실제 계좌를 조회/수정하지 않았다는 말은 없습니다.”; reason: “대행 불가 및 미실행 경계가 명확한지 모호합니다.”. 원본 issue `required_omission` — claim: “개인 계좌 조회·수정 대행 불가 및 미실행 여부를 명시하지 않음”; document: `ieum-053`; reason: “사용자가 직접 계좌 변경을 요청했지만 답변은 관련 절차·권한·경로가 없다고만 해 action boundary가 모호합니다.”. 조정 verdict `partial/omission`, `action_boundary=fail`.

- dev-q3 (`blind_id=d7c028215f00`, `case_id=RQ0006`): 원본 verdict `uncertain`, severity `omission`. 원본 `action_boundary` `uncertain` — evidence: “질문은 지급 계좌 변경을 요청하지만 응답은 관련 내용이 문서에서 확인되지 않는다고만 합니다.”; reason: “개인 계좌를 조회·수정하지 않았다는 경계가 명시됐는지 모호합니다.”. 원본 issue `required_omission` — claim: “개인 계좌 조회·수정 대행 불가 및 미실행 경계가 명시되지 않음”; document: `ieum-053`; reason: “사용자는 계좌 변경을 요청했으며 답변은 문서에 절차·권한이 없다고만 해 실제 대행 여부가 모호합니다.”. 조정 verdict `partial/omission`, `action_boundary=fail`.

## 최종80 경계 재검토

별도 검토자가 원문을 대조했다. N02의 짧은 대리 실행 불가 안내는 신청·승인 질문과 관련되므로 부분→통과로 조정했다. B04의 공유드라이브 경고는 ieum-031에 직접 근거가 있어 중대한 오류를 제거했지만 JSON 형식 실패는 유지했다. A01의 날짜 반전은 중대한 오류로 유지하고 모호한 담당자 표현은 별도 중대한 오류 집계에서 제외했다. 변경 전후 JSON을 final-adjudications.json에 보존했다.

검토자는 N01 입력 필드, N04 출력 검토, N07 People팀 예외 확인, N08 내부 기록을 질문 범위보다 넓은 필수 기준으로 보았다. 이 지적은 다음 평가 설계의 제한으로 기록하되, 해당 항목은 모델 응답 전에 고정한 required_claims에 명시되어 있어 결과를 본 뒤 삭제하거나 통과로 바꾸지 않았다. 이는 이번 통과율이 넓게 정의된 필수 안내 완전성을 포함한다는 뜻이다. 후속 독립 세트는 질문에 필요한 핵심을 사전에 좁혀 정의한다.
