# 서버 구성과 변경 규약

이 문서는 Sanaebi 서버 코드를 수정하거나 확장할 때의 책임 분리와 검증 기준을 정한다. 서비스가 무엇을 처리하는지는 [서비스 설계](service-architecture.md), 라벨 의미는 [라벨 기준](label-taxonomy.md)을 따른다.

현재 서버는 [앱 진입점](../app/fastapi_main.py), [요청·응답 스키마](../app/schemas.py), [질문 라우터](../app/routers/questions.py), [문서 라우터](../app/routers/documents.py), [JSONL 저장 함수](../app/document_store.py)로 분리되어 있다. 질문 서비스와 의존성 연결 계층은 아직 구현하지 않았다. 모델 수명주기·추론 동시성과 공개 배포·권한·운영 구성은 후속 작업으로 남긴다. 이 규약 작성만으로 해당 기능을 구현하거나 운영 준비를 완료한 것으로 처리하지 않는다.

분류 확인용 `POST /classify/koelectra-base`는 [분류 라우터](../app/routers/classification.py)에서
요청을 전달하고, [KoELECTRA 연동 함수](../app/koelectra_classifier.py)에서 로컬 저장 모델로 예측한다.
첫 요청에서 모델을 불러와 캐시하며, 재학습 없이 카테고리만 반환한다.
분류 결과는 아직 `/ask`의 답변 흐름에 연결하지 않았다.

## 책임과 의존 방향

| 구성 | 책임 | 경계 |
|---|---|---|
| 앱 진입점 | 앱 생성, 라우터와 공통 오류 처리 연결 | 질문 처리 정책이나 파일 저장 구현을 모으지 않는다. |
| 스키마 | HTTP 요청·응답의 필드와 검증 | 저장 방식이나 모델 초기화를 담당하지 않는다. |
| 라우터 | 요청 전달, HTTP 응답과 상태 코드 | JSONL 직렬화나 모델·LLM 실행 세부 사항은 외부 모듈에 맡긴다. |
| 질문 서비스 | 분류 결과에 따른 처리 순서와 정책 | FastAPI의 Request·Response·HTTPException 없이 테스트할 수 있게 한다. |
| 외부 연동 | JSONL 접근, 분류기와 LLM 호출 | 저장 형식이나 외부 도구의 세부 사항을 내부에 둔다. |
| 의존성 연결 | 사용할 구현을 생성·선택하여 전달 | 서비스 내부에서 실제 모델·클라이언트를 고정 생성하지 않도록 한다. |

질문 서비스를 도입할 때 실행 흐름은 `라우터 → 질문 서비스 → 필요한 외부 연동`으로 구성한다. 현재 질문 라우터는 echo 응답을 반환하고, 문서 라우터는 저장 함수를 직접 호출한다. HTTP 오류 변환은 라우터 또는 공통 핸들러가 담당한다. 서비스는 처리 결과나 HTTP에 종속되지 않는 오류를 전달한다.

작은 기능은 함수로 시작한다. 저장소 인터페이스, Protocol, 앱 팩토리는 실제 교체·테스트 요구가 생길 때 도입한다. 폴더 이름만 나누고 다른 모듈의 내부 구현을 직접 조작하는 구조는 책임 분리로 보지 않는다.

## 현재 모듈 구성과 후속 분리

기본 분리를 완료한 현재 구조는 다음과 같다. 기존 실행 명령과 API 계약은 유지한다.

```text
app/
├── __init__.py
├── fastapi_main.py
├── schemas.py
├── routers/
│   ├── __init__.py
│   ├── questions.py
│   └── documents.py
└── document_store.py
```

스키마를 먼저 옮기고, APIRouter로 라우터를 분리한 뒤, JSONL 접근을 문서 저장 모듈로 옮긴다. 각 단계에서 API 테스트를 실행한다. `GET /`와 공통 검증 오류 핸들러는 작은 규모에서는 진입점에 유지해도 된다.

실제 분류 흐름을 연결하는 시점에 `services/question_service.py`와 `dependencies.py`를 추가한다. 패키지 디렉터리에는 같은 패키지 규칙을 적용한다. 외부 연동이 늘어날 때 `infrastructure/` 등으로 묶을 수 있지만, 아직 필요하지 않은 빈 계층이나 모델·LLM 구현을 미리 만들지 않는다.

`document_store.append_document(path, text)`는 전달받은 본문을 JSONL 한 줄로 추가한다. 앞뒤 공백 제거와 성공 응답은 문서 라우터가 담당하고, DOCUMENT_FILE도 문서 라우터에서 기존 `app/documents.jsonl`로 지정한다. 파일을 옮길 때 `__file__`의 위치가 바뀌어 실제 데이터 경로까지 바뀌지 않도록 확인한다. 저장 위치 이전은 별도 요구와 데이터 보존 절차가 있을 때만 수행한다.

## 질문 서비스와 대체 가능한 의존성

분류기는 현재 질문을 받아 처리 라벨을 반환하고, 질문 서비스가 [서비스 설계](service-architecture.md)에 따라 다음 동작을 선택한다. 라벨의 정의와 경계 사례는 이 문서에 복제하지 않는다. 분류 결과만으로 문서 근거가 충분하다고 판단하지 않는다.

질문 서비스가 사용할 분류기·문서 접근·LLM을 외부에서 전달한다. FastAPI Depends는 HTTP 계층에서 연결하는 수단으로 사용하고, 서비스는 전달받은 함수나 객체를 사용한다. 테스트에서 실제 모델·네트워크 대신 고정된 결과를 주는 구현으로 교체할 수 있어야 한다.

예를 들어 CLARIFY를 반환하는 대체 분류기로 추가 정보 요청을 확인하고, 이 경로에서 문서 조회·LLM 호출이 발생하지 않는지도 검사한다. SEARCH_KNOWLEDGE 경로는 문서 부족·충돌 상황을 별도 시나리오로 검증한다. 이 검사는 해당 기능을 실제로 구현할 때 추가한다.

모델 로딩·종료, timeout, 추론 실행 방식은 후속 설계에서 정한다. 과거 서버의 import 시 모델 로딩이나 async 함수 안의 동기 추론을 그대로 복사하지 않는다. 현재 동기 라우트를 구조 정리만을 이유로 일괄 async로 바꾸지 않는다.

## 호환성과 회귀 검증

구조 변경과 API 동작 변경을 별도 변경으로 관리한다. 구조만 옮길 때 URL, 상태 코드, 요청·응답 필드, 입력 검증, 공통 오류 처리와 저장 동작을 보존한다. 현재 계약의 근거는 코드와 [API 회귀 테스트](../tests/test_api.py)다. 저장 실패 등 기존 오류 형태를 개선하려면 변경할 계약을 별도로 명시한다.

테스트는 실제 문서 파일과 외부 API를 사용하지 않는다. 임시 저장소와 대체 의존성을 사용하고 종료 시 원상 복원한다. 모듈 분리에 따라 현재 문서 라우터의 DOCUMENT_FILE 교체 지점을 바꾸더라도, 입력·응답·append·기존 데이터 보존 검증을 약화하지 않는다. 의도적인 API 추가 시에는 OpenAPI 경로 목록 검증도 함께 갱신한다.

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
git diff --check
```

리팩터링 완료 기준은 기존 API 테스트 통과, 저장 경로와 기존 데이터 보존, 문서 링크·실행 경로의 일치다. 질문 서비스를 추가한 경우에는 HTTP·실제 모델·네트워크 없이 분기별 테스트가 가능해야 한다.

## 과거 코드와 규약 관리

[과거 FastAPI 프로토타입](../archive/fastapi-prototype/README.md)은 보관 자료이며 활성 앱에서 import하거나 현재 계약의 기준으로 사용하지 않는다. 보관본의 실행이나 경로 복구는 이 규약의 적용 범위가 아니다.

규약을 바꿀 때는 구현·채택된 기준·향후 제안을 구분하고 [문서 관리 가이드](documentation-guide.md)를 따른다. 작업별 검사 로그와 적용 결과는 작업 기록에 두고 이 문서에 누적하지 않는다.

참고: [FastAPI 여러 파일 구성](https://fastapi.tiangolo.com/tutorial/bigger-applications/), [의존성 주입](https://fastapi.tiangolo.com/tutorial/dependencies/), [테스트 의존성 대체](https://fastapi.tiangolo.com/advanced/testing-dependencies/). 위 폴더 구성은 이 프로젝트의 적용 기준이며 FastAPI가 강제하는 유일한 구조가 아니다.
