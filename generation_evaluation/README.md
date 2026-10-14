# 생성 실행 기록과 기초 집계

사용자가 AI 튜터의 설명·힌트·모범 답안을 참고해 직접 구현 중인 평가 모듈이다. 테스트 작성·검증과 요청한 기록 검증·복원 구현은 AI에 위임했다. 기존 `answer_pipeline/`와 활성 API에는 연결하지 않았고 실제 모델 품질을 측정하지 않았다.

## 코드와 계약

| 파일 | 책임 |
|---|---|
| [types.py](types.py) | GenerationRun: case_id, config, result, elapsed_seconds, error_type |
| [runner.py](runner.py) | 공통 generate_from_documents를 호출하고 perf_counter로 경과 시간 측정 |
| [metrics.py](metrics.py) | 상태별 개수·완료 비율·평균 시간·설정별 그룹화·GenerationSummary 조립 |
| [reporting.py](reporting.py) | 기록 사전 변환·JSONL 저장/읽기·타입 복원 |

run_case에는 질문·문서 문자열 목록·미리 만든 호출 함수를 전달한다. 공통 진입점 generate_from_documents를 사용하며, 경과 시간은 프롬프트 구성·모델 호출·파싱을 포함한다. 문서 읽기와 클라이언트 초기화는 제외한다. 이전의 호출·파싱만 측정한 기록과 측정 범위가 다르므로 구분한다. config는 기록용으로 전달되므로 호출 함수가 실제로 그 설정에서 생성됐는지는 아직 강제하지 않는다.

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

현재 count_outcomes는 결과와 오류가 모두 없으면 ValueError를 발생시킨다. GenerationRun 생성 시 결과와 오류 중 정확히 하나가 있는지, 경과 시간이 유한한 0 이상인지, 오류 이름이 공백이 아닌지 검사한다. 복원 함수는 추가로 필수 키와 필드 타입을 검사한다. 그룹 키에는 데이터·문서 snapshot·프롬프트 버전·실행 회차가 아직 없으므로 실험 동등성의 근거로 사용하지 않는다.

## 저장과 복원

`summarize_runs`는 설정별 GenerationSummary 목록을 반환한다. 빈 입력은 빈 목록이며, 이것은 품질 판정이나 실험 동등성 검증이 아니다.

`save_runs_jsonl(path, runs)`는 원문을 포함한 실행 기록을 UTF-8 JSONL로 저장한다. 직렬화를 먼저 끝내고 상위 디렉터리를 만든 뒤 배타적 생성으로 기존 파일 덮어쓰기를 막는다. NaN·무한대 JSON 직렬화를 거부한다. 디스크 쓰기 실패·프로세스 중단까지 원자적으로 복구하는 방식은 아니다.

`read_runs_jsonl(path)`는 순서를 유지한 객체 목록을 읽고 문법 오류·빈 줄·비객체 행을 줄 번호와 함께 거부한다. `run_from_dict`가 설정·생성 결과를 복원하고 타입·도메인 검증을 적용한다. `None` 결과는 실행 오류 기록이며 timeout 결과와 구별한다.

```python
runs = [run_from_dict(row) for row in read_runs_jsonl(path)]
summaries = summarize_runs(runs)
```

파일 전체 객체 복원 오류에 줄 번호를 붙이는 별도 loader는 아직 없다. 저장 형식에는 schema_version·측정 범위·문서/프롬프트 식별 정보가 없으므로 서로 다른 실행 조건의 파일을 혼합하지 않는다.

## 검증과 다음 단계

저장소 루트에서 실행한다. 가짜 클라이언트·응답·시계만 사용한다.

```bash
uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -v
```

다음은 독립 생성 CLI의 입력 예산과 실제 호출 확인이다. 이후 평가 문항과 고정 문서 snapshot·프롬프트 식별 정보, 품질 판정으로 이어간다. 새 모듈은 아직 설치 패키지 목록에 포함하지 않았다. [생성 모듈](../generation/README.md), [품질 평가 기준](../docs/generation-evaluation.md), [이번 작업 기록](../docs/worklogs/2026-10-14-generation-cli-reporting.md)을 함께 따른다.
