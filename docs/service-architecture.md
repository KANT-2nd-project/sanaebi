# 서비스 아키텍처와 질문 처리 흐름

새 [generation 모듈](../generation/README.md)은 프레임워크와 분리된 입력·결과 계약, system/user 프롬프트 구성, 주입받은 모델 함수 호출과 JSON 응답 검사, Ollama/OpenAI 연결부를 구현한 단계다. 새 generation_evaluation과 독립 생성 CLI는 같은 generate_from_documents를 호출한다. 평가는 시간·결과·오류를 기록하고 설정별 요약·기록 저장·복원을 제공한다. 독립 CLI는 명시적 내보내기 JSONL을 받고 서버·DB를 직접 참조하지 않는다. 가짜 클라이언트 테스트와 사용자 실행의 로컬 Ollama 문서 한 건 smoke 결과를 확인했다. 새 경로는 모델 별칭·실험 설정과 사용량·종료 사유를 기록하며 출력 길이 제한은 실패로 처리한다. 전체 문서 품질·변경 프롬프트 재실행·서버 연결은 미검증이다. 서버와 평가기가 동일한 생성 경로를 사용하도록 발전시킨다. 현재 `/ask`·`/assistant`·`answer_pipeline/`는 새 모듈에 연결하지 않았으며 기존 LangChain 실행기를 계속 사용한다. 기존 코드의 아카이브 보존은 채택한 전환 방향이며 실제 이동은 대체 경로 검증 후 수행한다.

- 기준일: 2026-10-14
- 상태: 현재 API 동작과 아직 연결되지 않은 목표 설계를 구분한다.
- 질문 처리 기준: [요청 처리 분류·라벨링 기준 v1.0](label-taxonomy.md)
- 서버 코드 구성과 변경 기준: [서버 구성 규약](server-conventions.md)
- 화면·API 중계·공개 페이지 SEO 설계: [프런트엔드 설계](frontend-architecture.md). Next.js 정적 내보내기 + nginx + FastAPI를 채택한다. 정적 내보내기·로컬 nginx→FastAPI echo 연결과 메모리 기반 대화형 화면을 구현했다. 이전 메시지는 서버 답변에 반영되지 않으며 새 모델 경로의 브라우저 종단 검증·외부 배포는 후속 범위다. 운영에서 nginx가 정적 파일과 API 중계를 담당하고 FastAPI가 질문 처리·인증·권한을 맡는 설계다.
- 질문 데이터와 데이터 상태: [요청 처리 데이터 안내](../data/README.md)
- 프로젝트 설계 참고: [Notion 서비스 처리 기준](https://app.notion.com/p/3f805a3cdadc81d7b909fc71ed78381b)

코드의 호출 순서는 [서버 요청 흐름](../app/README.md)에서 설명한다. 이 문서는 처리 정책과 설계 경계를 관리한다.

## 현재 구현 상태

현재 `/ask`는 질문 서비스를 통해 분류하고, 검색 라벨·유효 문서가 있을 때만 LangChain을 호출한다. `/documents`와 `/regist-docs`는 같은 SQLite 저장소에 초안을 생성하고, 검색 답변은 현재 유효한 게시본만 읽는다. 게시와 사람 검수 승인은 별개다.

| 구성 | 저장소에서 확인한 동작 |
|---|---|
| `GET /` | FastAPI 서버 실행 메시지를 반환한다. |
| `POST /ask` | 현재 질문을 KoELECTRA Base로 분류하고 질문 서비스의 라벨 정책에 따라 고정 안내 또는 생성 답변을 AnswerResponse로 반환한다. |
| `POST /assistant` | 이미 분류한 response·classification_label을 LangChain 실행기에 전달하고 기존 출력 형식을 그대로 반환한다. |
| `POST /regist-docs` | doc 문자열을 검증해 SQLite 초안을 생성한다. 성공 응답은 유지하며 중복은 409다. |
| 기존 질문·레거시 HTTP 응답 | AnswerResponse는 ok, text, reason을 가진다. 요청 검증 오류는 같은 응답 형태로 HTTP 422를 반환한다. |
| `/documents` | SQLite 초안·개정·게시·중단을 관리하며 문서 전용 오류 계약을 사용한다. [상세 계약](document-management.md)을 따른다. |
| 질문 처리 분류 | `/classify/koelectra-base`에서 분류만 확인하거나 `/ask`에서 분류 후 답변 생성을 실행한다. |
| 질문 서비스 | `handle_question`은 활성 /ask 처리 서비스다. dependencies가 앱별 분류기·snapshot reader·답변 어댑터를 조립한다. `/ask/langchain`은 제거했다. |
| 문서 답변 | /ask의 라벨별 정책과 snapshot 전달을 검증했다. 기존 LangChain 실행기는 유지하며 실제 LLM 답변 품질은 별도 검증 대상이다. |

앱 연결과 공통 오류 처리는 [진입점](../app/fastapi_main.py), 입력·응답 형식은 [스키마](../app/schemas.py), 엔드포인트는 [질문 라우터](../app/questions/router.py)와 [문서 라우터](../app/documents/registration.py), SQLite 저장은 [문서 저장소](../app/documents/repository.py)에서 확인한다. 현재 `POST /ask`는 질문 서비스를 거쳐 검색 라벨·유효 문서가 있는 경우에만 LangChain을 호출한다. SANAEBI_ANSWER_PROVIDER로 Ollama 또는 OpenAI 하나를 선택하고, 성공 시 reason은 빈 문자열로 반환한다. `POST /regist-docs`는 doc 본문으로 SQLite 초안을 생성하며 자동 게시하지 않는다.

등록 요청은 기존 `{"doc":"본문"}` 형식을 유지하며 50,000자·512KiB 제한을 적용한다. 게시 전에는 답변에 사용하지 않는다. 원본 JSONL은 최초 이관·과거 평가를 위해 보존한다.

[LangChain 실행기](../sanaebi_assistant.py)는 `/assistant`·`/ask`·독립 실행에서 공통 SQLite provider를 사용한다. 검색 질문마다 snapshot을 한 번 확보하고 읽기 트랜잭션을 닫은 뒤 모델을 호출한다. `/assistant`의 provider별 기록에는 `model_called`가 포함된다. 빈 게시 목록은 모델 호출 없이 자료 없음 안내를 반환한다. DB 오류는 HTTP 503, 모델 호출 실패는 기존 502다. 명시적인 평가용 `documents_path`만 JSONL을 읽는다.

`/ask`는 SANAEBI_ANSWER_PROVIDER로 선택한 한 모델의 답변을 AnswerResponse로 변환한다. 실행기의 기본 실행은 두 모델을 비교한다. /ask의 CLARIFY·UNSUPPORTED는 서비스의 고정 안내로 종료하며 문서·LLM을 호출하지 않는다. /assistant는 기존 실행기 계약을 유지한다. 2026-10-15 사용자 결정으로 KoELECTRA base를 현 단계 서버 분류기로 채택했다. [선정 근거와 연결 절차](worklogs/2026-10-15-classifier-selection.md)를 따른다. 기존 연동 코드의 존재와 이번에 선정한 checkpoint의 연결 완료는 구분하며, 이번 저장본은 공통 Transformer 추론기로 연결한다. 검증 결과는 [연결 작업 기록](worklogs/2026-10-15-server-classifier-integration.md)을 따른다.

## 목표 질문 처리 흐름

분류 입력은 현재 질문 하나다. 대화 이력이나 사용자별 실시간 정보를 분류 입력으로 사용하지 않는다. 라벨은 다음 처리 경로를 고르며 문서의 존재나 답변 근거가 충분한지를 판정하지 않는다. 세 라벨의 유일한 상세 기준과 경계 사례는 [라벨 기준](label-taxonomy.md)에 둔다.

| 라벨 | 목표 처리 |
|---|---|
| `SEARCH_KNOWLEDGE` | 회사 문서를 근거로 답변을 시도한다. 답변 단계에서 실제 근거와 한계를 확인한다. |
| `CLARIFY` | 대상이나 원하는 도움을 알 수 있도록 구체적으로 되묻는다. |
| `UNSUPPORTED` | 현재 지원하지 않는 조회·실행·요청임을 안내한다. |

SEARCH_KNOWLEDGE로 분류된 질문에는 SQLite의 유효 게시 문서 전체, 공통 답변 지침, 원래 질문을 LangChain 흐름에 전달해 LLM 답변을 만든다. CLARIFY와 UNSUPPORTED는 각각 되묻기와 지원 범위 안내로 처리한다.

```mermaid
flowchart TD
    Q["현재 질문"] --> C{"요청 처리 분류"}
    C -->|"SEARCH_KNOWLEDGE"| D["회사 문서 전체 + 공통 지침 + 원래 질문"]
    D --> LC["LangChain"] --> LLM["LLM 답변 생성"]
    LLM --> E["근거·충돌·자료 부족 확인"]
    C -->|"CLARIFY"| CL["필요한 정보 되묻기"]
    C -->|"UNSUPPORTED"| U["지원 범위 안내"]
```

문서 답변은 SQLite의 현재 유효한 게시본 전체를 사용한다. 기존 71건 JSONL은 최초 이관 원본으로 보존하며 서비스는 파일과 DB를 합치지 않는다. 관리 화면의 게시·사용 중단은 다음 검색 질문에 적용된다. 요청 단위 snapshot을 모델 호출 전에 확보하며 두 provider도 같은 문서를 사용한다. 명시적 평가 JSONL은 재현용으로 유지한다. 저장·이관 기준은 [문서 관리](document-management.md), 원본 이력은 [회사 정책 데이터](../data/README.md#답변용-회사-지식)를 따른다. RAG는 후속 검토 범위다.

## 답변 규칙과 경계

- 회사 문서에 근거한 사실만 답하고, 근거에 없는 사내 규정·날짜·담당자·개인 상태를 추측하지 않는다.
- 필요한 근거를 찾지 못하면 정보가 부족하다고 말한다. 문서가 없다는 사실이 질문 처리 라벨을 바꾸지는 않는다.
- 문서끼리 충돌하면 충돌 사실과 각각의 근거를 알린다. 날짜만으로 우선순위를 정하지 않는다.
- 문서 본문은 참고 데이터로 취급한다. 본문에 포함된 모델 지시나 비밀 공개 요청을 시스템 지시처럼 따르지 않는다.
- 전체 문서를 모델 입력에 담을 수 없으면 일부를 조용히 생략하거나 자르지 않는다. 호출을 멈추고 처리 한도 안내 또는 오류로 다룬다.
- 개인·조직의 실시간 기록 조회나 신청·변경 실행을 완료했다고 표현하지 않는다. 정보 요청과 실행 요청이 섞인 질문은 안내 가능한 정보만 답하고 실행할 수 없는 부분을 밝힌다.
- 응답은 현재 AnswerResponse 필드 안에서 표현한다. 이 문서는 공개 요청·응답 스키마 변경을 정하지 않는다.

신규 문서 관리 API는 불변 개정본과 게시본을 구분하지만 문서별 접근 권한은 아직 제공하지 않는다. 전체 문서 답변을 연결할 때에는 열람이 허용된 공통 회사 자료만 입력에 제공한다. 접근 권한이 다른 자료를 다루려면 LLM 호출 전에 서버에서 권한을 검사하는 설계를 별도로 마련해야 한다.

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

세 라벨의 의미·경계, JSON Lines 문서 전체 제공, 단계별 평가 구분은 이 프로젝트의 설계 결정이다. 사용할 모델, 입력 예산, 분류 점수, 근거 인용 정확성, 응답 시간과 비용은 아직 확인되지 않았다.

## 등록 자료의 관리와 답변 연결 단계

로컬 `/admin/documents`에서 초안·개정·게시·중단을 관리하고 `/ask`·`/assistant`는 같은 SQLite의 유효 게시본을 사용한다. `/regist-docs`도 동일 DB에 초안을 저장한다. 게시본 0건은 모델 호출 없이 안내하고 저장소 장애는 503으로 구분한다. [문서 관리 안내](document-management.md)를 따른다.
