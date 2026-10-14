# 로컬 문서 등록·관리

문서 관리 화면은 `/admin/documents`다. 제목·본문을 붙여 넣어 초안을 저장하고, 편집·게시·사용 중단할 수 있다. 현재 기능은 **로컬 가상 공통 자료 시연용**이며 사용자 인증이나 부서별 접근 권한은 제공하지 않는다. 관리와 답변 생성은 같은 SQLite 저장소를 사용한다. `/ask`·`/assistant`와 기본 독립 실행기는 현재 유효한 게시본만 답변에 전달한다.

## 저장과 상태

서비스 문서는 `var/documents.sqlite3`에 저장한다. `SANAEBI_DOCUMENT_DB`로 다른 경로를 지정할 수 있다. DB·WAL·SHM·백업은 Git에 넣지 않는다. 기존 `app/documents.jsonl`과 `data/company-knowledge/documents.jsonl`은 수정하지 않는다.

- 초안: 저장되었지만 답변 대상은 아니다.
- 게시: 지정한 개정본을 답변 대상으로 선택한다. 다음 검색 질문부터 적용한다.
- 적용 대기: 게시본의 시행일이 서울 기준 미래 날짜다.
- 수정 초안: 게시 후 편집한 내용은 새 개정본이며 재게시 전에는 기존 게시본이 유지된다.
- 사용 중단: 문서 제공 대상에서 제외하되 원문과 변경 기록은 보존한다. 영구 삭제는 제공하지 않는다.

이미 유효한 게시본이 있을 때 미래 시행일 개정본으로 교체하는 예약 기능은 제공하지 않는다. 해당 날짜에 수동 게시한다. 원문은 공백·개행까지 보존하며 메타데이터만 바꿔도 새 개정본을 만든다. 제목·본문이 같은 신규 문서는 중복 오류로 안내한다.

## API

웹은 아래 경로 앞에 `/api`를 붙인다. 개발 Next와 nginx가 FastAPI로 중계하면서 접두사를 제거한다.

| 경로 | 역할 |
|---|---|
| GET /documents/capabilities | local-demo·answer_integration="connected" (문서 연결 상태이며 품질·인증 보장은 아님) |
| GET /documents | 제목 검색·상태 필터·페이지 목록, 본문 제외 |
| GET /documents/{id} | 초안·게시본 상세 |
| POST /documents | 초안 생성 |
| PATCH /documents/{id} | 새 초안 개정 |
| POST /documents/{id}/publish | 지정 초안 게시 |
| POST /documents/{id}/withdraw | 사용 중단 |

새 쓰기 API에는 UUID `Idempotency-Key`가 필요하다. 수정·게시·중단은 `expected_version`, 게시는 `revision_id`도 받는다. 같은 키로 같은 요청을 다시 보내면 기존 결과를 반환한다(24시간). 다른 요청에 같은 키를 쓰거나 다른 탭에서 먼저 수정했으면 409다. 자동 재전송하지 않으며 통신 실패 시 같은 요청의 키를 유지해 수동 재시도한다.

필수 제목은 최대200자, 본문은 최대50,000자다. 출처 이름·담당 부서·출처 URL·시행일을 추가할 수 있다. URL은 원본 위치 표시용이며 서버가 가져오지 않는다. JSON 요청 본문은 최대512KiB다. 신규 오류는 `{ok:false,error:{code,message,details?}}`이며 기존 질문/레거시 API의 응답 형식과 다르다. 모든 문서 API 응답은 no-store다.

`POST /regist-docs`는 기존 `{doc}` 입력과 성공 AnswerResponse를 유지하며 같은 SQLite에 초안을 저장한다. 제목은 본문 첫 유효 줄의 앞 200자다. 본문 50,000자·요청 512KiB 제한, 동일 제목·본문 중복 409가 적용된다. 레거시 등록은 자동 게시하지 않는다. 기존 JSONL 파일은 자동 이관하지 않으며 별도 레거시 이관 도구로 보존·이관한다.

## 데이터 공급과 답변

`DocumentContextProvider`는 SQLite에서 유효한 게시 개정본과 출처 메타데이터를 한 읽기 트랜잭션으로 확보한다. 초안·중단·미래 시행본은 제외한다. 한 검색 질문은 하나의 고정 snapshot을 사용하고 두 모델 비교도 같은 문서를 사용한다. LLM 호출 전에 트랜잭션을 닫는다. 게시본이 0건이면 모델 호출 없이 자료 없음 안내를 반환한다. DB 누락·손상·잠금 오류는 503이며 JSONL로 대체하거나 빈 목록으로 숨기지 않는다.

원본 문서는 이관 순서, 새 문서는 생성 시각·UUID 순서로 제공한다. 원문은 그대로 저장하고 프롬프트를 만들 때 기존 공백 정규화를 적용한다. 문서 전체 입력 방식은 유지하며 모델 문맥 한도·답변 품질은 별도 검증한다. `/assistant`의 provider별 `model_called`는 실제 모델 실행 여부를 나타낸다.

SQLite schema v2는 기존 문서·개정·이벤트·멱등성을 유지하고 원본 이관 추적과 개정 메타데이터를 추가한다. 원본 ID·버전·출처 ID·정책 결정 ID·분류·검수 상태를 보존한다. 관리 UUID와 원본 ID는 다르다. 수정 개정은 출처 정보를 계승하되 `review_status=unreviewed`가 된다. 게시를 사람 검수 승인으로 해석하지 않는다. 상세 화면의 출처 정보는 읽기 전용이다.

기본 경로는 `SANAEBI_DOCUMENT_DB`로 통일한다. `IEUM_WORKS_PATH`는 런타임에서 사용하지 않고 경고한다. 명시적 평가 `--documents`는 고정 JSONL을 계속 읽으며 라이브 DB와 자동 병합하지 않는다.

## 회사 지식 이관·내보내기

저장소 루트에서 실행한다. 기본 dry-run은 실제 DB를 생성·수정하지 않는다. 기존 DB는 메모리에 복제해 schema·중복·길이를 검사한다.

```bash
uv run --locked python scripts/import_company_knowledge.py --source data/company-knowledge/documents.jsonl
uv run --locked python scripts/import_company_knowledge.py --source data/company-knowledge/documents.jsonl --apply --publish-imported
```

`--apply`만 쓰면 초안으로 이관한다. `--publish-imported`는 새로 이관한 자료만 게시하며 과거 사용 상태를 이어가기 위한 옵션이다. 재실행은 같은 원본 행을 건너뛰고 원본 ID의 내용이 달라지면 중단한다. 수정·중단된 기존 문서를 재게시하거나 덮어쓰지 않는다. 전체 이관은 한 트랜잭션으로 처리한다. 원본과 DB 백업·hash·매핑 manifest는 DB 옆 `backups/knowledge-*/`에 남긴다. 실제 이관 전 서비스 쓰기를 중지한다.

```bash
uv run --locked python scripts/export_company_knowledge.py --output tmp/evaluation-documents.jsonl
```

내보내기는 현재 게시 snapshot과 `.manifest.json`을 함께 만들며 기존 파일은 덮어쓰지 않는다. 평가에는 이 파일과 대응하는 평가 세트를 명시한다. 원본 JSONL은 새 로컬 환경의 최초 이관 자료로 유지하며 DB 편집 결과로 자동 갱신하지 않는다. DB 자체는 Git에 넣지 않는다.

## 실행·보존

FastAPI와 Next를 모두 loopback에 실행한다. nginx는 [기존 실행 안내](../deployment/README.md)를 따른다.

```bash
npm run dev
```

DB가 다른 버전이거나 저장 불가능하면 오류를 확인하고 무조건 삭제·재생성하지 않는다. SQLite 실행 중 백업은 SQLite backup API를 사용한다. 단일 DB 파일을 실행 중에 복사하면 WAL의 최신 변경을 놓칠 수 있다.

레거시 이관 도구는 기본 dry-run으로 읽기·검증만 한다. `--apply`를 명시했을 때만 백업 후 초안으로 복사한다. 안정적인 source ID·행 번호·행 해시로 반복 이관을 추적하고, 기존 행 내용이 바뀌면 중단한다. 추가 행만 있는 재이관은 이미 복사한 행을 건너뛴다. 원본 파일을 삭제하거나 잘라내지 않는다. 실제 명령 옵션은 `uv run --locked python scripts/import_registered_documents.py --help`로 확인한다.

미저장 입력은 브라우저 메모리에만 있다. 닫기·이동 시 확인하고 새로고침 시 유실될 수 있다. 채팅의 ‘문서로 등록’은 같은 편집기를 열며 질문을 자동 전송하거나 대화를 초기화하지 않는다.

공유 운영에는 서버 인증·문서 권한·감사 주체·CSRF 정책·레거시 쓰기 경로 보호가 추가로 필요하다. 메뉴 숨김이나 noindex는 권한 검사가 아니다. 실제 사내 자료·다중 사용자 운영은 이번 범위 밖이다.

## 현재 로컬 전환과 모델 제한

2026-10-14에 회사 지식 71건을 실제 로컬 DB에 게시 상태로 이관하고 원본 ID·본문·제목·순서·메타데이터와 정규화 프롬프트를 전수 대조했다. 게시가 사람 검수 승인을 뜻하지는 않는다. 새 clone에는 DB가 없으므로 위 명시적 이관을 수행해야 한다.

현재 로컬 `/ask`는 요구하는 분류 모델 파일이 없어 503이다. 분류기를 거치지 않는 독립 Ollama 호출에서는 같은 71건 snapshot의 입력이 66,652토큰으로 측정되어 현재 `num_ctx=40960`을 초과해 400으로 실패했다. 본문은 절단하지 않았고 모델 설정을 변경하지 않았다. 관리·공급 연결과 실제 답변 생성 성공을 구분해야 하며, 모델 준비·전체 문맥 처리 방식은 후속 결정이 필요하다. 상세 증거는 [전환 작업 기록](worklogs/2026-10-14-sqlite-documents.md)에 둔다.
