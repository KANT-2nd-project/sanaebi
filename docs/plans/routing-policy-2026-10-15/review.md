# 구현 전 계획 검수 — 2026-10-15

상태: **계획 검수 통과 / 구현·실험 미착수**. 사용자가 다음 단계에서 직접 구현한다.

## 검수 범위

별도 AI reviewer가 결정·구현 계획을 현재 `app/settings.py`, `app/fastapi_main.py`, `app/dependencies.py`, `app/questions/service.py`, `app/answering/router.py`, `app/classification/predictor.py`, `app/diagnostics/trace.py`, 생성 어댑터와 대조했다. 실제 코드 수정이나 모델 호출, 사용자 숙련도 검증은 하지 않았다.

현재 코드의 두 모드 정책 제안, 알려진 분류 오류와 예상 밖 오류 구분, /assistant의 앞 단계 실패·라벨 유효성·client 출처, 동기 추론 지연, 기본 gate 유지, v1 프롬프트·모델 고정, 과거 결과 보존을 확인했다.

## 발견과 수정

| 지적 | 근거 | 반영 |
|---|---|---|
| P2: 메타데이터 수집 경로 미정 | HTTP 응답은 라벨/사용량을 포함하지 않음. TRACE_DIR 미설정 시 record 함수 no-op | 격리된 모드별 프로세스의 ASGI/TestClient, 실행 전용 trace 활성화, trace 헤더와 slot 연결, 누락 시 중단/uncertain 명시 |
| P2: 실제 생성 전 예약 지점 미정 | HTTP 요청 전에 무조건 예약하면 gate 미호출까지 생성으로 계산됨 | 평가 전용 answerer wrapper가 원장에 원자 예약한 뒤 실제 answerer를 한 번 호출. 예약 실패 시 미호출, 실패/timeout/uncertain 예약 유지 |

전역 앱의 동시 lifespan 간섭을 막기 위해 모드별 프로세스를 격리하고 임시 DB 설정을 lifespan 전에 준비한다. 실제 서비스 DB는 접근하지 않는 계획이다. 원장은 프로세스 간 트랜잭션/잠금·slot 고유 제약을 사용하며 trace 저장과 독립적이다.

해당 수정 후 동일 검수자가 다시 확인하여 **추가 중대한 누락 없음, 사용자 구현 착수 가능한 계획**으로 판단했다. 이 판정은 실제 구현의 안전성·회귀 통과·서비스 품질 승인을 뜻하지 않는다.

## 남은 실행 전 확정 사항

- 40문항·두 반복·최대160 생성 시도 및 제안 품질 기준을 실제 실행 전에 고정한다.
- 금액·전체 시간·지연 수용 한도는 실험 시작 전에 사용자가 정한다. 현재 실험 실행 승인은 요청하지 않았고 호출하지 않았다.
- 최신 main과 사용자 작업을 다시 대조한다. 문서 게시 브랜치 전체를 무심코 병합하지 않는다.
- 프롬프트 고정 상태에서 범위 밖 질문을 잘 처리하는지는 미검증이다. 결과가 나쁘면 기본 gate 유지·보류로 기록한다.

[최종 계획](implementation-plan.md) · [사용자 채택 방향](decision.md) · [공식 근거](references.md)
