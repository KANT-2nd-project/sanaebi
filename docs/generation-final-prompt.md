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

결정·기록 정리 과정에서 실행 코드나 CLI/서버 기본 설정은 변경하지 않았다. 선택된 프로필을 실제 호출 경로에 연결하는 작업과 서비스 품질 검증은 별도이며, 추가 프롬프트 튜닝 실험은 계획하지 않는다.

[전체 과정·기록 점검](../generation_evaluation/reports/2026-10-15-luna-tuning-closure/README.md)과 [종료 일지](worklogs/2026-10-15-generation-prompt-tuning-closure.md)에서 실험별 결과, 중단·미판정 항목, 연구 근거, 추가4문항과 최종 결정을 확인할 수 있다.
