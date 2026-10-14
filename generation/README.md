# 생성 모듈

기존 LangChain 실행기와 분리해 사용자가 단계적으로 구현 중인 모듈이다. 현재는 기본 계약·프롬프트·파싱과 Ollama/OpenAI 연결부를 구현하고 가짜 클라이언트로 검증한 단계이며 `/ask`, `/assistant`, 기존 평가기에 연결하지 않았다. 설치 패키지 배포 설정도 아직 추가하지 않았다.

## 현재 입력과 출력

```text
질문 + 문서 문자열 목록
  → build_prompt → GenerationPrompt(system, user)
  → generate(prompt, model_call)
  → model_call(prompt)의 원문 문자열
  → parse_generation → GenerationResult(status, raw_text, answer)
```

| 파일 | 책임 |
|---|---|
| [config.py](config.py) | 제공자 enum, 모델 이름·유한한 양수 timeout 설정 |
| [providers.py](providers.py) | LangChain 메시지 변환·클라이언트 생성·호출 함수 조립·시간 초과 변환 |
| [types.py](types.py) | 불변 프롬프트·결과 dataclass와 실행 상태 enum |
| [prompts.py](prompts.py) | 사내비의 역할·말투·출력 규칙을 system에, 이번 문서·질문을 user에 구성 |
| [service.py](service.py) | 주입받은 모델 함수 호출과 TimeoutError 처리, 파싱 연결 |
| [validation.py](validation.py) | JSON 구조·문자열 answer 검사, 공백 제거, 원문 보존 |

모델 함수의 계약은 `Callable[[GenerationPrompt], str]`이다. system/user를 SystemMessage/HumanMessage로 변환하고 응답 content가 문자열인지 검사한다. build_model_call은 설정에 따라 Ollama 또는 OpenAI 클라이언트를 생성하고 호출 함수를 반환한다. 생성 시 추론하지 않고 반환된 함수를 호출할 때 invoke를 실행한다. 테스트에서는 클라이언트 생성자와 응답을 대체했다. 사용자가 실제 Ollama 예제를 건너뛰기로 했으므로 새 경로의 실제 연결·모델 가용성·답변 품질은 미검증이다.

| 상태 | 의미 | answer |
|---|---|---|
| COMPLETED | JSON 객체 안에 공백 제거 후 비어 있지 않은 문자열 answer가 있음 | 정리된 문자열 |
| PARSE_ERROR | JSON 구문 오류, 객체가 아닌 루트, answer 누락 또는 문자열이 아님 | None |
| EMPTY_ANSWER | 문자열 answer가 공백 제거 후 비어 있음 | None |
| TIMEOUT | 모델 함수가 TimeoutError를 발생시킴 | None |

응답이 있으면 raw_text는 원문 그대로 보존하고, 시간 초과는 raw_text도 None이다. 다른 예외는 호출자에게 전파한다. generate 자체가 제한 시간을 설정하거나 호출을 중단하지는 않는다. 연결부는 HTTPX TimeoutException과 OpenAI APITimeoutError를 원인을 보존한 TimeoutError로 변환한다. Ollama에는 client_kwargs.timeout, OpenAI에는 timeout과 max_retries=0을 전달한다. 이 timeout은 전체 작업의 절대 마감 시간을 보장하지 않는다. OpenAI 키는 환경에서 관리하며 코드·실험 기록에 저장하지 않는다. 설정은 제공자 enum·비어 있지 않은 모델 이름·유한한 양수 timeout을 검사하지만 모델의 실제 존재나 접근 권한을 검증하지 않는다. 타입 힌트만으로 모든 잘못된 입력을 거부하는 것은 아니다.

COMPLETED는 정확성·근거 충분성·한국어 준수·모델 품질의 합격 판정이 아니다. “문서에서 확인할 수 없습니다”도 형식이 올바르면 COMPLETED다. 현재 최소 출력 계약은 `{"answer": "답변"}`이며 근거 문서 ID·인용 검증·추가 필드 금지 등은 구현하지 않았다. 빈 문서 목록도 프롬프트에 표시한 뒤 모델 함수로 전달할 수 있다. 실제 서비스의 무문서 호출 차단 정책은 별도 연결 대상이다.

## 검증

저장소 루트에서 실행한다. 네트워크·실제 모델 호출 없이 입력 전달, 파싱 경계, 시간 초과와 예외 전달을 확인한다.

```bash
uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -v
```

테스트는 사용자 요청에 따라 AI가 작성·실행한다. 기능 코드는 사용자가 설명·힌트·모범 답안을 참고해 작성했으며, 테스트 통과를 독립 구현 숙련도나 실모델 평가로 해석하지 않는다.

## 평가 실행과 다음 구현

새 [평가 실행 안내](../generation_evaluation/README.md)의 run_case는 이 모듈의 generate를 호출하고 실행 시간·결과·오류 종류를 기록한다. 상태별 개수·완료 비율·전체/완료 평균 시간·설정별 그룹화를 구현했다. 이는 품질 평가 완료나 기존 평가기 교체를 뜻하지 않는다.

1. 설정별 지표 요약과 실행 기록의 무결성·저장 형식 정리.
2. 평가 문항·문서 snapshot·프롬프트 식별 정보와 입력 예산 연결.
3. 정확성·근거·인용 등 품질 판정 및 사람 검수, 실제 모델 비교.
4. 활성 서비스 연결·API 회귀 검증 후 기존 실행기와 평가기를 아카이브로 이동.

설치 패키지 포함과 직접 사용하는 httpx/openai 의존성의 명시적 선언은 배포 구성 단계에서 정리한다. 현재 환경에는 기존 의존성 트리로 설치되어 있다.

기존 `sanaebi_assistant.py`와 `answer_pipeline/`는 아직 활성 코드이며 이동하지 않았다. 목표 설계는 [서비스 아키텍처](../docs/service-architecture.md), 품질 기준은 [생성 평가](../docs/generation-evaluation.md), 이번 학습 기록은 [작업 일지](../docs/worklogs/2026-10-14-generation-adapters-metrics.md)를 따른다.
