# 생성 모듈

기존 LangChain 실행기와 분리해 사용자가 AI 튜터와 단계적으로 구현 중인 모듈이다. 요청에 따라 일부 검증·복원 함수와 문서 입력·CLI는 AI가 구현했다. 현재는 기본 계약·프롬프트·파싱과 Ollama/OpenAI 연결부를 구현하고 가짜 클라이언트로 검증한 단계이며 `/ask`, `/assistant`, 기존 평가기에 연결하지 않았다. 설치 패키지 배포 설정도 아직 추가하지 않았다.

## 현재 입력과 출력

```text
질문 + 문서 문자열 목록
  → generate_from_documents (공통 진입점)
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
| [documents.py](documents.py) | 명시적 내보내기 JSONL 검사, 문서 ID·개정·제목·본문의 프롬프트 입력 구성 |
| [__main__.py](__main__.py) | 독립 생성 CLI: 인자·문서·모델 조립과 결과 출력 |
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

## 독립 실행

저장소 루트에서 `uv run --locked python -m generation --help`로 인자를 확인한다. 다음은 호출 예시이며 실제 실행 성공 기록이 아니다. 서버나 SQLite를 직접 읽지 않는다.

```bash
uv run --locked python -m generation \
  --documents tmp/evaluation-documents.jsonl \
  --question "연차 신청 절차는 무엇인가요?" \
  --provider ollama \
  --model qwen3:4b-instruct-2507-q4_K_M \
  --timeout 60
```

입력은 기존 `scripts/export_company_knowledge.py --output tmp/evaluation-documents.jsonl`로 내보낸 형식이다. 각 줄은 `document_id`, `revision_number`, `title`, `document`를 가진 객체여야 한다. ID·제목·본문은 비공백 문자열, 개정은 bool이 아닌 1 이상의 정수다. 중복 ID·빈 줄·잘못된 JSON·빈 파일은 거부하며 문서 행 오류에는 줄 번호를 붙인다. 순서·본문을 보존한다. 기존 원본 JSONL에 개정 번호가 없다면 이 입력 계약과 호환되지 않으며 임의 개정을 부여하지 않는다.

CLI는 문서를 모두 검증한 뒤 모델을 생성하고 공통 `generate_from_documents`를 실행한다. stdout에 status·answer·raw_text JSON을 출력한다. COMPLETED는 종료 코드 0, 파싱 실패·빈 답변·timeout은 1이다. 그 밖의 실행 예외는 전파되어 비정상 종료한다. 평가 기록 파일을 자동 저장하지는 않는다.

**입력 토큰 예산 검사·출력 예약량·manifest fingerprint 검증은 아직 없다.** 전체 71건 입력은 기존 실행에서 한도를 초과했다. 현재 CLI를 전체 문서 품질 평가에 사용하기 전 모델별 입력 한도를 확인해야 한다. 본문 절단·문서 선별·모델 다운로드를 자동 수행하지 않는다. 실행 시 OpenAI provider는 유료 호출과 외부 문서 전송이 될 수 있으며 인증은 환경에서 관리한다.

GenerationResult 생성 시 필드 타입과 상태별 원문·답변 조합을 검증한다. COMPLETED는 비공백 답변과 원문 문자열, TIMEOUT은 둘 다 None, 나머지 실패는 원문 문자열과 answer=None을 요구한다. 이 검사는 원문을 재파싱하거나 사실성을 판정하지 않는다.

## 검증

저장소 루트에서 실행한다. 네트워크·실제 모델 호출 없이 입력 전달, 파싱 경계, 시간 초과와 예외 전달을 확인한다.

```bash
uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -v
```

테스트는 사용자 요청에 따라 AI가 작성·실행한다. 공통 생성 진입점 등은 사용자가 작성했고, 위임받은 구현·테스트는 AI가 수행했으며, 테스트 통과를 독립 구현 숙련도나 실모델 평가로 해석하지 않는다.

## 채택한 진행 방향

얇은 LangChain 어댑터를 유지하고 생성 모듈·평가를 서버와 독립적으로 먼저 검증한다. 공통 생성 경로를 실제 실행 진입점에 연결하면서 필요한 계약과 검증을 확장한다. 문서 snapshot·입력 예산·구조화 출력·인용 검증이 목표이며, 별도 서버 연결과 기존 코드 아카이브는 대체 경로 검증 후 진행한다. LangGraph·검색 도입은 현재 필수로 채택하지 않았다.

## 평가 실행과 다음 구현

새 [평가 실행 안내](../generation_evaluation/README.md)의 run_case는 이 모듈의 generate_from_documents를 호출하고 실행 시간·결과·오류 종류를 기록한다. 상태별 개수·완료 비율·전체/완료 평균 시간·설정별 그룹화를 구현했다. 이는 품질 평가 완료나 기존 평가기 교체를 뜻하지 않는다.

1. 독립 CLI에 실제 모델별 입력 예산·출력 예약량을 연결하고 소규모 호출 검증.
2. 평가 문항·문서 snapshot·프롬프트 식별 정보와 구조화 출력·인용 검사 연결.
3. 정확성·근거·인용 등 품질 판정 및 사람 검수, 실제 모델 비교.
4. 활성 서비스 연결·API 회귀 검증 후 기존 실행기와 평가기를 아카이브로 이동.

설치 패키지 포함과 직접 사용하는 httpx/openai 의존성의 명시적 선언은 배포 구성 단계에서 정리한다. 현재 환경에는 기존 의존성 트리로 설치되어 있다.

기존 `sanaebi_assistant.py`와 `answer_pipeline/`는 아직 활성 코드이며 이동하지 않았다. 목표 설계는 [서비스 아키텍처](../docs/service-architecture.md), 품질 기준은 [생성 평가](../docs/generation-evaluation.md), 이번 학습 기록은 [작업 일지](../docs/worklogs/2026-10-14-generation-cli-reporting.md)를 따른다.
