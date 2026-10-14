# 생성 모듈

기존 LangChain 실행기와 분리해 사용자가 단계적으로 구현 중인 모듈이다. 현재는 저장소 루트에서 실행하는 기본 계약·프롬프트·파싱·호출 연결 단계이며 `/ask`, `/assistant`, 기존 평가기에 연결하지 않았다. 설치 패키지 배포 설정도 아직 추가하지 않았다.

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
| [types.py](types.py) | 불변 프롬프트·결과 dataclass와 실행 상태 enum |
| [prompts.py](prompts.py) | 사내비의 역할·말투·출력 규칙을 system에, 이번 문서·질문을 user에 구성 |
| [service.py](service.py) | 주입받은 모델 함수 호출과 TimeoutError 처리, 파싱 연결 |
| [validation.py](validation.py) | JSON 구조·문자열 answer 검사, 공백 제거, 원문 보존 |

모델 함수의 계약은 `Callable[[GenerationPrompt], str]`이다. 아직 실제 모델 구현은 없고 테스트에서는 가짜 함수를 사용한다. system/user 필드는 내부 문자열이며 실제 LangChain 메시지 역할로 변환하는 어댑터가 필요하다.

| 상태 | 의미 | answer |
|---|---|---|
| COMPLETED | JSON 객체 안에 공백 제거 후 비어 있지 않은 문자열 answer가 있음 | 정리된 문자열 |
| PARSE_ERROR | JSON 구문 오류, 객체가 아닌 루트, answer 누락 또는 문자열이 아님 | None |
| EMPTY_ANSWER | 문자열 answer가 공백 제거 후 비어 있음 | None |
| TIMEOUT | 모델 함수가 TimeoutError를 발생시킴 | None |

응답이 있으면 raw_text는 원문 그대로 보존하고, 시간 초과는 raw_text도 None이다. 다른 예외는 호출자에게 전파한다. generate 자체가 제한 시간을 설정하거나 호출을 중단하지는 않는다. 타입 힌트는 런타임 입력 검증이 아니다.

COMPLETED는 정확성·근거 충분성·한국어 준수·모델 품질의 합격 판정이 아니다. “문서에서 확인할 수 없습니다”도 형식이 올바르면 COMPLETED다. 현재 최소 출력 계약은 `{"answer": "답변"}`이며 근거 문서 ID·인용 검증·추가 필드 금지 등은 구현하지 않았다. 빈 문서 목록도 프롬프트에 표시한 뒤 모델 함수로 전달할 수 있다. 실제 서비스의 무문서 호출 차단 정책은 별도 연결 대상이다.

## 검증

저장소 루트에서 실행한다. 네트워크·실제 모델 호출 없이 입력 전달, 파싱 경계, 시간 초과와 예외 전달을 확인한다.

```bash
uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -v
```

테스트는 사용자 요청에 따라 AI가 작성·실행한다. 기능 코드는 사용자가 설명·힌트·모범 답안을 참고해 작성했으며, 테스트 통과를 독립 구현 숙련도나 실모델 평가로 해석하지 않는다.

## 다음 구현 순서

1. GenerationPrompt를 실제 system/user 메시지로 변환하는 LangChain 어댑터와 문자열 응답 경계.
2. 모델 설정·실제 timeout·공급자 오류 변환, 입력 예산과 문서 snapshot 메타데이터.
3. 서비스와 평가기가 같은 생성 경로를 호출하도록 연결하고 API 회귀 검증.
4. 평가 데이터·실행 기록·품질 판정을 분리하고 같은 문서 snapshot으로 모델 비교.
5. 대체 경로 검증 후 기존 실행기·평가기를 커밋·실행 방법과 함께 아카이브로 이동.

기존 `sanaebi_assistant.py`와 `answer_pipeline/`는 아직 활성 코드이며 이동하지 않았다. 목표 설계는 [서비스 아키텍처](../docs/service-architecture.md), 품질 기준은 [생성 평가](../docs/generation-evaluation.md), 이번 학습 기록은 [작업 일지](../docs/worklogs/2026-10-14-generation-foundation.md)를 따른다.
