# 서버 구성과 변경 규약

로컬 통합 준비는 `npm run setup:local -- --init-documents`, 실행은 `npm run dev`를 사용한다. 기존 DB·전체 삭제 상태는 보존하며 검색 색인과 기본 복원 묶음을 함께 준비한다. [준비·진단 상세](rag-runtime.md#준비와-실행).

서버 책임 분리와 회귀 검증의 기준이다. 서비스 정책은 [서비스 설계](service-architecture.md), 라벨 의미는 [라벨 기준](label-taxonomy.md), 문서 저장 계약은 [문서 관리](document-management.md)를 따른다.

처음 읽는 경우 [서버 요청 흐름](../app/README.md) → [분류기 추론](../app/classification/README.md)을 따른다. 이 문서는 구현을 변경할 때 지켜야 할 책임·설정·검증 기준을 관리한다.

## 현재 흐름과 책임

`라우터 → 질문 서비스 → 외부 연동`을 사용한다. 원복용 `gate` 모드에서 `/ask`는 분류 후 CLARIFY·UNSUPPORTED에 고정 안내를 반환하며 문서·LLM을 호출하지 않는다. SEARCH_KNOWLEDGE만 SQLite 게시 snapshot을 한 번 읽고, 비어 있지 않을 때 최종 Luna 생성 모듈로 답변을 생성한다. 빈 snapshot은 정상적인 자료 없음 안내다. 조회 실패를 빈 문서로 숨기지 않는다.

| 구성 | 책임 | 경계 |
|---|---|---|
| 앱 진입점 | 라우터·오류 처리 등록, 앱별 모델·문서 provider 생성 | 모델 가중치는 첫 예측에서 로딩; 운영 readiness가 1회 예열 |
| 스키마 | HTTP 요청·응답 검증 | 모델 초기화·정책 없음 |
| 라우터 | 입력 전달과 HTTP 응답 변환 | 모델·DB·실행기 직접 호출 없음 |
| 질문 서비스 | 라벨별 처리 순서·자료 없음 안내 | FastAPI 없이 대체 의존성으로 검증 |
| 외부 연동 | 로컬 모델 추론·LangChain 호출·출력 검증 | 학습 코드 import 없음 |
| 의존성 연결 | 앱 객체를 질문 처리 함수로 조립 | 서비스 내부에서 구현을 생성하지 않음 |

`/classify/koelectra-base`는 호환 URL을 유지하며 `/ask`와 같은 앱별 추론 객체를 사용한다. `/assistant`는 기존 입력을 유지하고 재분류 없이 공통 `handle_classified_question`을 호출한다. 두 API는 동일한 `AnswerResponse`를 반환한다. 앞 단계 `ok=false`는 생성 없이 안전한 실패 안내로 끝나고, `ok=true`의 공백 질문은 422다. `/ask/langchain`은 없다.

## 현재 구조

```text
app/
├── fastapi_main.py           # 기존 실행 진입점·lifespan·등록
├── settings.py              # 모델·문서 경로·답변 provider
├── dependencies.py          # 의존성 조립
├── errors.py                # 공통 HTTP 예외 핸들러
├── schemas.py               # 여러 API가 공유하는 요청·응답
├── questions/
│   ├── router.py            # /ask
│   └── service.py           # 라벨 정책·QuestionResult
├── classification/
│   ├── router.py            # 분류 전용 API
│   └── predictor.py         # 저장 모델 검증·CPU 추론
├── documents/
│   ├── router.py            # 문서 관리 API
│   ├── registration.py      # 기존 /regist-docs 계약
│   ├── schemas.py           # 문서 전용 HTTP 계약
│   ├── service.py           # 개정·게시 정책
│   ├── repository.py        # SQLite 영속화
│   ├── metadata.py          # 메타데이터 저장
│   ├── context.py           # 게시 snapshot·출처
│   ├── http.py              # 문서 HTTP 오류·입력 제한
│   ├── transfer.py          # 이관·내보내기
│   └── reset.py             # 명시적 시연 DB 복원·백업
├── answering/
│   ├── router.py            # 이미 분류한 입력의 /assistant
│   ├── adapter.py           # 앱별 GenerationAnswerer·수명주기
│   └── output.py            # 답변 본문 검증
└── diagnostics/
    └── trace.py             # 선택적 요청·LangChain 추적
```

코드를 읽을 때는 `fastapi_main.py` → `dependencies.py` → `questions/router.py` → `questions/service.py` → `classification/predictor.py` 순서로 확인한다. 문서 기능은 documents, 이후 답변 연결은 answering에서 읽는다. 루트 classification/은 학습 공간이며 app/classification/은 서버 추론 기능이다.

서버는 `retrieval/experiments/`와 `archive/`를 import하지 않는다. 미채택 임베딩 문맥 확장은 실험 계층에서 재현하고, 과거 실행기 전용 trace 단계 해석은 보관 계층에서 관리한다. 현재 trace의 요청·분류·검색·생성 기록과 일반 모델 콜백은 유지한다. `/ask`와 `/assistant`는 공통 의존성 조립으로 같은 문서 provider·검색기·답변기 선택을 사용한다.

기존 routers/services/infrastructure 폴더와 재수출 래퍼는 제거했다. 내부 Python import 경로는 변경했으며 외부에 배포된 Python 라이브러리 호환을 보장하지 않는다. HTTP API와 `app.fastapi_main:app` 실행 진입점은 유지한다. 과거 단독 KoELECTRA 래퍼·echo 답변 함수는 제거하고, JSONL 처리는 archive/server_legacy에 보존한다.

문서 snapshot 진단은 `uv run --locked python -m scripts.inspect_document_context`로 실행한다. 읽기 전용이며 DB가 없으면 오류를 숨기지 않는다. trace는 기존 TRACE_DIR·TRACE_FULL_PROMPT·TRACE_MAX_CHARS 설정과 기록 형식을 유지한다. 모델 종료와 별개로 최종 생성 판정·설정 식별자·snapshot/프롬프트 해시·시간·사용량을 기록한다. 새 생성 요약에는 원문·키·예외 메시지를 넣지 않는다. 기존 opt-in trace의 요청·응답·콜백 원문은 민감 자료로 취급한다.


작은 기능은 함수로 시작한다. 실제 필요가 없는 Protocol·앱 팩토리·빈 폴더는 추가하지 않는다. 구조를 옮길 때 공개 API 동작 변경은 별도로 명시한다. 현재 동기 라우트를 일괄 async로 바꾸지 않는다.

## 내부 계약

| 경계 | 입력 → 출력 |
|---|---|
| 분류 | 질문 문자열 → ClassificationLabel |
| 문서 조회 | 인자 없음 → DocumentContextSnapshot |
| 답변 생성 | AnswerInput(질문·렌더링 문서·snapshot fingerprint·선택적 분류 참고) → 검증된 답변 문자열 |
| 질문 처리 | 질문·의존 함수 → QuestionResult(text) |
| HTTP | 요청 → 서비스 결과 → AnswerResponse(ok, text, reason) |

문서는 문자열 목록으로 축소하지 않는다. 문서 ID·출처·revision을 포함한 같은 snapshot을 답변기로 전달한다. DB 트랜잭션은 LLM 호출 전에 끝나며 답변 어댑터는 문서를 재조회하지 않는다. SQLite-only 런타임에 JSONL·더미 fallback은 없다.

`dependencies.py`는 요청의 앱 상태에서 구현을 선택하고 `Depends`로 처리 함수를 전달한다. 테스트는 의존성을 override한다. 서비스에는 FastAPI Request·Response·HTTPException을 넣지 않는다. 정상 결과에는 내부 reason을 추가하지 않고 공개 reason의 기본값을 유지한다.

## 모델 설정과 수명주기

`SANAEBI_CLASSIFIER_PATH`는 저장본 폴더이며 상대 경로는 저장소 루트 기준이다. 기본은 `artifacts/experiments/learning-comparison-2026-10-15/koelectra_base/model/`이다. [선정 보고서](../classification/reports/2026-10-15-seven-model-comparison/README.md)의 model_id `9f51682d82d4455d8296077c339afd58`를 채택했다. 다른 같은 형식의 Transformer 저장본도 경로로 주입할 수 있지만 교체 전 라벨·예측 회귀 검증을 수행한다.

새 학습 형식의 metadata.json(schema_version=1)에서 model_id·labels·config.max_length를 읽는다. config의 id2label·label2id와 라벨 순서·집합을 검증하고 저장 모델의 번호를 그대로 해석한다. metadata 버전 1은 아카이브 manifest 버전 1과 다른 형식이다. 아카이브 자동 변환·자동 재학습은 없다.

모델은 CPU에서 로컬 파일만 읽으며 첫 예측 시 잠금 안에서 로딩한다. 초기화·추론을 직렬화하고 성공한 객체를 앱 프로세스 안에서 재사용한다. 여러 worker는 각각 별도 가중치를 로딩하므로 메모리를 따로 사용한다. 파일을 교체해도 실행 중 객체는 바뀌지 않으며 재시작해야 한다. GPU·추론 큐·처리량 최적화는 후속 범위다.

`SANAEBI_ANSWER_PROVIDER`는 미설정 또는 openai만 허용하며 그 밖의 값은 시작 시 거부한다. `generation.presets.load_runtime_settings`로 CLI와 같은 모델·프로필을 읽되 서버는 JSONL 경로를 요구하지 않는다. 최종 설정은 [최종 프롬프트 기준](generation-final-prompt.md)을 따른다. 비밀키·가중치는 Git에 게시하지 않는다.

앱별 `GenerationAnswerer`는 첫 유효 문서 답변 요청에서 OpenAI 클라이언트를 생성한다. 초기화만 잠그고 원격 요청 전체는 직렬화하지 않는다. 각 요청은 별도 프롬프트를 구성하고 앱 종료 시 소유한 동기·비동기 클라이언트를 닫는다. 자동 재시도·fallback·temperature 전달은 없다. 문서 렌더러는 원본 knowledge_id·개정·제목·본문·순서를 보존한다. 서버는 `archive.answering_v1`과 `generation_evaluation`을 import하지 않는다. 과거 답변기·평가기의 새 실행 경로는 [보관 안내](../archive/answering_v1/README.md)를 따른다.

문서 게시 상태를 바꾸는 요청은 문서 조립 계층에서 검색 동기화를 수행한다. 라우터·저장소에 임베딩 계산을 넣지 않는다. 검색 반영 완료 후 성공 응답하며 부분 실패·멱등 재시도와 잠금 계약은 [문서 관리](document-management.md#rag-색인과-자정-초기화)를 따른다.

## 오류와 호환

- 입력 오류: 422, 기존 AnswerResponse 형식.
- gate 또는 분류 전용 API의 알려진 분류 저장본·추론 실패: 503, `분류 모델을 사용할 수 없습니다.`. 내부 경로·예외 원문은 반환하지 않는다.
- 문서 공급 오류: 기존 503. 빈 snapshot의 정상 안내와 구별한다.
- 생성 파싱 실패·추가 JSON 키·공백 답변·거절·잘림·timeout·제공자 오류: 안전한 502. 원문·키·예외 메시지는 응답하지 않는다.
- 예상하지 못한 일반 오류: 기존 공통 500 처리. 모델 부재로 오인하지 않는다.

`/documents`와 `/regist-docs`는 같은 SQLite를 사용한다. 기존 doc 입력·초안 생성·중복 409·50,000자/512KiB 제한을 유지한다. 게시와 사람 검수 승인은 별개다. 원본 파일·레거시 append·과거 FastAPI 프로토타입은 보존하며 활성 런타임 쓰기 경로로 사용하지 않는다.

서버는 `classification/`의 학습·평가 모듈이나 아카이브 CLI를 import하지 않는다. 학습·모델 선정·서버 연결·실서비스 품질을 구분한다. 새 모델은 실험 폴더에 저장되며 자동 배포되지 않는다. 기존 실험 CLI·MLflow·과거 HTML은 [아카이브 안내](../archive/classification_v1/README.md)를 따른다.

## 회귀 검증과 문서 유지

서비스는 가짜 분류·문서·답변 의존성으로 세 라벨 분기, 비검색 미호출, snapshot 1회 조회·동일 객체 전달, 빈 문서, 잘못된 라벨·오류를 검증한다. API는 임시 DB·대체 모델로 공개 URL·필드·오류를 확인한다. 실제 모델 연결은 저장된 validation 예측과 서버 추론의 일치 및 모의 생성기를 이용한 HTTP 검증으로 확인한다. 이는 새로운 성능 평가나 실제 LLM 종단 품질 검증이 아니다.

```bash
uv run --locked python -m unittest discover -s tests -t . -v
uv run --locked ruff check .
uv run --locked ruff format --check .
git diff --check
```

구조·내부 계약·연결 상태가 바뀌면 이 문서를 함께 수정한다. 구현과 검증이 끝난 항목만 현재 상태로 기록하고 향후 설계와 구분한다. 작업별 실행 로그는 작업 일지에 둔다. 서비스 정책은 서비스 설계·API 테스트에도 반영하고 [문서 관리 가이드](documentation-guide.md)에 따라 Notion 요약을 갱신·재조회한다. 원격 미게시 파일을 게시 링크처럼 안내하지 않는다.

시연용 자정 초기화는 별도 관리 명령과 systemd 타이머가 담당한다. 복원 트랜잭션·백업·오래된 요청 거부 정책은 [문서 관리 안내](document-management.md#공용-시연-문서-자정-초기화)를 따른다. 공개 시연용 전체 관리 API도 같은 교체 로직과 잠금을 재사용한다. GET /documents/maintenance-preview와 POST /documents/maintenance는 라우터가 HTTP 검증, 서비스가 상태 확인·멱등성·결과 조립, maintenance.py와 reset.py가 준비·백업·트랜잭션 교체를 담당한다. 삭제는 새 백업을 만들지 않고 복원은 백업 후 적용한다. schema v3의 버전 하한과 일반 쓰기 키 무효화로 과거 편집 재실행을 차단한다. 완료된 전체 관리 키는 결과 재확인용으로 보존한다. 임베딩·모델·생성 사용량 저장소는 변경하지 않는다.

## 공개 시연 운영

`SANAEBI_PUBLIC_DEMO=1`에서 IP별 질문·문서 쓰기 제한과 즉시 거절하는 질문 동시 요청 상한을 적용한다. 원자적인 일일 생성 예약은 `app/public_limits.py`가 별도 SQLite에서 관리하고 `GenerationAnswerer`의 실제 provider 호출 직전에 수행한다. 문서 초기화와 카운터 수명주기는 분리한다. 한도 초과는 기존 AnswerResponse를 유지하는 429와 Retry-After, 카운터 장애는 503이다.

`/health/live`·`/health/ready`는 내부 관리용이다. readiness는 설정·문서 snapshot·분류기 첫 추론을 확인하며 생성 API를 호출하지 않는다. 공개 nginx는 웹에 필요한 질문·문서 API만 허용한다. 원문 trace를 끈 운영 환경에서도 생성 시도 여부·상태·token 수·지연은 별도 구조화 로그로 남긴다. 숫자 한도·경로·배포/복구 절차는 [운영 배포](../deployment/README.md)에서 관리한다.

## 선택 의존성과 회귀 테스트 경계

기본 운영 환경은 분류 추론 의존성을 포함하며 Ollama integration은 선택한 경우에만 import한다. Ollama 미설치 안내와 다른 의존성 오류를 구분한다. 서버·평가기는 checkout 실행을 지원하며 공개 HTTP 계약은 유지한다.

회귀 테스트는 runtime·generation·evaluation·classification·legacy로 나누며 공통 fixture와 루트 계산은 tests/support가 맡는다. discovery에는 `-t .`를 지정한다. [테스트 실행 안내](../tests/README.md)를 따른다. 문서 repository는 변환 helper의 독립적 재사용 이득이 작아 기존 구조·트랜잭션 단위를 유지한다.

## 분류 관찰 모드와 비교 경계

`SANAEBI_ROUTING_MODE`는 `advisory`(미설정 기본값), `shadow` 또는 `gate`다. 앱 시작 시 검증해 저장하며 요청이 모드를 선택할 수 없다. 기존 모델·프롬프트는 유지한다.

advisory는 정상 서버 예측을 공통 지침과 함께 전달하며 질문·문서를 우선한다. 라벨별 지침 분기는 없다. shadow는 분류 결과를 기록만 하고 세 라벨 모두 게시 snapshot으로 답변을 시도한다. advisory·shadow는 알려진 분류 저장본/추론 장애만 안전한 유형으로 기록하고 기존 프롬프트로 계속하며 예상 밖 오류와 허용 밖 라벨은 500이다. 문서 장애503·빈 문서 안내·생성 실패502는 유지한다. 동기 분류 실행·잠금 시간은 여전히 요청 지연에 포함된다.

`/assistant`는 전달 라벨을 client 출처로 기록하고 재분류하지 않는다. 앞 단계 ok=false는 기존처럼 생성 없이 끝난다. `/ask`는 model 출처다. 분류 전용 API의 오류 계약은 그대로이며 클라이언트 라벨이나 분류 결과가 실제 데이터 권한을 부여하지 않는다.

trace는 모드·라벨 출처·분류 상태·단계 경과 시간·처리 경로·생성 시도를 별도로 기록한다. 과거 기록의 누락 필드는 미확인으로 읽는다. 라벨은 trace나 전역 상태에서 읽지 않고 요청별 선택적 keyword 인자 ClassificationContext로 전달한다. client 라벨·라벨 없음은 원본 프롬프트로 복귀한다. `TRACE_DIR`의 명시적 원문 기록은 로컬 민감 자료로 취급한다.

관찰 모드 구현과 서비스 기본값 승격은 별개다. 현재 advisory 채택은 [사용자 설계 결정](worklogs/2026-10-16-adopt-advisory.md)이며 품질 개선 입증이 아니다. 라벨 미전달 원복은 `SANAEBI_ROUTING_MODE=shadow` 지정 후 재시작이다. 아래 shadow 채택은 과거 결정이다. 평가에는 임시 DB·고정 snapshot·격리 프로세스를 사용하고 실제 서버 DB를 바꾸지 않는다. 비교 당시 gate를 유지했고, 이후 사용자가 상대 개선을 근거로 shadow 기본값을 채택했다. 절대 품질 기준 충족으로 해석하지 않는다. 원복은 `SANAEBI_ROUTING_MODE=gate`를 지정하고 앱을 재시작한다.

## 선택적 RAG 경계

`SANAEBI_RETRIEVAL_MODE=full|rag`를 앱 시작 시 검증하며 기본 rag를 사용한다. KURE는 현재 게시 개정의 최고 코사인이0.42882221937179565 이상이면 상위20청크를 선택하고 겹친 원문 구간을 병합한다. 개별 청크 하한·추가 본문 문자·전달 토큰 제한은 없다. 상위20은 병합 전 수량이다. 질문512·문서8192토큰과 제공자 입력 한계는 유지한다. rag의 질문 서비스는 같은 snapshot을 retriever에 한 번 전달하고, `RetrievedContext`의 선택 근거를 공통 AnswerInput으로 렌더링해 GenerationAnswerer에 보낸다. full도 snapshot 전체 문서를 같은 입력으로 변환한다. 기존 answer/answer_retrieved 메서드는 호환 입구로 유지하며 생성 호출·예약·파싱·종료는 공통 구현을 사용한다.

검색은 현재 문서/개정/digest를 검증한 청크만 대상으로 한다. 예전 개정을 top-k 이후 거르는 방식은 허용하지 않는다. 빈 원본은 정상 안내, 미완성 색인은503, 검색 입력 초과는422, 일반 코드 오류는500이다. 검색 실패에서 생성기/예산 예약0회를 회귀 검증한다. startup KURE 준비·ready 조회와 생성 API 호출을 분리한다.

기본 벡터 묶음은 실제 host 초기화 원본으로 준비하고, 자정 reset은 원본 복원 후 새 revision mapping만 연결한다. 원본 commit 뒤 실패를 다시 reset으로 복구하지 않는다. 단일 writer lock과 worker 중지/재개의 운영 경계는 [RAG 실행 안내](rag-runtime.md)·[배포 안내](../deployment/README.md)를 따른다. 직접 운영 전환과 서비스 품질 검증은 별도다.

검색 설정 변경은 벡터 입력 변경과 구분한다. KURE 채택은 모델·차원·접두사 변경이므로 별도 vector spec·색인·기본 복원 묶음을 사용한다. 분할용 Tiny tokenizer와360/60 규칙은 유지한다. 기존 Tiny spec·과거 실험과 릴리스 복구는 보존하고 묶음 혼용은 거부한다. [KURE 채택·검증](../retrieval/reports/2026-10-16-kure-adoption/README.md)을 따른다.

## Runnable 조립과 내부 입력

질문 정책은 `questions/service.py`, 문서 흐름 조립은 `questions/pipeline.py`가 담당한다. 분류는 명명된 RunnableLambda로 연결하되 HF 추론과 잠금은 분류기에 남긴다. HTTP 의존성 조립은 full 또는 rag 흐름을 선택하고, 두 흐름 모두 렌더링한 불변 `AnswerInput`을 답변기로 전달한다. 기존 질문 서비스의 함수 주입 인자는 직접 호출·회귀 검증용 호환 경로다.

snapshot은 요청마다 한 번 읽는다. `RunnablePassthrough.assign`은 입력과 snapshot/검색 문맥을 연결하고, 빈 문서·빈 근거는 명시적 분기로 처리한다. 분류·검색·생성의 의존 순서를 유지하며 서로 병렬 실행하지 않는다. HTTP admission, 취소 후 worker 종료까지의 slot 유지, SQLite 트랜잭션과 생성 예산 예약은 체인 밖의 기존 경계를 따른다.

생성 체인은 profile/advisory 구성 → ChatPromptTemplate → 모델 → 응답 정규화 → 결과 검증이다. 문자열만 추출하지 않고 finish_reason·거절·usage를 보존한다. 프로필 본문과 등록 목록을 분리하되 기존 프로필 이름과 문구를 유지한다. 기본 모델은 ChatOpenAI Runnable이며 strict JSON은 공개 SDK adapter를 사용한다.

진단은 callback·단계 이벤트·HTTP middleware·파일 저장으로 분리한다. `diagnostics/trace.py`는 archive와 기존 소비자를 위한 import 경계를 유지한다. 단계 이름·역할은 명시적 metadata로 연결하고, generic chain 입력/출력은 허용된 진단 필드만 기록한다. 전체 snapshot의 객체 표현을 저장하지 않는다.
