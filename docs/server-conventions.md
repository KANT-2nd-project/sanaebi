# 서버 구성과 변경 규약

이 문서는 Sanaebi 서버 코드를 수정하거나 확장할 때의 책임 분리와 검증 기준을 정한다. 서비스가 무엇을 처리하는지는 [서비스 설계](service-architecture.md), 라벨 의미는 [라벨 기준](label-taxonomy.md)을 따른다.

현재 서버는 앱 진입점, 스키마, 라우터와 저장 함수로 분리되어 있다. `POST /ask`는 [질문 라우터](../app/routers/questions.py)에서 KoELECTRA Base 분류 후 LangChain을 호출하고, `PROVIDER`로 선택한 모델(기본 Ollama)의 답변 text를 AnswerResponse로 반환한다. 분류 모델 파일 부재는 503, 모델 호출 실패·사용 불가 답변은 502로 반환한다. `/ask/langchain`은 제거했으며 `/assistant`는 이미 분류한 입력을 받는 경로로 유지한다.

[질문 서비스](../app/services/question_service.py)의 `handle_question`과 [dependencies.py](../app/dependencies.py)는 기존 분기 정책·미완성 답변기 조립 초안으로 보존한다. 현재 `/ask`가 이 초안을 사용하지는 않는다. 새 라우터는 분류기와 LangChain 연결 함수를 직접 호출한다. 모델 수명주기·추론 동시성·권한·운영 구성 및 목표 분기 정책 정합성은 후속 과제다. 실제 모델 품질이나 최종 모델 선정 완료를 뜻하지 않는다.

분류 확인용 `POST /classify/koelectra-base`는 [분류 라우터](../app/routers/classification.py)에서 [KoELECTRA 연동 함수](../app/koelectra_classifier.py)를 호출한다. 첫 요청에서 로컬 저장 모델을 캐시하며 재학습 없이 카테고리를 반환한다.

## 책임과 의존 방향

| 구성 | 책임 | 경계 |
|---|---|---|
| 앱 진입점 | 앱 생성, 라우터와 공통 오류 처리 연결 | 질문 처리 정책이나 파일 저장 구현을 모으지 않는다. |
| 스키마 | HTTP 요청·응답의 필드와 검증 | 저장 방식이나 모델 초기화를 담당하지 않는다. |
| 라우터 | 요청 전달, HTTP 응답과 상태 코드 | SQLite 저장이나 모델·LLM 실행 세부 사항은 외부 모듈에 맡긴다. |
| 질문 서비스 | 분류 결과에 따른 처리 순서와 정책 | FastAPI의 Request·Response·HTTPException 없이 테스트할 수 있게 한다. |
| 외부 연동 | SQLite 접근·명시적 평가 파일 읽기, 분류기와 LLM 호출 | 저장 형식이나 외부 도구의 세부 사항을 내부에 둔다. |
| 의존성 연결 | 사용할 구현을 생성·선택하여 전달 | 서비스 내부에서 실제 모델·클라이언트를 고정 생성하지 않도록 한다. |

질문 서비스를 도입할 때 실행 흐름은 `라우터 → 질문 서비스 → 필요한 외부 연동`으로 구성한다. 현재 질문 라우터는 분류기와 LangChain 연결 함수를 직접 호출하고, 문서 라우터는 SQLite 저장소를 사용한다. HTTP 오류 변환은 라우터 또는 공통 핸들러가 담당한다. 서비스는 처리 결과나 HTTP에 종속되지 않는 오류를 전달한다.

작은 기능은 함수로 시작한다. 저장소 인터페이스, Protocol, 앱 팩토리는 실제 교체·테스트 요구가 생길 때 도입한다. 폴더 이름만 나누고 다른 모듈의 내부 구현을 직접 조작하는 구조는 책임 분리로 보지 않는다.

## 현재 구성과 목표 구조

별도 `generation/`에는 프레임워크 독립 타입·프롬프트·호출 조정·파싱이 구현되어 있다. 현재 서버에서는 사용하지 않는다. 실제 모델 어댑터와 서버 연결은 후속 단계이며 [생성 모듈 안내](../generation/README.md)의 계약을 따른다. 기존 API와 실행기는 대체 경로 검증 전까지 유지한다.

다음은 분류·문서 답변 연결 시 따를 목표 구조다. `예정` 표시가 있는 파일·기능은 아직 구현하지 않았으며, 구조를 문서화했다는 이유로 빈 파일이나 구현을 미리 추가하지 않는다. 기존 실행 명령과 공개 API 계약은 유지한다.

```text
contracts/
├── __init__.py
└── classification.py        # 서버·학습·평가 공통 라벨 타입·순서
app/
├── __init__.py
├── fastapi_main.py           # 앱 생성·라우터 등록·공통 HTTP 오류 처리
├── schemas.py                # 공개 HTTP 요청·응답 모델
├── dependencies.py           # 조립 초안: HTTP 미연결, 답변기 미구현
├── company_knowledge.py      # 공통 DB 경로·명시적 JSONL 경로
├── debug.py                  # 문서 reader 단독 확인
├── answer_text.py            # 생성 결과의 본문 검증·추출
├── langchain_adapter.py      # 요청 snapshot 주입·실행기 결과 반환
├── koelectra_classifier.py   # 기존 분류 확인용 로컬 추론, 최종 선정과 별개
├── document_store.py         # doc append와 개발용 title/document reader
├── routers/
│   ├── __init__.py
│   ├── assistant.py          # /assistant 실행기 연결
│   ├── classification.py     # /classify/koelectra-base 분류 확인
│   ├── questions.py          # /ask 요청 전달·HTTP 응답 변환
│   └── documents.py          # /regist-docs 입력·저장 호출·응답
├── services/
│   ├── __init__.py
│   └── question_service.py   # handle_question: 미연결 / answer_question: 별도 API 연결
└── infrastructure/           # 예정: 실제 모델 연결 단계에서 추가
    ├── __init__.py
    ├── classifier.py         # 저장 모델 또는 선택한 외부 API로 분류
    └── answerer.py           # 단일 생성 제공자 호출·출력 검증
```

`contracts/classification.py`는 `ClassificationLabel`과 불변 `LABELS` 튜플의 기준 위치다. 서버 스키마·서비스, 학습 분할, 데이터 검증과 답변 실행·평가가 이를 공유한다. 프레임워크와 모델 라이브러리에 의존하지 않으며, 학습 코드의 기존 리스트 형식은 공통 튜플에서 변환한다. 과거 문서 주제 라벨은 별도 계약으로 유지한다. 모델 출력 번호는 저장된 `id2label` 또는 `classes_`로 해석한다.

`GET /`와 공통 검증 오류 핸들러는 진입점에 유지한다. `classification/`은 직접 구현 학습 공간이며 기존 실험 구현은 `archive/classification_v1/`에 보존한다. 서버가 `train_*`를 import하지 않는다. `infrastructure/classifier.py`는 전달된 아티팩트로 추론하거나 선택한 외부 API를 호출한다. 모델이 없을 때 자동 학습·대체 모델 다운로드를 실행하지 않는다.

새 학습 공간의 TF-IDF·Transformer는 [학습 코드 안내](../classification/README.md)를 따른다. `python -m classification.evaluate`는 새 저장 형식을 읽고 기본 validation·명시적 test를 평가한다. 새 모델은 지정한 실험 폴더에 저장하며 서버에 자동 배치하지 않는다. [7종 비교](../classification/reports/2026-10-15-seven-model-comparison/README.md)는 서비스 모델 선정·교체와 별개다.

보존된 분류 실험은 [분류 코드 안내](../archive/classification_v1/README.md)의 `cli → workflows → 전달받은 모델 기능`으로 구성한다. CLI가 구체 모델·데이터·저장과 명시적인 train·eval 실행을 조립하고, workflow는 모델 선택 결과·평가 결과를 반환한다. 실험 실행 진입점은 `archive/classification_v1/experiments/`, 지표·보고서 코드는 `archive/classification_v1/evaluation/`, 과거 문서 분할 코드는 `archive/classification_v1/legacy/`에 둔다. 모델 구현은 `archive/classification_v1/models/`에 있으며 새 가중치의 `artifacts/models/`, 평가 결과의 `artifacts/results/`와 구분한다. `sanaebi train`은 기존 모델 폴더가 있으면 검사 없이 안내하고 종료하며 재학습은 `--force`로 명시한다. CLI는 로컬 MLflow에 설정·지표·산출물을 기록하며 workflow와 모델 계산은 추적 도구에 의존하지 않는다. 신규 HTML·비교 페이지는 생성하지 않는다. `sanaebi eval`은 validation CPU 평가, `--split test`는 test만 담당한다. 학습 workflow는 train/validation만 받고 신규 결과는 `artifacts/results/<모델명>/<분할>/`에 나누어 보관한다. 채택한 small 모델은 실험 저장소에만 있으며 서버의 base 선택·`classification/model/koelectra_base` 경로는 유지한다. 서버의 기존 `koelectra_classifier.py`는 아직 이 구현에 연결하지 않았다. 서버는 실험 CLI나 학습 진입점을 import하지 않으며, 이 정리를 서버 연결이나 모델 선정 완료로 취급하지 않는다.

`answer_text.py`의 `generate_answer`는 사용하지 않는 echo 도우미로 남아 있다. 현재 `/ask`는 LangChain 연결 함수를 호출한다. 실제 연결 시 답변 생성은 `infrastructure/answerer.py`가 담당하고, 본문 추출 도우미는 필요한 경우 재사용한다. 목표 `/ask` 응답에는 별도 실험 실행기의 provider별 결과 포장을 전달하지 않는다. 현재 `/assistant`는 이 실행 기록을 반환하는 별도 계약이며 `AnswerResponse`를 반환하는 `/ask`와 구분한다.

### 내부 계약과 연결 책임

| 경계 | 입력 → 출력 | 담당 위치 |
|---|---|---|
| 분류 | 질문 문자열 → 허용된 라벨 | `infrastructure/classifier.py` |
| 문서 경로 | 환경변수 또는 기본 정책 → Path | `company_knowledge.py` |
| 문서 읽기 | 지정 경로 → 문서 본문 목록 | `document_store.py`; 경로는 연결 계층에서 전달 |
| 답변 생성 | 질문·문서 목록 → 검증된 답변 문자열 | `infrastructure/answerer.py` |
| 질문 처리 | 질문·의존 함수 → `QuestionResult(text)` | `services/question_service.py` |
| HTTP 변환 | 요청 → 서비스 호출 → `AnswerResponse` | `routers/questions.py` |

`QuestionResult`는 내부 결과이므로 서비스 옆에 둔다. `schemas.py`의 `AnswerResponse(ok, text, reason)`과 별개이며, 내부 결과에서 `reason`을 제거해도 공개 응답 필드는 유지한다. 정상 반환은 라우터가 `ok=True`와 `text`로 변환하고 `reason`은 공개 스키마의 기본값을 사용한다. 지원 범위·자료 부족 안내는 정상 처리이며 실행 오류는 예외로 전달한다. 예외의 HTTP 상태 코드와 안전한 응답 변환은 라우터 또는 공통 핸들러에서 명시적으로 연결한다.

`dependencies.py`는 분류기·문서 reader·답변기를 선택하여 질문 서비스에 전달하고, 라우터가 `Depends`로 받을 질문 처리 함수를 제공한다. 서비스 내부에는 FastAPI 의존성 선언을 넣지 않는다. 함수와 `functools.partial`로 시작할 수 있으며, 테스트에서는 제공 함수를 override한다. Depends의 사용 자체가 프로세스 전체의 모델 단일 로딩을 보장하지 않으므로 실제 모델 연결 때 로딩 시점도 정한다.

현재 조립 초안의 문서 reader도 SQLite 게시 snapshot을 사용한다. 공통 DB 경로는 `get_document_database_path()`로 계산한다. 미구현 답변 함수의 `NotImplementedError`는 유지하며 이 초안을 HTTP 경로로 활성화하지 않는다.

### 단계별 연결과 완료 기준

| 단계 | 구현 범위 | 확인할 결과 |
|---|---|---|
| 1. 질문 서비스 | 가짜 의존성을 사용한 세 라벨 분기 | 비검색 경로의 문서·LLM 미호출, 빈 문서 안내, 잘못된 라벨·실행 예외 처리. 현재 단위 검증 완료 |
| 2. HTTP 연결 | `dependencies.py`와 질문 라우터 | override를 사용한 API 테스트, 기존 요청·응답 필드 유지, 필요한 예외의 HTTP 변환 |
| 3. 실제 분류 | 선택 모델의 추론 어댑터 | 아티팩트·라벨·전처리 확인, 고정 질문의 예측 재현 |
| 4. 문서·생성 연결 | SQLite 게시 snapshot과 답변 어댑터 | 기존 데이터 보존, 문서·생성 형식 정합성, 자료 부족·입력 한도·실패 처리 |
| 5. 종단 검증 | 실제 예측 라벨부터 최종 답변까지 | 분류 오류와 생성 오류 분리, 정답 라벨 고정 평가와 구분 |

각 단계의 미구현 부분은 완료로 표시하지 않는다. `document_store.read_documents(path)`는 명시적 JSONL 호환 reader로 남지만 기본 서비스 문서 공급에는 사용하지 않는다. 런타임은 SQLite-only provider이며 DB 오류를 더미나 파일 fallback으로 숨기지 않는다.

`/regist-docs`는 기존 입력·성공 응답을 유지하면서 동일 SQLite에 초안을 저장한다. 50,000자·512KiB 제한과 중복 409가 적용된다. 과거 append 도우미와 원본 파일은 레거시 자료로 보존하고 런타임 쓰기에는 사용하지 않는다.

## 질문 서비스와 대체 가능한 의존성

`handle_question`은 비검색 라벨에서 고정 안내로 종료하고 검색 경로에서만 reader·answer를 호출한다. `answer_question`은 모든 분류 결과를 `generate(response, category)`로 전달하며 분류 모델 파일 부재만 `ClassificationModelUnavailable`로 변환한다. 후자는 원격의 별도 실행기 연결 동작을 보존한 것이며 전자의 분기 정책·문서 reader·의존성 조립을 사용하지 않는다. 둘을 통합할 때는 라벨별 LLM 호출 정책과 응답 계약을 먼저 결정한다.

분류기는 현재 질문을 받아 처리 라벨을 반환하고, 질문 서비스가 [서비스 설계](service-architecture.md)에 따라 다음 동작을 선택한다. 라벨의 정의와 경계 사례는 이 문서에 복제하지 않는다. 분류 결과만으로 문서 근거가 충분하다고 판단하지 않는다.

질문 서비스가 사용할 분류기·문서 접근·LLM을 외부에서 전달한다. FastAPI Depends는 HTTP 계층에서 연결하는 수단으로 사용하고, 서비스는 전달받은 함수나 객체를 사용한다. 테스트에서 실제 모델·네트워크 대신 고정된 결과를 주는 구현으로 교체할 수 있어야 한다.

현재 단위 테스트는 CLARIFY·UNSUPPORTED의 문서·LLM 미호출, SEARCH_KNOWLEDGE의 인자 전달, 빈 문서 안내, 잘못된 라벨과 의존 함수 오류 전달을 확인한다. 실제 문서의 근거 부족·충돌과 생성 출력 검증은 답변 어댑터 연결 단계에 추가하며, 서비스 단위 테스트 통과를 답변 품질 검증으로 취급하지 않는다.

모델 로딩·종료, timeout, 추론 실행 방식은 후속 설계에서 정한다. 과거 서버의 import 시 모델 로딩이나 async 함수 안의 동기 추론을 그대로 복사하지 않는다. 현재 동기 라우트를 구조 정리만을 이유로 일괄 async로 바꾸지 않는다.

## 호환성과 회귀 검증

구조 변경과 API 동작 변경을 별도 변경으로 관리한다. 구조만 옮길 때 URL, 상태 코드, 요청·응답 필드, 입력 검증, 공통 오류 처리와 저장 동작을 보존한다. 현재 계약의 근거는 코드와 [API 회귀 테스트](../tests/test_api.py)다. 저장 실패 등 기존 오류 형태를 개선하려면 변경할 계약을 별도로 명시한다.

테스트는 실제 문서 파일과 외부 API를 사용하지 않는다. 임시 저장소와 대체 의존성을 사용하고 종료 시 원상 복원한다. 문서 저장소 교체 시 입력·응답·중복·기존 데이터 보존 검증을 유지한다. 의도적인 API 추가 시에는 OpenAPI 경로 목록 검증도 함께 갱신한다.

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
git diff --check
```

리팩터링 완료 기준은 기존 API 테스트 통과, 저장 경로와 기존 데이터 보존, 문서 링크·실행 경로의 일치다. 질문 서비스를 추가한 경우에는 HTTP·실제 모델·네트워크 없이 분기별 테스트가 가능해야 한다.

## 과거 코드와 규약 관리

[과거 FastAPI 프로토타입](../archive/fastapi-prototype/README.md)은 보관 자료이며 활성 앱에서 import하거나 현재 계약의 기준으로 사용하지 않는다. 보관본의 실행이나 경로 복구는 이 규약의 적용 범위가 아니다.

서버 구조의 기준 문서는 이 파일이다. 파일·폴더의 추가·이동·삭제, 모듈 책임, 내부 입출력 또는 의존 방향을 바꾸는 작업에서는 목표 트리·계약 표·현재 연결 상태를 같은 변경에서 갱신한다. 새로운 설계만 채택했다면 `예정`으로 표시하고, 구현과 해당 검증이 끝난 항목만 현재 상태로 옮긴다. 검토 중인 대안은 채택된 목표 구조와 구분한다.

공개 API나 서비스 정책까지 바뀌면 서비스 설계와 관련 테스트도 함께 갱신한다. Notion에는 필요한 요약과 Git 기준 링크를 반영하고, 원격 미게시 변경은 로컬 상태임을 명시한다. 구조 전체를 여러 문서에 복제하지 않는다.

규약을 바꿀 때는 구현·채택된 기준·향후 제안을 구분하고 [문서 관리 가이드](documentation-guide.md)를 따른다. 작업별 검사 로그와 적용 결과는 작업 기록에 두고 이 문서에 누적하지 않는다.

참고: [FastAPI 여러 파일 구성](https://fastapi.tiangolo.com/tutorial/bigger-applications/), [의존성 주입](https://fastapi.tiangolo.com/tutorial/dependencies/), [테스트 의존성 대체](https://fastapi.tiangolo.com/advanced/testing-dependencies/). 위 폴더 구성은 이 프로젝트의 적용 기준이며 FastAPI가 강제하는 유일한 구조가 아니다.

## 회사 정책 데이터 연결

기본 경로 선택은 `app/company_knowledge.py`에서 관리한다. 서버 조립·디버그·독립 실행기가 같은 기본 경로를 사용하고, 공개 API 계약이나 등록 API의 doc 저장 형식은 바꾸지 않는다. 정책의 출처·검수·고정 ID와 과거 문서 재현 방법은 [회사 정책 안내](../data/README.md#답변용-회사-지식)를 따른다. 평가 실행기는 고정 ID를 사용하며 ID가 전혀 없는 보관본만 행 번호를 사용한다. 혼합·중복·빈 ID는 실패시킨다.

## 런타임 문서 관리

`/documents`와 `/regist-docs`는 같은 SQLite를 사용한다. 스키마·서비스·저장소가 입력, 개정·게시, 원자적 저장을 담당한다. `DocumentContextProvider`는 유효 게시본과 출처를 읽기 트랜잭션으로 확보하고 HTTP 어댑터는 이를 실행기에 주입한다. 실제 LLM 호출 전 트랜잭션을 닫는다. schema v2와 이관·백업·오류 계약은 [문서 관리](document-management.md)를 따른다.
