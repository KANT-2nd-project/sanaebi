# 서버 요청 흐름 읽기

서버는 질문을 받아 처리 방향을 분류하고, 필요한 경우 게시된 회사 문서로 답변을 생성한다. 분류기는 FastAPI 프로세스 안에서 실행하며 별도 HTTP 서버가 아니다. 설치·실행·첫 분류 확인은 [프로젝트 빠른 시작](../README.md#빠른-시작)을 따른다.

## 서버 시작과 첫 요청

[fastapi_main.py](fastapi_main.py)의 `lifespan`은 SQLite 저장소를 초기화하고 문서 provider·분류기 객체·답변 제공자 설정을 `app.state`에 준비한다. 모델 가중치는 첫 `predict()`에서 읽는다. `GET /` 성공은 서버 응답 확인이며 모델 로딩 성공을 증명하지 않는다.

```mermaid
sequenceDiagram
    participant Client as 클라이언트
    participant HTTP as FastAPI
    participant DI as dependencies
    participant Router as 질문 라우터
    participant Service as 질문 서비스
    participant Model as 분류기
    Client->>HTTP: POST /ask, question
    HTTP->>DI: Depends로 처리 함수 준비
    DI-->>HTTP: 앱 객체를 연결한 handle
    HTTP->>Router: 검증된 요청과 handle
    Router->>Service: handle(question)
    Service->>Model: predict(question)
    opt 아직 로딩되지 않음
        Model->>Model: 로컬 저장본 검증·로딩
    end
    Model->>Model: 토큰화·CPU 추론
    Model-->>Service: 세 라벨 중 하나
    Service->>Service: 라벨별 정책 실행
    Service-->>Router: QuestionResult(text)
    Router-->>HTTP: AnswerResponse
    HTTP-->>Client: JSON 응답
```

FastAPI가 의존성을 해결한 뒤 라우터 본문을 호출한다. 라우터가 DI 함수를 직접 호출하는 것은 아니다. 모델 로딩에 실패하면 정상 라벨 반환 대신 오류 경로로 종료한다. 성공한 모델은 앱 프로세스에서 재사용하며 여러 worker는 각각 별도 모델을 갖는다.

## 질문 한 건이 지나가는 경계

예를 들어 `{"question":"연차 신청 절차 알려줘"}`를 보내면 요청 스키마가 입력을 검사하고 라우터가 앞뒤 공백을 제거해 처리 함수에 전달한다. 이 문장의 실제 라벨은 모델 예측 결과에 따라 정해진다.

| 경계 | 입력 → 출력 | 책임 |
|---|---|---|
| [questions/router.py](questions/router.py) | QuestionRequest → AnswerResponse | HTTP 입력 전달·응답 변환 |
| [dependencies.py](dependencies.py) | 앱 객체 → 질문 처리 함수 | 분류·문서·답변 함수 조립 |
| [questions/service.py](questions/service.py) | 질문과 세 함수 → QuestionResult | 라벨별 호출 순서 결정 |
| [classification/predictor.py](classification/predictor.py) | 문자열 → ClassificationLabel | 저장 모델 추론 |
| [documents/context.py](documents/context.py) | snapshot() → DocumentContextSnapshot | 유효한 게시 문서 확보 |
| [answering/adapter.py](answering/adapter.py) | 질문·snapshot·provider → 문자열 | 기존 실행기 호출·답변 검증 |

### 의존성 조립은 무엇인가

`get_question_handler()`는 `partial()`로 서비스에 세 함수를 미리 연결한다. 아래는 이해를 돕는 동등한 형태이며 실제 코드는 [dependencies.py](dependencies.py)에 있다.

```python
# 개념 예제: 구현을 미리 연결하고 요청마다 question만 받는다.
def handle(question):
    return handle_question(
        question,
        classify=classifier.predict,
        read_documents=document_provider.snapshot,
        answer=selected_answer_function,
    )
```

서비스는 모델 경로나 DB 접속 방법을 몰라도 된다. 테스트에서는 이 함수들을 대체해 모델·LLM 없이 정책을 확인한다. 구현 선택은 조립 계층, 처리 순서는 서비스가 맡는다.

### 라벨에 따라 호출이 달라진다

| 분류·자료 상태 | 반환할 내용 | 요청 중 문서 조회 | 답변 생성 호출 |
|---|---|---:|---:|
| CLARIFY | 질문 구체화 안내 | 없음 | 없음 |
| UNSUPPORTED | 지원 범위 안내 | 없음 | 없음 |
| SEARCH_KNOWLEDGE, 문서 없음 | 자료 없음 안내 | 1회 | 없음 |
| SEARCH_KNOWLEDGE, 문서 있음 | 생성한 답변 | 1회 | 있음 |

라벨은 처리 방향이며 근거 존재를 보장하지 않는다. 허용되지 않은 라벨은 프로그래밍 오류로 처리한다. 비검색 요청에서 문서를 조회하지 않는다는 것은 서버 시작 시 SQLite 초기화도 없다는 뜻은 아니다. 상세 정책과 목표 설계는 [서비스 아키텍처](../docs/service-architecture.md)를 따른다.

### 문서는 한 번 확보해서 전달한다

`DocumentContextProvider.snapshot()`은 SQLite의 유효한 게시본을 읽는다. snapshot에는 본문 외에 문서 ID·개정·제목·출처·메타데이터가 함께 있다. 서비스는 같은 snapshot을 답변기에 전달하고 어댑터는 DB를 다시 읽지 않는다. 현재 이 단계는 게시 문서 공급이며 질문 유사도 기반 벡터 검색은 아니다.

답변 어댑터는 전달받은 질문과 snapshot으로 기존 `sanaebi_assistant.py` 실행기의 선택한 제공자를 호출한다. 실행 성공 여부와 답변 본문을 검증한 뒤 문자열을 반환한다. 별도 `generation/`은 현재 이 서버 경로에 연결되지 않았다. 이후 생성기를 구성할 때도 `질문 + snapshot → 답변 문자열` 경계를 유지하면 서비스 변경을 줄일 수 있다.

## API별 차이와 오류

| API | 사용 목적 |
|---|---|
| `POST /ask` | 분류 → 서비스 정책 → 필요한 경우 문서·답변 생성. `ok`, `text`, `reason` 반환 |
| `POST /classify/koelectra-base` | `/ask`와 같은 분류 객체로 라벨만 확인. `category` 반환 |
| `POST /assistant` | 이미 분류한 `response`·`classification_label`을 기존 실행기에 전달. `/ask` 서비스 경로와 출력 계약이 다름 |

`/ask/langchain`은 없다. `/ask` 성공의 `text`는 고정 안내 또는 생성 답변이며 `reason`은 빈 문자열이다. 입력 검증은 422, 분류 모델·문서 공급 장애는 503, 답변 생성·본문 검증 실패는 502다. 빈 문서의 정상 안내와 저장소 장애를 구분한다. 상세 설정·오류·문서 관리 API 계약은 [서버 규약](../docs/server-conventions.md)과 [문서 관리](../docs/document-management.md)를 따른다.

## 코드 읽는 순서와 진단

1. [진입점](fastapi_main.py): 시작 시 객체와 HTTP 기능 등록.
2. [질문 라우터](questions/router.py) → [의존성](dependencies.py): 요청과 처리 함수 연결.
3. [질문 서비스](questions/service.py): 세 라벨의 처리 순서.
4. [분류기 설명](classification/README.md): 토큰화·점수·라벨 해석.
5. [문서 snapshot](documents/context.py) → [답변 어댑터](answering/adapter.py): 검색 경로의 입력과 출력.

문서 공급 상태는 저장소 루트에서 다음 명령으로 확인한다. 기존 SQLite 게시본의 문서 수와 snapshot 식별값을 읽으며 DB를 생성하거나 변경하지 않는다. DB가 없거나 사용할 수 없으면 오류를 표시한다.

```bash
uv run --locked python -m scripts.inspect_document_context
```

[진단 trace](diagnostics/trace.py)는 선택적 요청·LangChain 기록이다. `TRACE_DIR`을 지정했을 때 기록하며 `TRACE_MAX_CHARS`·`TRACE_FULL_PROMPT`로 기록 길이를 조절한다. 상세 기록 형식은 해당 모듈의 설명을, 변경 기준은 [서버 규약](../docs/server-conventions.md)을 따른다. 문서를 수정하거나 이관하려면 [문서 관리 절차](../docs/document-management.md)를, 전체 문서 탐색은 [문서 색인](../docs/README.md)을 이용한다.
