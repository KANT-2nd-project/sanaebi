# GPT-6 Luna 최종 프롬프트 결정

2026-10-15 사용자는 **답변 범위 보강안 `examples_answer_scope_v1`을 최종 선택하고 프롬프트 튜닝을 종료**했다. 이 문서가 현재 채택 결정의 기준이다. 과거 보고서의 `examples 유지`나 `scope 탈락`은 해당 실험 시점의 판단으로 보존한다.

| 항목 | 최종 선택 |
|---|---|
| 모델 | GPT-6 Luna (`gpt-6-luna`) |
| 프로필 | `examples_answer_scope_v1` |
| 전략 | `single` |
| 추론 | `xhigh` |
| 최대 출력 | 4096토큰 |
| 호출 timeout | 180초 |
| 출력 모드 | `prompt_json` |
| temperature | 전달하지 않음 |

[기계 판독 설정](../generation_evaluation/reports/2026-10-15-luna-tuning-closure/adopted-config.json)과 [최종 system 프롬프트](../generation_evaluation/reports/2026-10-15-luna-tuning-closure/adopted-system-prompt.txt)를 보존했다. 실제 프롬프트는 `generation/prompts.py`의 공통 규칙에 `generation/profiles.py`의 보강 프로필을 더해 구성한다. 사용자 질문과 문서는 호출별 user 메시지에 포함된다.

이번 선택은 알려진 누락과 평가 한계를 본 뒤 사용자가 내린 최종 구성 결정이다. **과거 회귀 게이트 통과나 서비스 품질 승인으로 바꿔 기록하지 않는다.** 보강안의 신고 목격자 정보 누락은 추가 확인에서도 재현됐다. 신규 선정20문항·반복 안정성은 미측정이며, strict 출력은 선택하지 않는다.

최초 결정·기록 정리에서는 실행 코드를 변경하지 않았다. 이후 사용자 요청으로 독립 generation·generation_evaluation 및 generate_from_documents/run_case의 기본값을 위 최종 구성에 연결했다. models.json에는 Luna 하나만 두고 company-final-v1을 기본 프리셋으로 사용한다. 서버 연결·서비스 품질 승인은 별도이며 추가 튜닝은 수행하지 않았다. [실행 반영·검증 기록](worklogs/2026-10-15-generation-final-runtime.md)을 따른다.

[전체 과정·기록 점검](../generation_evaluation/reports/2026-10-15-luna-tuning-closure/README.md)과 [종료 일지](worklogs/2026-10-15-generation-prompt-tuning-closure.md)에서 실험별 결과, 중단·미판정 항목, 연구 근거, 추가4문항과 최종 결정을 확인할 수 있다.

사용자의 후속 병합 요청에 따라 위 독립 런타임 구성을 main에도 통합했다. 이전 일지의 생성 브랜치 게시·main 미병합은 당시 상태로 보존한다. [통합 게시 기록](worklogs/2026-10-15-main-publication.md)을 따른다. 이후 별도 서버 통합 작업에서 `/ask`·`/assistant`도 같은 최종 구성에 연결했다. 채택한 프롬프트 본문은 수정하지 않았다. [서버 통합 검증과 한계](worklogs/2026-10-15-server-generation-integration.md)를 함께 확인한다.

## 후속: 출처 표시·문서 충실성 개선 검증

2026-10-15 사용자의 추가 요청으로 `examples_answer_scope_v2`를 별도 구현·평가했다. 내부 ID 대신 문서 제목·항목을 표시하고, 문서의 특이함만으로 작성 의도를 추측하지 않도록 보강한 후보다. 실제82회 평가에서 목표 사례 개선은 확인했지만 JSON 실패2건과 신고 필수 정보의 새 누락이 나와 **기본값 승격을 보류하고 v1을 유지**한다. 기존 튜닝 종료는 당시 결정이며 이번 요청에 따른 후속 검증과 구분한다. [결과·판정·한계](../generation_evaluation/reports/2026-10-15-answer-grounding/README.md)를 따른다. API 계약·모델·프런트엔드 변경이나 공개 서버 배포는 하지 않았다.

## 후속: 두 규칙만 추가한 v3 검증

2026-10-15 추가 요청에 따라 v1에 출처 표시·불필요한 추측 금지 두 규칙만 추가한 `examples_answer_scope_v3`를 검증했다. 초기24회는 모두 정상 JSON이고 ID 비노출 목표를 확인했지만 신고 필수 입력 정보 누락이 남아 확대 평가·기본값 전환을 보류했다. **현재 기본값은 계속 v1이다.** 형식 실패가 없어 strict 후속 조건은 충족되지 않았고 API·브라우저 검증·공개 배포는 실행하지 않았다. [v3 결과·판정과 한계](../generation_evaluation/reports/2026-10-15-answer-grounding-v3/README.md)를 따른다. v2·v3는 명시적으로 선택하는 실험 프로필이며 현재 서비스 동작 보장으로 해석하지 않는다.

## 후속: 소표본 변동 재검증

사용자의 반복 검증·중간 중단 요청으로 새 신고 응답 각25회를 비교했다. 엄격 기준 완전 응답은 v1 15/25, v3 20/25였으며 이전2회 결과를 v3 성능 저하의 증거로 해석할 수 없다. 두 후보 모두 누락이 남고 조기 중단·단일 질문 한계가 있어 우월성·동등성·전체 품질을 확정하지 않는다. **기본값은 v1 유지**다. [반복 결과·신뢰구간·기준 민감도](../generation_evaluation/reports/2026-10-15-answer-grounding-repeat/README.md)를 따른다. 이전의 채택 보류 기록과 통계적 성능 판단을 구분한다.
