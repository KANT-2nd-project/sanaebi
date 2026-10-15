# 분류 참고 정보 비교 — 고정 프로토콜

v5 기준의 문서 기반 생성에 오류 가능한 라벨을 전달하는 후보를 비교한다. 모든 라벨의 system 지침은 같고 user 데이터의 enum만 다르다. 모델·문서·추론 설정은 라벨별로 바꾸지 않는다. 현재 HTTP에는 연결하지 않으며 실험 통과 시에만 통합한다.

## 입력과 비교군

[고정 문항·판정 기준](cases.json)은 공개 합성 회사 문서와 합성 overlay를 사용한다. 운영 DB·실제 직원 질문 원문을 읽지 않는다. F09는 원래 배포 실패 사례의 합성 재현이며 정확한 원요청 재현이 아니다. 라벨 기준은 [요청 처리 기준](../../../docs/label-taxonomy.md)을 유지한다.

- A: 현재 프로필 원문.
- B: 공통 보조 지침과 null 라벨. 지침 추가 효과를 분리하는 평가용 대조군.
- C: 같은 보조 지침과 실제 분류기 예측. 정답 라벨로 교정하지 않는다.
- W: C의 라벨만 실제 예측과 다른 두 enum으로 바꾼 진단 시험. 모든 대체 라벨이 의미상 오답이라는 뜻은 아니다.

P01·P04·P05·P06에 W를 적용한다. 질문별 A/B/C 순서를 순환하고 두 번째 반복은 역순이다. 같은 모델의 반복을 서로 다른 질문으로 세지 않는다. 확인20문항은 후보 튜닝에 사용하지 않고 실행 전 동결한다. 과거 문제의 변형을 모두 새로운 일반화 질문이라고 주장하지 않는다.

## 실행

소스 checkout과 기존 Ollama 불필요 기본 환경에서 실행한다. OPENAI_API_KEY는 실행 환경에 주입하고 파일·명령 예시에 실제 값을 넣지 않는다.

```bash
python -m generation_evaluation.advisory_experiment freeze --classifier /path/to/saved/model --output tmp/classification-advisory-20261015/run
python -m generation_evaluation.advisory_experiment run --output tmp/classification-advisory-20261015/run --through 24
python -m generation_evaluation.advisory_experiment run --output tmp/classification-advisory-20261015/run --through 48
python -m generation_evaluation.advisory_experiment run --output tmp/classification-advisory-20261015/run --through 64
```

각 구간 후 원응답을 확인한다. 새로운 심각한 위반·업무 전체 거절이 나타나면 다음 구간을 실행하지 않고 근거와 중단 사유를 남긴다. 오류 한 건을 인과적 성능 저하 확정으로 표현하지 않는다. 형식 실패·거절·잘림·timeout을 분모에서 제거하거나 자동 재시도하지 않는다.

`freeze`는 모델 저장본 전체 파일 해시, 예측 라벨·시간·모델 ID, 문서·문항·설정, 각 슬롯의 메시지 해시와 실행 코드 해시를 보존한다. 같은 결과 폴더에 다시 freeze할 수 없다. 실행 중인 동일 폴더는 독점 잠금을 사용한다. 응답 없는 기존 예약은 uncertain으로 중단하며 자동 재호출하지 않는다. 코드·질문·prompt가 달라지면 resume를 거부한다.

최대 호출184회·전체$5·전체2시간, 재시도0회. 추가 API judge는 사용하지 않는다. GPT-6 Luna Standard long-context 상한 입력$0.25/M·출력$0.75/M을 모든 입력에 적용하고 캐시 할인 없이 보수 추정한다. [공식 가격](https://developers.openai.com/api/docs/pricing)을 2026-10-15 확인했다. 실제 청구액이 아니며 사용량 불명은 예약액을 유지한다. 바이트 기반 입력 상한과 최대 출력을 호출 전에 예약한다.

## 판정과 다음 단계

각 응답을 문서·질문별 필수/금지 기준과 대조한다. 합리적인 동등 표현과 질문에 필요하지 않은 추가 안내를 구분한다. 결과 키는 슬롯 ID이며 grade(pass/partial/fail/uncertain), reason, serious, false_rejection, record_sha256를 `judgments.json`에 기록한다. 원응답의 canonical JSON digest에 묶어 다른 응답 판정을 재사용하지 못하게 한다. AI 판정을 사람 승인으로 기록하지 않는다.

탐색64회에서 C의 두 반복 모두 통과 문항이 A/B보다 각각1개 이상 많고, C/W의 중대한 위반 및 W의 정상 업무 전체 거절이 없어야 확인 평가를 실행할 수 있다. 탐색 부적격이면 확인120회와 API 연결·승격을 진행하지 않는다.

```bash
python -m generation_evaluation.advisory_experiment run --output tmp/classification-advisory-20261015/run --through 124
python -m generation_evaluation.advisory_experiment run --output tmp/classification-advisory-20261015/run --through 184
```

확인 단계는 C 안정18/20 이상, A 대비+2문항·B 대비+1문항, 중대한 위반·ID/라벨 노출0, A 안정 통과 문항의 새 누락·왜곡·과잉 거절0을 요구한다. 중앙 지연과 보수 비용은 A 대비 각각20% 미만 증가여야 한다. 이는 실무 기준이며 통계적 우월성 증명이 아니다. 예산·시간 제한으로 미완료면 승격하지 않는다.

기준 통과 후에만 optional classification context를 답변기에 연결하고 서버 `advisory` 모드를 구현한다. client 출처·분류 실패는 A로 정확히 복귀하며 기존 shadow/gate·HTTP 계약을 보존한다. 최신 main의 채택 프로필·모델이 달라졌으면 default 전환을 보류하고 별도 통합 검증 필요로 표시한다.
