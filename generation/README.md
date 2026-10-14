# 생성 모듈

기존 LangChain 실행기와 분리해 사용자가 AI 튜터와 단계적으로 구현 중인 모듈이다. 요청에 따라 일부 검증·복원 함수와 문서 입력·CLI는 AI가 구현했다. 기본 계약·프롬프트·파싱과 Ollama/OpenAI 연결부를 구현했고, 사용자가 수행한 로컬 Ollama 문서 한 건 smoke의 저장 결과를 확인했다. 정식 품질 평가는 아니며 `/ask`, `/assistant`, 기존 평가기에 연결하지 않았다. 설치 패키지 배포 설정도 아직 추가하지 않았다.

## 현재 입력과 출력

```text
질문 + 문서 문자열 목록
  → generate_from_documents (공통 진입점)
  → build_prompt → GenerationPrompt(system, user)
  → generate(prompt, model_call)
  → model_call(prompt)의 ModelResponse(원문·사용량·종료 사유)
  → 길이 제한 판정 / parse_generation
  → GenerationResult(status, raw_text, answer, input_tokens, output_tokens, finish_reason)
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

모델 함수의 계약은 `Callable[[GenerationPrompt], ModelResponse]`이다. system/user를 SystemMessage/HumanMessage로 변환하고 응답 content가 문자열인지 검사한다. build_model_call은 설정에 따라 Ollama 또는 OpenAI 클라이언트를 생성하고 호출 함수를 반환한다. 생성 시 추론하지 않고 반환된 함수를 호출할 때 invoke를 실행한다. 테스트에서는 클라이언트 생성자와 응답을 대체했다. 이후 사용자가 로컬 Ollama로 명시 사실·자료 부족·업무 처리 요청 사례를 실행했다. 해당 저장 결과는 [실행·변경 기록](../docs/worklogs/2026-10-15-generation-presets-usage-policy.md)에 정리했다. 이후 전체 문서 실측과 GPT 비교를 진행했으며 최신 결과는 [GPT 비교 일지](../docs/worklogs/2026-10-15-generation-openai-comparison.md)를 따른다.

| 상태 | 의미 | answer |
|---|---|---|
| COMPLETED | JSON 객체 안에 공백 제거 후 비어 있지 않은 문자열 answer가 있음 | 정리된 문자열 |
| PARSE_ERROR | JSON 구문 오류, 객체가 아닌 루트, answer 누락 또는 문자열이 아님 | None |
| EMPTY_ANSWER | 문자열 answer가 공백 제거 후 비어 있음 | None |
| TIMEOUT | 모델 함수가 TimeoutError를 발생시킴 | None |
| TRUNCATED | finish_reason이 length여서 출력 길이 제한 종료로 판정 | None |

응답이 있으면 raw_text는 원문 그대로 보존하고, 시간 초과는 raw_text도 None이다. 다른 예외는 호출자에게 전파한다. generate 자체가 제한 시간을 설정하거나 호출을 중단하지는 않는다. 연결부는 HTTPX TimeoutException과 OpenAI APITimeoutError를 원인을 보존한 TimeoutError로 변환한다. Ollama에는 client_kwargs.timeout과 num_ctx·num_predict를 전달한다. OpenAI에는 timeout과 max_retries=0을 전달한다. max_output_tokens는 max_completion_tokens로, 지정된 reasoning_effort·temperature는 해당 제공자 인자로 전달한다. OpenAI context_window 요청은 거부한다. reasoning_effort는 OpenAI에서만 허용하며 명시적 추론 활성화와 temperature 동시 지정은 거부한다. temperature는 bool이 아닌 유한한 0~2 숫자다. 이 timeout은 전체 작업의 절대 마감 시간을 보장하지 않는다. OpenAI 키는 환경에서 관리하며 코드·실험 기록에 저장하지 않는다. 설정은 제공자 enum·비어 있지 않은 모델 이름·유한한 양수 timeout을 검사하지만 모델의 실제 존재나 접근 권한을 검증하지 않는다. 타입 힌트만으로 모든 잘못된 입력을 거부하는 것은 아니다.

COMPLETED는 정확성·근거 충분성·한국어 준수·모델 품질의 합격 판정이 아니다. “문서에서 확인할 수 없습니다”도 형식이 올바르면 COMPLETED다. 현재 최소 출력 계약은 `{"answer": "답변"}`이며 근거 문서 ID·인용 검증·추가 필드 금지 등은 구현하지 않았다. 빈 문서 목록도 프롬프트에 표시한 뒤 모델 함수로 전달할 수 있다. 실제 서비스의 무문서 호출 차단 정책은 별도 연결 대상이다.

## 독립 실행

저장소 루트에서 실행한다. 모델 설정은 [models.json](models.json), 문서와 모델 목록은 [experiments.json](experiments.json)에서 한 번 읽는다. 모델은 별칭으로 선택하며 실제 provider·model_name·timeout·문맥/출력 한도는 설정에서 가져온다. 문서 상대 경로는 저장소 루트 기준이다. 인증값은 설정 파일에 넣지 않는다.

```bash
uv run --locked python -m generation --help
uv run --locked python -m generation \
  --experiment company-smoke-v1 \
  --model qwen3-4b-q4km \
  --question "예정된 연차는 언제까지 어디에서 신청해야 하나요?"
```

**입력 파일은 저장소에 포함하지 않는다.** 기존 `scripts/export_company_knowledge.py --output tmp/generation-cli-documents.jsonl`로 내보낸 71건 snapshot에서 문서 한 건을 내용 변경 없이 `tmp/generation-smoke-documents.jsonl`로 복사해야 smoke 실험을 실행할 수 있다. 전체 baseline과 한 건 smoke는 별도 실험이다. 이 설정은 전체 문서가 모델 입력 한도에 맞는다는 보장이 아니다.

각 JSONL 행은 document_id·revision_number·title·document가 필요하다. 문자열은 비공백이어야 하며 개정은 bool이 아닌 1 이상의 정수다. 중복 ID·빈 줄·잘못된 JSON·빈 파일을 거부하며 행 오류에는 줄 번호를 붙인다. 원문·순서를 보존하고 개정이 없는 과거 원본에 임의 개정을 부여하지 않는다.

context_window와 max_output_tokens는 선택값이며 지정 시 양의 정수여야 한다. 둘 다 있으면 출력 한도는 문맥보다 작아야 한다. 입력 토큰 수·출력 예약량을 합한 예산 검사는 아직 없다. 전체 71건은 과거 실행에서 한도를 초과했다. 정확한 사전 토큰 계산, manifest fingerprint 검증, 설치 패키지 배포는 후속이다. 본문 절단·자동 문서 선별·모델 다운로드는 하지 않는다.

CLI는 문서 읽기·클라이언트 생성 후 run_case로 공통 생성 경로를 호출한다. stdout에는 case_id=manual, config, result, elapsed_seconds, error_type과 experiment·model_alias·question을 출력한다. result 안에 상태·답변·원문·입출력 토큰·종료 사유가 있다. COMPLETED는 종료 코드 0, 나머지 결과 또는 실행 오류는 1이다. 문서 읽기·클라이언트 생성 실패는 run_case 이전이라 기록 없이 예외로 종료한다. 파일 자동 저장은 하지 않으며 쉘 리다이렉션은 기존 파일을 덮어쓸 수 있다.

사용량 누락은 None으로 보존하고 0과 구별한다. Ollama done_reason 또는 OpenAI finish_reason을 기록하며 length는 JSON 파싱보다 먼저 TRUNCATED로 판정한다. 그 밖의 종료 사유·거절을 모두 분류한 상태는 아니다. 제공자가 보고한 호출 후 토큰 수는 입력 전체가 누락 없이 처리됐다는 보증이나 사전 예산 검사가 아니다.

시스템 프롬프트에는 사내비 역할·근거 제한·자료 부족 안내·문서 속 지시 무시·한국어 말투·JSON 형식을 둔다. 현재 신청·변경·취소·승인·개인 상태 조회를 실행하지 않으며 허위 완료·허위 조회를 주장하지 않도록 명시한다. 문서는 user 메시지의 데이터다. 규칙이 전달되는 단위 검사와 모델이 실제 따르는지 확인하는 검증은 구분한다.

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

문서/프롬프트 SHA-256·문서 수와 전체 문서 배치 기록을 연결했고, 전체 입력의 속도 및 소수 답변의 근거를 검토했다. 다음은 다음 순서로 진행한다.

1. 답변 가능성·필수 근거·조건을 고정한 평가셋과 입력·출력 예산 검사.
2. 근거 추출과 최종 답변을 분리해 검사하고 같은 작은 근거 묶음으로 다른 모델 비교.
3. 구조화된 근거·인용 검사와 실제 문서 선택기, 사람 품질 검수.
4. 활성 서비스 연결·API 회귀 검증 후 기존 실행기와 평가기를 아카이브로 이동.

설치 패키지 포함과 직접 사용하는 httpx/openai 의존성의 명시적 선언은 배포 구성 단계에서 정리한다. 현재 환경에는 기존 의존성 트리로 설치되어 있다.

기존 `sanaebi_assistant.py`와 `answer_pipeline/`는 아직 활성 코드이며 이동하지 않았다. 목표 설계는 [서비스 아키텍처](../docs/service-architecture.md), 품질 기준은 [생성 평가](../docs/generation-evaluation.md), 이번 학습 기록은 [작업 일지](../docs/worklogs/2026-10-15-generation-presets-usage-policy.md)를 따른다.

## 전체 문서 긴 문맥 실험 설정

`qwen3-4b-q4km-96k`는 기존 별칭을 보존하고 추가한 실험용 설정이다. 문맥 98,304, 출력 한도 1,024, timeout 1,800초이며 `company-full-context-v1`에서 전체 문서 snapshot을 사용한다. 2026-10-15 RQ0001 한 건을 문서 71건으로 실행해 입력 67,665·출력 111토큰, completed/stop, 약 374.7초를 확인했다. 문서 증가 여유는 이번 입력과 출력 예약 기준 29,615토큰이다. 문서 개수나 다른 질문의 입력량을 보증하지 않는다.

Ollama 보고 모델·캐시 할당은 약 16.6 GiB였고 CPU 사용이 컸다. 이 설정은 전체 입력 실행 확인용이며 실시간 서비스 성능을 확보했다는 의미가 아니다. 문서 추가 시 새 snapshot과 실험 기록을 보존하고 입력·출력 예산 및 메모리·지연을 다시 확인한다. 정확한 사전 토큰 검사는 아직 없으며 한도 초과 시 자동 절단하지 않는다. 상세 원자료는 로컬 `tmp/generation-full-context-96k/20261015-063818/README.md`에 있다.

### 로컬 GPU 실험 실행

RTX5060 Laptop8GB / Ollama0.33.3에서 긴 문맥의 KV 캐시와 GPU 배치를 조정하는 별도 실행기를 추가했다. 시스템 Ollama 설정은 그대로 유지한다. 다른 모델 작업과 GPU 메모리를 공유하면 배치·속도가 달라지므로 같은 조건인지 확인한다.

터미널 하나에서 실행한다. 기존 11434 서비스에 모델이 적재되어 있으면 먼저 본인이 실행한 모델을 내려 GPU 공간을 확보한다.

```bash
bash scripts/serve_generation_ollama.sh
```

다른 터미널에서 기존 CLI를 연결한다. OLLAMA_HOST는 서버 환경과 **호출 프로세스 양쪽**에 필요하며, 아래처럼 지정하지 않으면 기존 기본 서버로 연결된다.

```bash
OLLAMA_HOST=http://127.0.0.1:11435 uv run --locked python -m generation \
  --experiment company-full-context-v1 \
  --model qwen3-4b-q4km-96k \
  --question "영수증을 분실했을 때 어떻게 정산하나요?"
```

실행기는 loopback11435, Flash Attention, KV cache q4_0, 동시 요청1개, 모델1개, backend fit 여유256MiB를 사용한다. 기본 모델 파일 경로는 `/usr/share/ollama/.ollama/models`이며 `OLLAMA_MODELS`로 변경할 수 있다. 설치 모델을 재사용하고 자동 내려받기·정리는 하지 않는다. `LLAMA_ARG_FIT_TARGET`은 설치된 llama backend 옵션으로 버전 변경 시 다시 확인해야 한다. 이번 로그의 37/37 GPU 배치가 다른 GPU·동시작업·버전에서도 보장되는 것은 아니다.

가중치 Q4_K_M과 KV cache q4_0는 서로 다른 설정이다. 캐시 압축은 품질에도 영향을 줄 수 있으므로 기본 서비스 정책으로 일괄 채택한 것은 아니다. [실측·품질 검토 일지](../docs/worklogs/2026-10-15-generation-tps-quality.md)와 로컬 `tmp/generation-tps-quality-20261015/README.md`를 따른다.

OpenAI GPT-6 Luna와 로컬 GPU 프로필의 실행·키 로딩·측정 기준은 [생성 실행 설정](../docs/generation-runtime.md)을 따른다.
