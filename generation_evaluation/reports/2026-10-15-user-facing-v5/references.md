# 사용자용 말투와 서비스 범위 안내의 공식 참고 자료

확인일: 2026-10-15. 별도 읽기 전용 연구자가 공식 자료를 조사했고 구현 담당 AI가 적용 범위를 정리했다. 아래는 제품별 공개 기능·지침이며 각 회사의 비공개 운영 구조를 재현했다는 뜻이 아니다.

| 공식 자료 | 확인한 원칙 | 사내비 적용 |
|---|---|---|
| [Intercom Fin Guidance best practices](https://www.intercom.com/help/en/articles/10560969-fin-guidance-best-practices) | 제품과 직접 관련된 요청만 돕고, 무관한 요청에는 지원 범위를 정중히 알리는 예시. Guidance가 검색 전에 적용된다는 제품 특성도 설명한다. | 일반 알고리즘 강의·조리법에는 회사 업무 안내 서비스임을 짧게 알린다. 범위 밖과 범위 안의 자료 부족을 별도로 판단한다. |
| [Google Dialogflow CX Intents](https://docs.cloud.google.com/dialogflow/cx/docs/concept/intent) | 표현이 비슷한 요청도 의도로 구분하고, 범위 밖 부정 예시가 범위 안 매칭까지 방해할 수 있음을 경고한다. | 기술 용어 키워드만으로 차단하지 않는다. 업무 맥락이 모호하면 묻고 회사 문서에 해당 사용법이 있으면 답한다. |
| [Google Data store settings](https://docs.cloud.google.com/dialogflow/cx/docs/concept/data-store/settings) | 연결 자료의 근거 수준과 정보 부족 처리 경로를 설명한다. | 사내 연봉 기준을 확인하지 못한 경우는 자료 부족이다. 회사 제도가 없다고 단정하지 않는다. |
| [AWS Bedrock denied topics](https://docs.aws.amazon.com/us_en/bedrock/latest/userguide/guardrails-denied-topics.html) | 주제를 문맥적으로 평가하며 단어·개체 자체의 탐지에 쓰지 말라고 안내한다. | 기술 용어의 일괄 차단을 피한다. AWS의 안전 주제 차단을 사내비 업무 범위와 동일 기능이라고 주장하지 않는다. |
| [Microsoft Copilot Studio generative answers FAQ](https://learn.microsoft.com/en-us/microsoft-copilot-studio/faqs-generative-answers) | 연결 출처 밖 일반 지식 응답 허용 여부를 별도로 설정한다. | 회사 문서에 근거한 답변이라는 경계는 유지한다. 자연스러운 말투는 일반 지식 허용을 의미하지 않는다. |

## 적용한 판단

범위·업무 맥락 확인 → 해당 범위의 근거 확인 → 사용자에게 직접 안내한다. 범위 안의 자료 부족은 확인되지 않는 항목을 구체적으로 밝히고, 범위 밖은 서비스가 돕는 범위를 설명한다. 혼합 질문에는 가능한 부분을 답한다. 기술 문서가 추가되면 같은 기술어 질문에도 업무 범위 내 답변이 가능해야 한다.

“확인되지 않는 내용은 확인할 수 없다고 안내하겠습니다” 같은 작성 규칙 선언을 제외하는 것은 사용자의 UX 요구를 반영한 프로젝트 결정이다. 모든 상용 챗봇의 표준 문구라고 표현하지 않는다. 필요한 출처·조건·충돌 설명은 허용하며 내부 문서 ID 대신 실제 제목·항목명을 사용한다.

## 가격 기록

[OpenAI 공식 가격](https://developers.openai.com/api/docs/pricing)을 확인했다. 비용은 Standard long-context의 cache-write 입력 상한 $0.25/백만 토큰과 출력 $0.75/백만 토큰으로 보수적으로 추정하며 캐시 할인을 적용하지 않는다. 청구서와 동일한 실청구액으로 주장하지 않는다. 사용량을 못 받으면 사전 예약 추정치를 유지한다.
