# 서버 구성과 변경 규약

서버 책임 분리와 회귀 검증의 기준이다. 서비스 정책은 [서비스 설계](service-architecture.md), 라벨 의미는 [라벨 기준](label-taxonomy.md), 문서 저장 계약은 [문서 관리](document-management.md)를 따른다.

## 현재 흐름과 책임

`라우터 → 질문 서비스 → 외부 연동`을 사용한다. `/ask`는 분류 후 CLARIFY·UNSUPPORTED에 고정 안내를 반환하며 문서·LLM을 호출하지 않는다. SEARCH_KNOWLEDGE만 SQLite 게시 snapshot을 한 번 읽고, 비어 있지 않을 때 선택한 LangChain 제공자로 답변을 생성한다. 빈 snapshot은 정상적인 자료 없음 안내다. 조회 실패를 빈 문서로 숨기지 않는다.

| 구성 | 책임 | 경계 |
|---|---|---|
| 앱 진입점 | 라우터·오류 처리 등록, 앱별 모델·문서 provider 생성 | 모델 가중치는 첫 예측에서 로딩 |
| 스키마 | HTTP 요청·응답 검증 | 모델 초기화·정책 없음 |
| 라우터 | 입력 전달과 HTTP 응답 변환 | 모델·DB·실행기 직접 호출 없음 |
| 질문 서비스 | 라벨별 처리 순서·자료 없음 안내 | FastAPI 없이 대체 의존성으로 검증 |
| 외부 연동 | 로컬 모델 추론·LangChain 호출·출력 검증 | 학습 코드 import 없음 |
| 의존성 연결 | 앱 객체를 질문 처리 함수로 조립 | 서비스 내부에서 구현을 생성하지 않음 |

`/classify/koelectra-base`는 호환 URL을 유지하며 `/ask`와 같은 앱별 추론 객체를 사용한다. `/assistant`는 이미 분류한 입력을 받는 기존 실행기 계약이며 이번 질문 서비스 정책 변경 대상이 아니다. `/ask/langchain`은 없다. 별도 `generation/`은 현재 서버에서 사용하지 않는다.

## 현재 구조

```text
contracts/classification.py       # 공통 라벨 타입·순서
app/
├── fastapi_main.py               # lifespan·라우터·HTTP 오류 처리
├── schemas.py                    # 공개 HTTP 계약
├── model_settings.py             # 모델 경로·생성 provider 설정
├── dependencies.py               # 앱별 분류기·snapshot reader·답변기 조립
├── koelectra_classifier.py        # 과거 단독 호출용 얇은 호환 함수
├── langchain_adapter.py          # /assistant용 기존 snapshot 주입
├── answer_text.py                # 답변 본문 검증·추출, 과거 echo 도우미
├── company_knowledge.py          # DB 경로·명시적 평가 JSONL 경로
├── document_repository.py        # SQLite 영속화
├── document_store.py             # 명시적 JSONL 호환·과거 append
├── routers/
│   ├── questions.py              # /ask → 질문 서비스
│   ├── classification.py         # 분류만 확인
│   ├── assistant.py              # 기존 실행기 API
│   ├── documents.py              # /regist-docs → SQLite 초안
│   └── managed_documents.py      # 문서 관리 API
├── services/
│   ├── question_service.py       # 라벨 정책·QuestionResult
│   ├── document_context.py       # 유효 게시 snapshot과 출처
│   └── document_service.py       # 문서 개정·게시 정책
└── infrastructure/
    ├── classifier.py             # Transformer 저장본 검증·CPU 추론
    └── answerer.py               # 단일 LangChain 제공자·본문 검증
```

작은 기능은 함수로 시작한다. 실제 필요가 없는 Protocol·앱 팩토리·빈 폴더는 추가하지 않는다. 구조를 옮길 때 공개 API 동작 변경은 별도로 명시한다. 현재 동기 라우트를 일괄 async로 바꾸지 않는다.

## 내부 계약

| 경계 | 입력 → 출력 |
|---|---|
| 분류 | 질문 문자열 → ClassificationLabel |
| 문서 조회 | 인자 없음 → DocumentContextSnapshot |
| 답변 생성 | 질문·snapshot → 검증된 답변 문자열 |
| 질문 처리 | 질문·의존 함수 → QuestionResult(text) |
| HTTP | 요청 → 서비스 결과 → AnswerResponse(ok, text, reason) |

문서는 문자열 목록으로 축소하지 않는다. 문서 ID·출처·revision을 포함한 같은 snapshot을 답변기로 전달한다. DB 트랜잭션은 LLM 호출 전에 끝나며 답변 어댑터는 문서를 재조회하지 않는다. SQLite-only 런타임에 JSONL·더미 fallback은 없다.

`dependencies.py`는 요청의 앱 상태에서 구현을 선택하고 `Depends`로 처리 함수를 전달한다. 테스트는 의존성을 override한다. 서비스에는 FastAPI Request·Response·HTTPException을 넣지 않는다. 정상 결과에는 내부 reason을 추가하지 않고 공개 reason의 기본값을 유지한다.

## 모델 설정과 수명주기

`SANAEBI_CLASSIFIER_PATH`는 저장본 폴더이며 상대 경로는 저장소 루트 기준이다. 기본은 `artifacts/experiments/learning-comparison-2026-10-15/koelectra_base/model/`이다. [선정 보고서](../classification/reports/2026-10-15-seven-model-comparison/README.md)의 model_id `9f51682d82d4455d8296077c339afd58`를 채택했다. 다른 같은 형식의 Transformer 저장본도 경로로 주입할 수 있지만 교체 전 라벨·예측 회귀 검증을 수행한다.

새 학습 형식의 metadata.json(schema_version=1)에서 model_id·labels·config.max_length를 읽는다. config의 id2label·label2id와 라벨 순서·집합을 검증하고 저장 모델의 번호를 그대로 해석한다. metadata 버전 1은 아카이브 manifest 버전 1과 다른 형식이다. 아카이브 자동 변환·자동 재학습은 없다.

모델은 CPU에서 로컬 파일만 읽으며 첫 예측 시 잠금 안에서 로딩한다. 초기화·추론을 직렬화하고 성공한 객체를 앱 프로세스 안에서 재사용한다. 여러 worker는 각각 별도 가중치를 로딩하므로 메모리를 따로 사용한다. 파일을 교체해도 실행 중 객체는 바뀌지 않으며 재시작해야 한다. GPU·추론 큐·처리량 최적화는 후속 범위다.

`SANAEBI_ANSWER_PROVIDER`는 ollama(기본) 또는 openai다. 실행기는 기존 모델·프롬프트를 사용하며 다른 생성 모듈로 자동 전환하지 않는다. 비밀키·가중치는 Git에 게시하지 않는다. API의 호출 동작은 앱 시작 시 읽은 설정을 따른다.

## 오류와 호환

- 입력 오류: 422, 기존 AnswerResponse 형식.
- 분류 저장본 부재·잘못된 메타데이터·라벨 매핑 또는 추론 실패: 503, `분류 모델을 사용할 수 없습니다.`. 내부 경로·예외 원문은 반환하지 않는다.
- 문서 공급 오류: 기존 503. 빈 snapshot의 정상 안내와 구별한다.
- 생성 실패·사용 불가 답변: 기존 502.
- 예상하지 못한 일반 오류: 기존 공통 500 처리. 모델 부재로 오인하지 않는다.

`/documents`와 `/regist-docs`는 같은 SQLite를 사용한다. 기존 doc 입력·초안 생성·중복 409·50,000자/512KiB 제한을 유지한다. 게시와 사람 검수 승인은 별개다. 원본 파일·레거시 append·과거 FastAPI 프로토타입은 보존하며 활성 런타임 쓰기 경로로 사용하지 않는다.

서버는 `classification/`의 학습·평가 모듈이나 아카이브 CLI를 import하지 않는다. 학습·모델 선정·서버 연결·실서비스 품질을 구분한다. 새 모델은 실험 폴더에 저장되며 자동 배포되지 않는다. 기존 실험 CLI·MLflow·과거 HTML은 [아카이브 안내](../archive/classification_v1/README.md)를 따른다.

## 회귀 검증과 문서 유지

서비스는 가짜 분류·문서·답변 의존성으로 세 라벨 분기, 비검색 미호출, snapshot 1회 조회·동일 객체 전달, 빈 문서, 잘못된 라벨·오류를 검증한다. API는 임시 DB·대체 모델로 공개 URL·필드·오류를 확인한다. 실제 모델 연결은 저장된 validation 예측과 서버 추론의 일치 및 모의 생성기를 이용한 HTTP 검증으로 확인한다. 이는 새로운 성능 평가나 실제 LLM 종단 품질 검증이 아니다.

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
git diff --check
```

구조·내부 계약·연결 상태가 바뀌면 이 문서를 함께 수정한다. 구현과 검증이 끝난 항목만 현재 상태로 기록하고 향후 설계와 구분한다. 작업별 실행 로그는 작업 일지에 둔다. 서비스 정책은 서비스 설계·API 테스트에도 반영하고 [문서 관리 가이드](documentation-guide.md)에 따라 Notion 요약을 갱신·재조회한다. 원격 미게시 파일을 게시 링크처럼 안내하지 않는다.
