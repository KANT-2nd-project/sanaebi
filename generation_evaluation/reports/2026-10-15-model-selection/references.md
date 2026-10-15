# 공식 참조 확인 — 2026-10-15

https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/pricing
https://developers.openai.com/api/docs/guides/latest-model

모델 페이지에서 none/low 추론 설정 지원, 문맥 1,050,000, 출력128,000 상한을 확인했다. 함수 호출 없는 텍스트 Chat Completions 비교이며 low에는 temperature를 전달하지 않는다.

표준 1M토큰 단가: 입력 $0.10, 캐시읽기 $0.01, 캐시쓰기 $0.125, 출력 $0.50. 모델 페이지의 272K 초과 입력 요청은 입력/캐시2배·출력1.5배임을 실험 진행 중 재확인했다. 실험 시작 전 고정한 ledger는 긴 문맥 단가를 모든 호출에 보수적으로 적용한다. 이미 실행한 코드·정산 방식을 중간에 바꾸지 않고 최종 보고서는 이 상한 추정과 표준 단가 적용 추정을 구분한다. 둘 다 청구서 확정 금액은 아니다.

## 최종 평가에서 발견한 형식 실패의 후속 검토

[Structured Outputs 공식 안내](https://developers.openai.com/api/docs/guides/structured-outputs)를 2026-10-15에 확인했다. 스키마 제약과 프롬프트의 JSON 지시는 별개이며, 구조화 출력에서도 거절과 출력 한도에 따른 미완성 처리는 필요하다. 현재 비교는 프롬프트 지시만 사용했으므로 이 기능의 효과를 실측한 것은 아니다. 최종 결과를 본 뒤 후보를 바꾸지 않는 규칙에 따라 이번 비교에는 추가하지 않았다. 차기 개발 실험에서 스키마 강제를 한 요소로 비교하고 의미 정확성은 별도로 평가해야 한다.
