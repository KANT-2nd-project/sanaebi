# 생성 실행 기록과 기초 집계

사용자가 AI 튜터의 설명·힌트·모범 답안을 참고해 직접 구현 중인 평가 모듈이다. 테스트 작성·검증은 AI에 위임했다. 기존 `answer_pipeline/`와 활성 API에는 연결하지 않았고 실제 모델 품질을 측정하지 않았다.

## 코드와 계약

| 파일 | 책임 |
|---|---|
| [types.py](types.py) | GenerationRun: case_id, config, result, elapsed_seconds, error_type |
| [runner.py](runner.py) | 같은 생성 함수 generate를 호출하고 perf_counter로 경과 시간 측정 |
| [metrics.py](metrics.py) | 상태별 개수·완료 비율·평균 시간·설정별 그룹화 |

run_case에는 프롬프트와 호출 함수를 미리 만들어 전달한다. 경과 시간은 generate의 호출·파싱 구간이며 초기화·프롬프트 구성은 제외한다. config는 기록용으로 전달되므로 호출 함수가 실제로 그 설정에서 생성됐는지는 아직 강제하지 않는다.

정상·파싱 실패·빈 답변·시간 초과는 GenerationResult와 error_type=None으로 기록한다. 그 밖에 generate가 전파한 Exception은 result=None과 예외 클래스 이름으로 기록하며 시간도 남긴다. 평가 경계의 광범위한 예외 처리는 구현 버그도 포착할 수 있으므로 실행 오류를 숨기거나 성공으로 집계하지 않는다. KeyboardInterrupt는 전파한다. 전체 traceback과 상세 오류 메시지는 아직 보존하지 않는다.

## 집계 의미

| 함수 | 의미 | 빈 입력 |
|---|---|---|
| count_outcomes | total, completed, parse_error, empty_answer, timeout, execution_error 개수 | 모든 값 0 |
| completion_rate | completed / 전체 시도 수, 실패도 분모에 포함 | None |
| mean_attempt_seconds | 실패 포함 전체 기록의 평균 시간 | None |
| mean_completed_seconds | 오류 없고 결과가 COMPLETED인 기록만의 평균 시간 | None |
| group_by_config | 제공자·모델 이름·제한 시간이 같은 기록을 리스트로 묶음 | 빈 사전 |

COMPLETED는 기본 형식의 답변을 얻었다는 뜻이며 정답률·근거 충실성 판정이 아니다. 완료 비율과 실패 개수를 평균 시간과 함께 봐야 빠른 연결 실패를 모델 응답 속도로 오해하지 않는다. 예를 들어 정상 2초·4초, 시간 초과 30초, 연결 실패 0.2초면 전체 평균은 9.05초, 완료 평균은 3초다. 이는 설명용 숫자이지 실모델 측정 결과가 아니다.

현재 count_outcomes는 결과와 오류가 모두 없으면 ValueError를 발생시킨다. 다만 GenerationRun 생성 시 상태 간 모순·경과 시간의 유한성 등을 전부 검증하는 것은 아니다. 외부 파일을 받아들이기 전에 무결성 검증을 추가해야 한다. 그룹 키에는 데이터·문서 snapshot·프롬프트 버전·실행 회차가 아직 없으므로 실험 동등성의 근거로 사용하지 않는다.

## 검증과 다음 단계

저장소 루트에서 실행한다. 가짜 클라이언트·응답·시계만 사용한다.

```bash
uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -v
```

다음은 설정별 요약 타입·집계 조립이다. 이후 기록 무결성·저장 형식, 평가 문항과 고정 문서 snapshot·프롬프트 식별 정보, 품질 판정으로 이어간다. 새 모듈은 아직 설치 패키지 목록에 포함하지 않았다. [생성 모듈](../generation/README.md), [품질 평가 기준](../docs/generation-evaluation.md), [이번 작업 기록](../docs/worklogs/2026-10-14-generation-adapters-metrics.md)을 함께 따른다.
