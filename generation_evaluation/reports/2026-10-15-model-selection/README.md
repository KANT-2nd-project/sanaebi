# 생성 모델 선정 실험 — 2026-10-15

최종 잠정 권장은 **GPT-6 Luna · examples · single · xhigh · 출력 한도 4,096**이다. 새 20문항을 모델별 2회 실행한 결과 중대한 오류 문항은 GPT 0개, Qwen 5개였고, 두 반복 모두 통과한 문항은 각각 11/20, 0/20이었다. 승격 기준 18/20에 미달하여 **기존 기본 설정과 서비스 품질 승인은 보류**한다.

- [최신 선정 결과·한계](reasoning-extension/README.md)
- [최신 20문항별 양 모델 답변·판정·원문 근거](reasoning-extension/comparison.md)
- [추론 확장 개발 실험과 탈락 후보](reasoning-extension/development.md)
- [사전 기준·방법·예산](methodology.md)
- [후속 개선 순서](next-actions.md)
- [작업 일지](../../../docs/worklogs/2026-10-15-generation-selection.md)

## 단계와 자료 경계

1차 개발 88응답과 1차 선정 80응답은 [당시 결과](initial-selection.md), [개발 기록](development.md), [당시 20문항 비교](comparison.md)에 보존한다. 이 디렉터리 바로 아래 summary.json·responses.json·judgments.json·costs.json은 **1차 결과**다.

사용자의 높은 추론 설정 비교 요청 후 개발 56응답을 추가하고, 겹치지 않는 새 20문항·판정 기준을 독립 검토하여 후보와 함께 실행 전에 고정했다. 최신 결과는 reasoning-extension/ 아래에 있다. 서로 다른 두 선정 세트의 점수 차이를 추론 개선의 인과 효과로 해석하지 않는다.

전체 품질 평가 304시도, 내부 호출 308회와 지원 여부 진단 1회였다. [전체 예산](total-budget.json)은 중단 전 기록을 이어받아 마지막 호출까지 활성 82.88분, 보수적 예약·정산액 $2.00353을 기록한다. 사용량이 확인된 표준 단가 추정 소계는 $0.76883이며, 사용량 미확인 9회는 0달러로 처리하지 않고 예약을 유지했다. 실제 청구서 금액은 아니다. 원응답·실패를 분모에서 제외하지 않았다.
