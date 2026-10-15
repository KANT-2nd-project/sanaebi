# 문서 검색 RAG 실행과 초기화

RAG는 현재 게시된 SQLite 문서를 검색해 선택한 발췌를 기존 Luna 생성기에 전달한다. 코드 기본값은 `SANAEBI_RETRIEVAL_MODE=rag`이며 검색은 KURE 상위20·질문 게이트로 고정한다. 실제 LLM 품질과 운영 배포 검증은 로컬 연결 검증과 구분하며 [준비 개선 기록](worklogs/2026-10-16-local-rag-startup.md)에 확인 결과를 남긴다.

[KURE 채택·연결](../retrieval/reports/2026-10-16-kure-adoption/README.md)은 근거 유지·전달량 감소에 따른 사용자 결정을 반영한다. 아래 모델·색인·기본 복원은 새 KURE spec으로 준비한다. 기존 Tiny 자료는 덮어쓰지 않는다.

## 준비와 실행

의존성 설치와 분류 저장본·`.env`의 `OPENAI_API_KEY` 준비 후 저장소 루트에서 실행한다.

```bash
npm run setup:local -- --init-documents
npm run check:local
npm run dev
```

- setup은 고정 KURE와 분할 tokenizer를 검증·준비하고 기본 원본의 벡터 묶음, 현재 게시 문서의 검색 색인을 구성한다. 준비된 자료는 재사용하며 변경된 입력만 임베딩한다. 최초 준비는 모델 다운로드·CPU 계산 시간이 필요하다.
- DB가 없을 때만 `--init-documents`로 기본 문서를 등록한다. 기존 DB는 비어 있어도 자동 등록·초기화하지 않는다. 의도적으로 전체 삭제한 문서는 웹의 기본 복원으로 되돌린다.
- dev는 읽기 전용 사전 검사 후 API·웹·3초 주기 worker를 함께 실행한다. 준비 실패 시 setup 안내로 종료하며, 준비나 reset을 자동 실행하지 않는다. Ctrl+C 또는 자식 실패 시 이번 실행의 프로세스 그룹을 정리한다. 명시적 `full`은 worker 없이 실행한다.
- setup·check·API·worker는 같은 `.env`를 읽고 이미 셸에 지정된 환경변수가 우선한다. `SANAEBI_DOCUMENT_DB`는 기본 `var/documents.sqlite3`, 검색 색인은 `SANAEBI_RETRIEVAL_ROOT`(기본 `var/retrieval`)다. 설정 변경 후 setup을 실행하고 dev를 재시작한다.
- 기본 묶음 경로는 현재 원본 SHA와 vector spec으로 `artifacts/retrieval-baselines/schema-v1/<spec>/<source SHA>/baseline.sqlite3`를 계산한다. 명시적 `SANAEBI_RETRIEVAL_BASELINE`이 있으면 그것만 사용하며 누락·불일치를 다른 묶음으로 대체하지 않는다. 사용자 지정 경로는 별도 준비 명령으로 먼저 준비한다.
- check는 모델·분류 자료·키 존재·문서 DB·색인·복원 준비를 검사하며 파일 생성이나 모델 추론을 하지 않는다. 기계 판독은 `uv run --locked --env-file .env python -m scripts.local_runtime --check --json`을 사용한다. 비밀값과 문서 본문은 출력하지 않는다.

선정 모델은 `nlpai-lab/KURE-v1`, revision `8b418a58414668e75532ed045c22d9ca018ae2b2`다. CPU FP32·CLS pooling·L2 정규화·1024차원·접두사 없음이며 `splitter/`에는 고정 Tiny tokenizer만 둔다. Tiny 가중치는 요구하지 않는다. 요청·worker에서 모델을 다운로드하지 않는다.

기존 개별 관리 CLI는 유지한다. 같은 `.env`를 사용하며 dev가 worker를 관리하는 동안 중복 watch를 시작하지 않는다.

```bash
uv run --locked --env-file .env python -m scripts.index_documents --once
uv run --locked --env-file .env python -m scripts.index_documents --status
```

`--status`는 모델을 로딩하지 않는다. 종료 코드는 준비0·미준비2·오류1이다. `--once`는 준비0·실패1이며 문서 원본은 생성하지 않는다. 모델만 준비하는 기존 `scripts/deployment_embedding.py`와 기본 묶음 준비 CLI는 배포·사용자 지정 경로에 계속 사용할 수 있다.

분할은 고정 Tiny tokenizer로 본문360토큰·중첩60과 기존 원문 경계를 유지한다. 임베딩은 E5 접두사를 제거한 제목·절·본문을 KURE로 계산한다. 질문 입력은512토큰, 문서는8192토큰을 명시적으로 검사한다. 질문 최고 코사인이0.42882221937179565 이상이면 상위20청크를 선택하며 개별 청크 점수 하한은 없다. 같은 개정의 겹친 원문은 병합한다. 상위20은 병합 전 수량이며 추가 문자·전달 토큰 제한은 없다. 생성 제공자 한계는 유지하고 초과 시 자동 절단·full 전환하지 않는다. schema/spec별 파생 DB를 `SANAEBI_RETRIEVAL_ROOT/schema-v1/<spec>/index.sqlite3`에 둔다.

## 요청·오류 계약

advisory 기본 모드와 명시적 shadow에서는 세 분류 라벨 모두 검색 경로로 진행한다. gate의 비검색 라벨과 assistant의 upstream 실패는 기존 안내를 반환하며 검색·생성하지 않는다. 정상 빈 snapshot은 근거 상태를 명시해 제한된 생성으로 전달한다. 문서는 요청마다 한 번 읽고 생성 전에 DB 연결을 닫는다.

현재 유효 개정 하나라도 색인이 누락되면503이다. 부분 색인으로 정책이 없다고 답하지 않는다. KURE tokenizer의 특수 토큰 포함512를 넘으면422로 나누어 질문하도록 안내한다. 문서·모델·검색 장애는503, 생성 오류는502, 일일 예산은 기존429, 예상 밖 코드 오류는500으로 구분한다. 검색 실패 때 생성 예약은 소비하지 않는다. 준비된 색인에서 질문 최고 코사인이0.42882221937179565 미만이면 근거를 선택하지 않고 검색 결과 없음 상태를 생성기에 전달한다. 인사·서비스 소개는 가능하지만 회사 정책·창구·금액을 근거 없이 보충하지 않는다. 이 경로도 생성 예산을 예약한다. rag 장애를 full로 자동 전환하지 않는다.

`/health/ready`는 rag에서 현재 색인과 기본 복원 묶음의 원본·spec 유효성을 검사한다. 빈 DB도 유효한 복원 묶음이 있으면 정상이며, 묶음 누락·불일치는503이다. KURE는 startup에서 준비하며 health가 외부 LLM을 호출하거나 색인을 만들지 않는다. full에서는 임베딩 모델 없이 기존 서버를 실행할 수 있다. 수동 복구는 `export SANAEBI_RETRIEVAL_MODE=full` 지정 후 서버를 재시작한다. rag의 모델·색인이 준비되지 않은 상태를 정상 준비로 표시하지 않는다.

## 자정 초기화용 벡터

기본 JSONL은 실제 host에 보존된 초기화 원본이다. 새 이미지에 다른 JSONL이 있어도 자동 교체하지 않는다. 이 원본 전체의 기본 벡터 묶음을 배포 준비 단계에서 생성하고 읽기 전용으로 보존한다.

```bash
uv run --locked python -m scripts.prepare_retrieval_baseline \
  --source /absolute/path/documents.jsonl \
  --output-root /absolute/path/retrieval-baselines
```

출력의 bundle 경로를 `SANAEBI_RETRIEVAL_BASELINE`, 같은 원본 경로를 `SANAEBI_RETRIEVAL_SOURCE`로 지정한다. 기본 묶음은 직접 검색하지 않으며 현재 document/revision mapping에만 벡터를 재사용한다. 모델·분할/spec·저장 schema·기본 원본이 달라지면 해당 묶음을 새로 준비한다.

자정에는 host helper가 묶음 확인 → worker 정지 → 기존 문서 reset → 새 revision에 기본 벡터 연결 → 현재 준비 확인 → worker 재개를 수행한다. 이 경로에는 모델 계산이 없다. 두 DB 사이 잠깐503은 가능하므로 무중단으로 설명하지 않는다.

연결만 실패했을 때 **문서를 다시 reset하지 않는다.** 운영에서는 다음 복구 helper를 사용한다.

```bash
sudo /usr/bin/python3 /usr/local/libexec/sanaebi/scripts/production_maintenance.py restore-retrieval
```

로컬에서 worker를 중지한 경우 `uv run --locked python -m scripts.index_documents --restore-baseline`을 사용할 수 있다. 원본 쓰기·모델 추론 없이 현재 내용과 같은 기본 벡터를 연결한다. 수정된 다른 문서가 남으면 worker의 정상 갱신이 필요하다. 운영 helper의 설치·릴리스·복구는 [배포 안내](../deployment/README.md)를 따른다.

원본·예산 DB는 계속 백업한다. 파생 색인은 재생성 가능하지만 이전 schema/spec와 기본 묶음은 rollback 기간 동안 보존한다. 임의로 운영 색인 파일을 과거 파일로 덮어쓰지 않는다. 명시적 원본 trace 외에는 검색 로그에 질문·원문을 추가하지 않는다.

## 검색 개선 후보와 현재 구성

[단계별 비교](../retrieval/reports/2026-10-15-rag-quality-improvement/README.md)에서 제목 경계 문맥·인접 근거 확장·BM25 결합을 검증했다. 인접 확장은 기존18문항15→17건을 회복했지만 신규개발20문항은19건 동률로 사전 기준에 미달해 자동 채택하지 않았다. 당시 서버·worker·자정 기본 묶음은 기존 vector spec과 벡터 검색을 유지했고, 이후 사용자 결정으로 C를 채택했다. 현재는 KURE 채택 후 별도 spec을 사용한다. BM25·인접 확장·과거 예산 후보는 실험 전용 구현으로 보관하며 서버에는 선택 분기를 두지 않는다. 당시 검색 정책만 바꿀 때는 벡터를 재생성하지 않았다. 이번 KURE 모델 변경에는 별도 색인·기본 벡터가 필요하다.

## 문서 변경 응답과 검색 반영

RAG 모드의 게시·사용 중단·전체 삭제·기본 복원 요청은 문서 저장 뒤 현재 게시 snapshot의 검색 준비를 확인하고 성공 응답한다. 초안 등록·수정은 검색 대상을 바꾸지 않으므로 임베딩하지 않는다. 미래 시행일의 게시본은 아직 검색 대상이 아니므로 현재 snapshot 확인까지만 수행하며, 시행일 도래 시 worker가 색인을 준비한다. `full`에서는 색인 준비를 요구하지 않는다.

API와 worker·관리 CLI는 같은 spec의 작업 단위 잠금을 사용한다. 잠금 획득 후 최신 snapshot을 읽으며, API는 게시 상태 변경부터 색인 확인까지 직렬화한다. 임베딩 중 문서 DB 쓰기 트랜잭션은 유지하지 않는다. worker는 3초 주기 대조로 누락·실패·시행일 도래를 복구하며 실행 시간 전체를 잠그지 않는다.

- 잠금을 10초 안에 얻지 못하면 이번 시도의 저장 전 `retrieval_sync_busy` 503과 `document_saved=false`를 반환한다. 이는 이전 요청까지 미저장이라는 뜻이 아니며, 이전 응답이 불확실하면 같은 키로 결과를 확인한다.
- 문서 저장 뒤 색인 반영이 실패하면 `retrieval_sync_failed` 503과 `document_saved=true`를 반환한다. 문서는 보존한다. 같은 요청 본문·Idempotency-Key로 재시도하면 문서 변경은 재생하고 현재 snapshot의 검색 준비를 다시 확인한다.
- 웹은 검색 반영까지 처리 중으로 표시하며 완료 전 성공 알림을 띄우지 않는다. 부분 실패는 저장 실패와 구별하고 같은 요청으로 수동 재시도한다.
- 전체 삭제 자체는 문서 관리 작업이며 생성하지 않는다. 이후 질문은 빈 snapshot 상태로 제한된 생성이 가능하고 임베딩은 수행하지 않는다. 디스크에 남은 과거 벡터는 현재 개정 필터에서 제외된다.
- 기본 복원은 설정된 원본과 사전 생성 묶음을 쓰기 전에 검증하고, 새 revision에 벡터를 연결한다. 묶음 부재·불일치 시 원본을 초기화하지 않는다. 벡터 연결 실패 후에는 같은 요청으로 재시도하며 원본을 다시 초기화하거나 임베딩하지 않는다. 재시도 사이에 다른 문서가 변경됐고 그 색인이 미완료라면503을 유지하며 해당 변경 요청의 재시도나 worker 복구를 기다린다.

성공 응답은 확인한 시점의 게시 snapshot이 검색 가능함을 뜻한다. 이후 다른 사용자의 게시, 외부 CLI 변경, 시행일 도래까지 영구 보장하는 것은 아니다. 처리 중 새 질문은 미준비503을 받을 수 있고, 이미 시작한 질문은 확보한 snapshot으로 완료한다. 두 DB를 하나의 원자적 트랜잭션으로 취급하지 않는다.

구현·실제 Tiny 로컬 검증과 미확인 운영 범위는 [작업 기록](worklogs/2026-10-16-document-rag-sync.md)을 따른다.

## 실제 답변 비교 상태

[Full·RAG 비교](../retrieval/reports/2026-10-15-rag-answer-comparison/README.md)는 20문항을 준비했지만 5번째 실제 호출의 JSON 형식 오류로 중단했다. 두 쌍만 완료됐으며 재시도·프롬프트 변경은 하지 않았다. 이는 당시 full 기본값에서의 과거 실행이다. 현재 코드 기본값은 rag+KURE지만 검색 구현과 답변 품질·운영 승격은 별개다. 전체 비교 재개, 사람 검수, 실제2vCPU 및 컨테이너 운영 검증은 후속이다.

[후속 인자·문맥 비교와 C 채택](../retrieval/reports/2026-10-15-c-adoption/README.md)은 검색의 근거 누락 최소화를 우선한 사용자 결정이다. 12문항 답변 비교의 품질 동률과 비용 증가를 보존하며 사람 승인이나 운영 품질 검증으로 표현하지 않는다.

## 검색 구성의 평가 근거

과거 C 유지와 KURE 보류 판단은 당시 보고서에 보존한다. 이후 사용자가 근거 유지·전달량 감소를 근거로 KURE를 채택했다. 코사인은 정답 존재 확률이 아니며 회사 맥락의 무관 질문도 통과할 수 있다. [채택 근거와 한계](../retrieval/reports/2026-10-16-kure-adoption/README.md)를 따른다. 실제 생성 답변 품질·사람 검수·운영 승격은 별도다.

KURE는 벡터 차원·모델·접두사가 달라 새 spec의 색인·자정 기본 벡터를 준비한다. 분할 tokenizer와360/60 원문 구간은 유지하며 과거 Tiny 자료는 보존한다. 앱·신규 descriptor·Compose·준비 코드의 rag 기본값은 이전 게시분을 유지한다. 명시적 환경변수와 과거 full 릴리스·rollback 경로가 우선하며 이번 게시로 운영 설정을 전환하지 않는다.

## 검색 실행과 색인 책임

`RetrievalService`는 질문 검색, `RetrievalIndexer`는 청크 생성·벡터 재사용·색인 쓰기를 담당한다. 게시 동기화는 indexer를 주입받는다. 기존 관리 명령의 `RetrievalService.reconcile()`은 indexer로 위임하는 호환 입구다. baseline 벡터 읽기는 별도 저장소, 점수 선택·원문 병합은 순수 함수로 분리한다.

질문 검색은 현재 snapshot의 청크를 한 번 읽으면서 준비 상태와 무결성을 검사한 후 질의를 임베딩한다. readiness는 별도 검사를 유지한다. 캐시를 추가하거나 손상 검사를 생략하지 않는다.

청크 크기·overlap은 `RetrievalSpec`에서 실제 분할기로 전달된다. 검색의 `SearchPolicy`는 벡터 spec과 분리된 불변 값이다. KURE 청크 설정 변경이 Tiny 정책으로 바뀌지 않으며, 정책과 맞지 않는 필드 조합은 거부한다. 기존 기본 Tiny/KURE의 식별자는 유지한다. 청크 설정 변경은 새 spec ID와 새 색인을 요구하며, 기존 색인을 자동 변환하지 않는다. 정책 ID는 실제 선택 정책의 식별자다.

## 근거 없는 요청과 문맥 보충 검증 (2026-10-16)

RAG 기본 프로필은 `examples_answer_scope_v5_rag_service_v1`이다. full·독립 CLI 기본 v5는 유지한다. `SANAEBI_RAG_PROMPT_PROFILE=examples_answer_scope_v5` 지정 후 사용자가 재시작하면 빈 자료·검색 0건의 고정 안내로 원복한다. 잘못된 프로필은 시작 시 거부한다. `evidence_state`는 `available`, `no_matches`, `no_published_documents`를 구분한다. 정상 빈 결과는 장애를 숨기는 수단이 아니다.

사용자의 후속 채택 결정으로 서버 RAG는 문맥 보충을 기본 활성화한다. `SANAEBI_RAG_EXPAND_CONTEXT=0` 지정 후 재시작하면 확장 없는 검색으로 원복한다. 비교용 `RetrievalService` 직접 생성자는 False 기본값을 보존한다. 최대 3문서·4000자 이하 전체 본문·추가 6000자·긴 문서 앞뒤 1청크 정책이며 벡터 spec은 그대로이고 검색 정책 식별자만 달라진다. [8회 비교 보고서](../retrieval/reports/2026-10-16-rag-context-empty/README.md)에 따라 초기 판정은 근거 없는 요청 채택·문맥 보충 보류였고, 이후 사용자가 관측 개선을 우선하여 문맥 보충도 채택했다. 원문의 신고 경로 선택/필수 관계는 미해결이다. 결합 경로는 mock으로 검증했으며 추가 유료 호출은 하지 않았다. 배포 상태는 [게시 기록](worklogs/2026-10-16-rag-publication.md)을 따른다.
