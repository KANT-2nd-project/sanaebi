# 서비스 아키텍처와 질문 처리 흐름

서버와 독립 생성·평가는 같은 [generation 모듈](../generation/README.md)의 최종 Luna 설정과 프롬프트·응답 검사를 사용한다. 서버는 SQLite 게시 snapshot을, CLI는 명시적으로 내보낸 JSONL을 사용하며 같은 렌더러로 프롬프트를 구성한다. 연결 구현과 검증 결과·남은 한계는 [서버 생성 통합 기록](worklogs/2026-10-15-server-generation-integration.md)을 따른다. 과거 실행기와 평가 자료는 비활성 레거시 재현용으로 보존한다.

- 기준일: 2026-10-15
- 상태: 코드 기본값은 shadow + rag(KURE)이며 gate와 명시적 full을 선택할 수 있다. 실제 운영 적용 상태는 별도 확인한다.
- 질문 처리 기준: [요청 처리 분류·라벨링 기준 v1.0](label-taxonomy.md)
- 서버 코드 구성과 변경 기준: [서버 구성 규약](server-conventions.md)
- 화면·API 중계·공개 페이지 SEO 설계: [프런트엔드 설계](frontend-architecture.md). Next.js 정적 내보내기 + nginx + FastAPI를 채택한다. 정적 내보내기·FastAPI 연결과 메모리 기반 대화형 화면을 구현하고 [공개 데모](https://sanaebi.29232923.xyz/chat)를 운영한다. 이전 메시지는 서버 답변에 반영되지 않는다. 배포·접속 검증과 모델 답변 품질 승인은 구분한다. 공용 가상 문서는 매일 한국시간 자정에 초기화된다. 공개 데모는 익명 질문·문서 편집·게시를 허용하며 nginx가 공개 API를 제한하고 FastAPI가 요청 제한·일일 생성 예산을 적용한다. 운영 구성은 [배포 안내](../deployment/README.md)를 따른다.
- 질문 데이터와 데이터 상태: [요청 처리 데이터 안내](../data/README.md)
- 프로젝트 설계 참고: [Notion 서비스 처리 기준](https://app.notion.com/p/3f805a3cdadc81d7b909fc71ed78381b)

코드의 호출 순서는 [서버 요청 흐름](../app/README.md)에서 설명한다. 이 문서는 처리 정책과 설계 경계를 관리한다.

## 현재 구현 상태

현재 `/ask`는 질문 서비스를 통해 분류한다. 선택적 `gate`는 검색 라벨·유효 문서가 있을 때만 생성한다. 기본 `shadow`는 분류 결과를 관찰 기록으로 남기고 유효 문서가 있으면 생성한다. `/documents`와 `/regist-docs`는 같은 SQLite 저장소에 초안을 생성하고, 검색 답변은 현재 유효한 게시본만 읽는다. 게시와 사람 검수 승인은 별개다.

| 구성 | 저장소에서 확인한 동작 |
|---|---|
| `GET /` | FastAPI 서버 실행 메시지를 반환한다. |
| `POST /ask` | 현재 질문을 KoELECTRA Base로 분류하고 질문 서비스의 라벨 정책에 따라 고정 안내 또는 생성 답변을 AnswerResponse로 반환한다. |
| `POST /assistant` | 기존 response·classification_label 입력을 공통 라벨 정책에 전달하고 `{ok,text,reason}`를 반환한다. 재분류·두 모델 비교는 수행하지 않는다. |
| `POST /regist-docs` | doc 문자열을 검증해 SQLite 초안을 생성한다. 성공 응답은 유지하며 중복은 409다. |
| 기존 질문·레거시 HTTP 응답 | AnswerResponse는 ok, text, reason을 가진다. 요청 검증 오류는 같은 응답 형태로 HTTP 422를 반환한다. |
| `/documents` | SQLite 초안·개정·게시·중단을 관리하며 문서 전용 오류 계약을 사용한다. [상세 계약](document-management.md)을 따른다. |
| 질문 처리 분류 | `/classify/koelectra-base`에서 분류만 확인하거나 `/ask`에서 분류 후 답변 생성을 실행한다. |
| 질문 서비스 | `handle_question`은 활성 /ask 처리 서비스다. dependencies가 앱별 분류기·snapshot reader·답변 어댑터를 조립한다. `/ask/langchain`은 제거했다. |
| 문서 답변 | /ask의 라벨별 정책과 snapshot 전달을 검증했다. 최종 generation 모듈을 사용하며 실제 LLM 답변 품질 승인은 별도다. 과거 실행기는 오프라인 재현용으로 보존한다. |

앱 연결과 공통 오류 처리는 [진입점](../app/fastapi_main.py), 입력·응답 형식은 [스키마](../app/schemas.py), 엔드포인트는 [질문 라우터](../app/questions/router.py)와 [문서 라우터](../app/documents/registration.py), SQLite 저장은 [문서 저장소](../app/documents/repository.py)에서 확인한다. 원복용 `gate`의 `POST /ask`는 검색 라벨·유효 문서가 있는 경우에만 생성한다. 최종 Luna만 사용하며 성공 시 reason은 빈 문자열로 반환한다. `POST /regist-docs`는 doc 본문으로 SQLite 초안을 생성하며 자동 게시하지 않는다.

등록 요청은 기존 `{"doc":"본문"}` 형식을 유지하며 50,000자·512KiB 제한을 적용한다. 게시 전에는 답변에 사용하지 않는다. 원본 JSONL은 최초 이관·과거 평가를 위해 보존한다.

`/ask`와 `/assistant`는 같은 앱 설정을 사용한다. 기본 shadow는 세 라벨 모두 문서 단계로 진행하고, gate에서만 CLARIFY·UNSUPPORTED를 고정 안내로 종료한다. 문서 단계는 SQLite snapshot을 한 번 확보하고 읽기 트랜잭션을 닫은 뒤 full 또는 rag 근거로 `GenerationAnswerer`를 호출한다. 빈 게시 목록은 정상 안내다. 알려진 분류 장애는 shadow에서 기록 후 계속하며 gate에서는 503이다. DB·색인 장애는 503, 생성 결과·제공자 오류는 502, 예상 밖 코드 오류는 500이다. `/assistant`의 앞 단계 실패 입력은 생성하지 않는다.

2026-10-15 사용자 결정으로 KoELECTRA base를 현 단계 서버 분류기로 채택했다. [선정 근거와 연결 절차](worklogs/2026-10-15-classifier-selection.md)를 따른다. 기존 연동 코드의 존재와 이번에 선정한 checkpoint의 연결 완료는 구분하며, 이번 저장본은 공통 Transformer 추론기로 연결한다. 검증 결과는 [연결 작업 기록](worklogs/2026-10-15-server-classifier-integration.md)을 따른다.

## 현재 질문 처리 흐름

분류 입력은 현재 질문 하나이며 대화 이력은 사용하지 않는다. 라벨 의미·데이터 정답은 [라벨 기준](label-taxonomy.md)에서 관리한다. 기본 shadow는 라벨을 관찰만 하고, 선택적 gate는 CLARIFY·UNSUPPORTED를 고정 안내로 종료한다. 라벨은 답변 근거의 존재나 권한을 보장하지 않으며 생성 프롬프트에 전달하지 않는다.

```mermaid
flowchart TD
    Q["현재 질문"] --> C["분류·결과 기록"]
    C --> M{"라우팅 모드"}
    M -->|"shadow: 세 라벨 모두"| D["SQLite 게시 snapshot 1회"]
    M -->|"gate: SEARCH_KNOWLEDGE"| D
    M -->|"gate: CLARIFY 또는 UNSUPPORTED"| G["고정 안내"]
    D --> V{"게시 문서 있음"}
    V -->|"없음"| N["자료 없음 안내"]
    V -->|"있음"| R{"문서 공급 모드"}
    R -->|"full: 수동 선택"| F["게시본 전체"]
    R -->|"rag: 기본 C"| S["유효 색인에서 근거 검색"]
    F --> L["질문·문서 근거·공통 지침으로 생성"]
    S --> L
    L --> A["응답 형식 검사 후 답변 또는 생성 오류"]
```

| 라우팅 / 문서 공급 | 문서 단계 진입 | 생성에 전달하는 근거 |
|---|---|---|
| shadow + full | 세 라벨 모두 | 게시본 전체 |
| shadow + rag (기본) | 세 라벨 모두 | 검색으로 선택한 근거 |
| gate + full | SEARCH_KNOWLEDGE | 게시본 전체 |
| gate + rag | SEARCH_KNOWLEDGE | 검색으로 선택한 근거 |

빈 문서는 검색·생성하지 않는다. 준비된 색인에서 임계값 이상 근거가 없으면 고정 안내로 끝내며 생성 예약을 소비하지 않는다. rag 색인 미준비·장애는 503이며 full로 자동 fallback하지 않는다. 검색 입력 초과는 422다. 코드 기본값은 실행 중 서버의 실효 설정이나 배포 완료를 증명하지 않는다.

명시적 full 경로는 SQLite의 현재 유효한 게시본 전체를 사용한다. 기존 71건 JSONL은 최초 이관 원본으로 보존하며 서비스는 파일과 DB를 합치지 않는다. 관리 화면의 게시·사용 중단은 다음 검색 질문에 적용된다. 요청 단위 snapshot을 모델 호출 전에 확보하고 Luna 단일 호출에 전달한다. 명시적 평가 JSONL은 재현용으로 유지한다. 저장·이관 기준은 [문서 관리](document-management.md), 원본 이력은 [회사 정책 데이터](../data/README.md#답변용-회사-지식)를 따른다. RAG의 임베딩은 사용자 결정으로 KURE-v1을 채택했다. [채택·연결 기록](../retrieval/reports/2026-10-16-kure-adoption/README.md)을 따른다. 별도 SQLite 벡터 저장소·서버 검색 연결·게시 개정 동기화를 구현했다. 기본 rag는 질문 최고 코사인이0.42882221937179565 이상이면 KURE 상위20청크를 선택하고 원문 중복을 병합한다. 개별 청크 하한·추가 문자·전달 토큰 제한은 없다. 준비 중 요청은503이며 운영 전환·품질 검증과 구분한다. [실행 계약](rag-runtime.md)을 따른다.

검색 구성의 후속 판단은 [평가 기준 보완·최적화 비교](../retrieval/reports/2026-10-15-retrieval-v3/README.md)를 따른다. 신규 확인에서 근거 손실이 발생해 C를 유지했으며 검색 최적성·생성 품질·운영 승인을 뜻하지 않는다.

## 답변 규칙과 경계

- 회사 문서에 근거한 사실만 답하고, 근거에 없는 사내 규정·날짜·담당자·개인 상태를 추측하지 않는다.
- 필요한 근거를 찾지 못하면 정보가 부족하다고 말한다. 문서가 없다는 사실이 질문 처리 라벨을 바꾸지는 않는다.
- 문서끼리 충돌하면 충돌 사실과 각각의 근거를 알린다. 날짜만으로 우선순위를 정하지 않는다.
- 문서 본문은 참고 데이터로 취급한다. 본문에 포함된 모델 지시나 비밀 공개 요청을 시스템 지시처럼 따르지 않는다.
- 전체 문서를 모델 입력에 담을 수 없으면 일부를 조용히 생략하거나 자르지 않는다. 호출을 멈추고 처리 한도 안내 또는 오류로 다룬다.
- 개인·조직의 실시간 기록 조회나 신청·변경 실행을 완료했다고 표현하지 않는다. 정보 요청과 실행 요청이 섞인 질문은 안내 가능한 정보만 답하고 실행할 수 없는 부분을 밝힌다.
- 응답은 현재 AnswerResponse 필드 안에서 표현한다. 이 문서는 공개 요청·응답 스키마 변경을 정하지 않는다.

2026-10-15 후속 답변 개선에서는 출처를 제목·항목으로 표시하고, 문서의 특이함만으로 타당성을 추측하지 않되 필요한 정보 부족·조건·충돌 안내는 유지하는 방향을 검증했다. 후보 v2는 회귀 누락·JSON 실패로 **기본값에 적용하지 않았으며 당시 v1을 유지**했다. [프롬프트 기준](generation-final-prompt.md#후속-출처-표시문서-충실성-개선-검증)과 [실험 결과](../generation_evaluation/reports/2026-10-15-answer-grounding/README.md)를 따른다. 이 방향을 현재 보장된 동작으로 해석하지 않는다. 후속 [v3 최소 변경 검증](../generation_evaluation/reports/2026-10-15-answer-grounding-v3/README.md)도 신고 정보 누락으로 초기 게이트를 통과하지 못해 당시 기본값은 v1을 유지했다.

신규 문서 관리 API는 불변 개정본과 게시본을 구분하지만 문서별 접근 권한은 아직 제공하지 않는다. 전체 문서 답변을 연결할 때에는 열람이 허용된 공통 회사 자료만 입력에 제공한다. 접근 권한이 다른 자료를 다루려면 LLM 호출 전에 서버에서 권한을 검사하는 설계를 별도로 마련해야 한다.

## 분류 관찰 모드

`SANAEBI_ROUTING_MODE`는 앱 시작 시 `shadow`(기본값) 또는 `gate`로 고정된다. `/ask`와 `/assistant`가 같은 정책을 사용한다. `/ask`는 모델 예측을, 재분류하지 않는 `/assistant`는 클라이언트 제공 라벨을 기록한다. `/assistant`의 앞 단계 실패는 생성하지 않는다.

`shadow`는 회사 밖 질문을 자유롭게 답하도록 허용하는 설정이 아니다. 라벨을 프롬프트에 넣지 않고 기존 문서 기반 생성 지침으로 범위·자료 부족·실행 불가를 판단하게 하는 비교 경로다. 알려진 분류 로딩·추론 장애는 안전한 상태를 기록하고 계속 진행하지만, 예상 밖 오류·잘못된 내부 라벨은500으로 남긴다. 분류를 동기 실행하므로 그 지연도 포함된다. 상세 계약은 [서버 규약](server-conventions.md#분류-관찰-모드와-비교-경계)을 따른다.

40문항×두 경로×두 반복 비교의 기준·실제 결과·권고는 [종단 비교 보고서](../generation_evaluation/reports/2026-10-15-routing-shadow/README.md)에 둔다. 비교 후 사용자가 상대 개선을 근거로 기본값을 `shadow`로 채택했다. 두 반복 통과는 gate 25/40, shadow 30/40으로 사전 36/40 기준에는 미달한다. main 통합으로 v3 프롬프트와 함께 사용한다. 이 비교·채택 당시에는 실행 중인 서버 전환·공개 배포를 수행하지 않았다. 이후 공개 배포와 설정 확인은 [main 배포 기록](worklogs/2026-10-15-main-deploy-doc-sync.md)을 따른다. [후속 채택 결정](worklogs/2026-10-15-adopt-shadow.md)에 사유와 원복 방법을 기록한다. 이번 비교는 고정된 v1 생성 구성의 합성 자료 평가로, 다른 프롬프트 변경의 품질이나 운영 신뢰성을 보장하지 않는다.

## 질문 데이터와 평가 설계

질문 분류 데이터는 학습·평가용 입력이며 회사 문서나 답변 근거가 아니다. 라벨 의미는 이 문서와 [요청 처리 분류·라벨링 기준](label-taxonomy.md), 데이터 구성·검수·분할 기록은 [데이터 안내](../data/README.md)에서 확인한다.

라우터와 문서 답변 경로를 따로 평가한 뒤 실제 분류기가 연결되면 종단 흐름을 확인한다. 답변 경로만 시험하려고 라벨을 고정해 입력하더라도 그 결과를 라우터 성능으로 해석하지 않는다.

- 라우터: Accuracy, Macro-F1, 클래스별 Precision·Recall·F1, 혼동행렬과 대표 오분류 사례를 확인한다.
- 답변 흐름: 근거 충실성, 근거 부족·충돌 처리, 혼합 요청의 실행 한계 안내를 확인한다.
- 종단 흐름: 실제 라우터가 고른 경로에 따른 답변 결과와 각 단계의 오류를 함께 기록한다.
- 데이터 준비와 평가 결과를 실제 회사 근거 자료와 구분한다. 검수 상태와 데이터 제약은 데이터 안내를 기준으로 해석한다.

## 설계 근거와 한계

아래 자료는 설계 참고 자료다. 인용한 접근은 설계 참고이며, 사내비에서 성능이 검증됐다는 뜻은 아니다.

| 참고 자료 | 설계에 참고한 점 | 사내비에서 확인할 사항 |
|---|---|---|
| [Anthropic, Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) | 작은 지식 집합에서 전체 내용을 프롬프트에 제공하는 방식도 고려할 수 있다는 설명 | 실제 회사 문서 총량, 모델 입력 한도, 답변 품질과 비용 |
| [Anthropic, Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | 입력을 분류하고 적절한 후속 처리로 보내는 라우팅 패턴 | 세 라벨 경계와 분류 결과의 실제 품질 |
| [LangChain, Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) | 구조화된 경로와 조건 분기로 후속 처리를 연결하는 예시 | 프로젝트 코드에서 필요한 경계와 기존 API 계약에 맞는 구현 |
| [Liu et al., Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/) | 긴 문맥 안에서 관련 정보 위치에 따라 결과가 달라질 수 있다는 실험 | 선택한 모델과 실제 문서에서 위치·문서 수에 따른 근거 품질 |
| [LangSmith, Evaluation types](https://docs.langchain.com/langsmith/evaluation-types) | 대표 입력과 기준 출력으로 오프라인 평가를 구성하는 방법 | 라우터, 답변 생성, 종단 평가의 데이터와 통과 기준 |
| [Anthropic, Mitigating the risk of prompt injections in browser use](https://www.anthropic.com/research/prompt-injection-defenses) | 외부 문서에 모델 지시를 바꾸려는 문구가 포함될 수 있다는 위험 | 문서 본문을 데이터로 다루는 지침의 실제 효과와 별도 방어 필요성 |

세 라벨의 의미·경계와 단계별 평가 구분은 프로젝트의 설계 결정이다. 서버 근거는 SQLite 게시본이며 full/rag 설정에 따라 전체 또는 선택 근거를 사용한다. 선정 모델·실측 결과는 [생성 기준](generation-final-prompt.md)과 [검색 실행·평가 상태](rag-runtime.md)에서 확인한다. 개별 실험 결과를 전체 품질 승인이나 운영 성능으로 일반화하지 않는다.

## 등록 자료의 관리와 답변 연결 단계

로컬 `/admin/documents`에서 초안·개정·게시·중단을 관리하고 `/ask`·`/assistant`는 같은 SQLite의 유효 게시본을 사용한다. `/regist-docs`도 동일 DB에 초안을 저장한다. 게시본 0건은 모델 호출 없이 안내하고 저장소 장애는 503으로 구분한다. [문서 관리 안내](document-management.md)를 따른다.

## 공용 시연 자료 복원

시연 전용 SQLite를 기준 JSONL의 게시 자료로 매일 한국 시간 자정에 복원하는 관리 명령과 systemd 예약 템플릿을 제공한다. 실제 배포 서버에서 예약을 설치·활성화해야 동작한다. 사용자별 공간 분리는 없으며 당일 변경은 다른 시연자에게도 영향을 준다. 백업·동시 요청·복원 정책은 [문서 관리 안내](document-management.md#공용-시연-문서-자정-초기화), 설치는 [배포 안내](../deployment/README.md#운영-확인과-복구)를 따른다.

후속 [반복 비교](../generation_evaluation/reports/2026-10-15-answer-grounding-repeat/README.md)에서는 신고 완전 응답이 v1 15/25·v3 20/25로 이전 소표본의 악화 방향이 재현되지 않았다. 이는 v3의 서비스 품질 승인이나 기본값 전환이 아니며 당시 v1을 유지했다.

반복 결과를 확인한 사용자의 후속 채택 요청으로 당시 공통 기본값과 서버 런타임 프리셋을 **examples_answer_scope_v3**로 전환했다. 내부 식별자 대신 제공된 제목·항목을 사용하고 문서가 상식과 다르다는 이유만으로 의도·타당성을 추측하지 않도록 지시한다. 필요한 정보 부족·조건·충돌 안내와 문서 내 모델 조작 지시 방어는 유지한다. 알려진 누락 해결·전체 품질 보증과 구분하며 [현재 채택 기준](generation-final-prompt.md#후속-채택-v3-기본값-전환)을 따른다.


사용자용 말투·범위 구분 보완 이후 현재 공통 기본 프로필은 **examples_answer_scope_v5**다. 자료 부족과 회사 업무 범위 밖을 구분하고, 작성 규칙 선언 대신 질문에 직접 답한다. 사내 기술 문서·부분 답변·명시적 출처 설명은 유지한다. [v5 채택과 남은 품질 한계](generation-final-prompt.md#후속-채택-사용자용-말투서비스-범위-v5)를 따른다.

## 검색 근거 구성

현재 기본 `SANAEBI_RETRIEVAL_MODE=rag`로 게시 개정별 검색을 연결한다. `full`은 명시적인 수동 복구 경로다. shadow/gate 정책은 유지하며 원본 snapshot 한 번 → 유효 색인 확인 → 선택 근거 → 기존 생성기 순서다. 색인 미준비는503이고 전체 문서 자동 fallback은 없다. [RAG 실행 계약](rag-runtime.md)을 따른다. 코드 기본값 변경과 운영 전환·실제 답변 품질 승인은 별개다.

## 분류 참고 정보 비교 결과

분류 라벨을 오류 가능한 생성 참고 정보로 전달하는 후보는 탐색 기준을 충족하지 못해 미채택했다. 현재 shadow/gate와 HTTP 계약은 유지하며, advisory 서버 모드는 제공하지 않는다. [평가 결과](../generation_evaluation/reports/2026-10-15-classification-advisory/README.md)에서 분모·비용·한계를 확인할 수 있다.

문서 변경의 완료 경계는 [문서 관리 계약](document-management.md#rag-색인과-자정-초기화)을 따른다. rag의 게시·철회·전체 삭제·기본 복원은 현재 게시 snapshot의 검색 준비 확인 후 성공 응답한다. 문서 저장 후 검색 반영 실패는 자료를 보존하고 같은 요청으로 복구한다. 초안 저장은 임베딩하지 않는다.
