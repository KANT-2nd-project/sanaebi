# 문서 검색 RAG 실행과 초기화

RAG는 현재 게시된 SQLite 문서를 검색해 선택한 발췌를 기존 Luna 생성기에 전달한다. 코드 기본값은 `SANAEBI_RETRIEVAL_MODE=rag`이며 검색은 C로 고정한다. 이번 게시에서는 운영 설정·배포를 변경하지 않는다. 실제 LLM 품질과 운영 배포 검증은 로컬 연결 검증과 구분한다.

[KURE 전환 검증](../retrieval/reports/2026-10-16-kure-gate/README.md)은 채택 조건 미달로 보류했다. 아래 모델·색인·기본 복원 묶음은 계속 Tiny 전용이며 KURE 가중치를 이 경로에 대체하지 않는다.

## 준비와 실행

선정 모델은 `exp-models/dragonkue-KoEn-E5-Tiny`, revision `292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9`다. 배포 준비 도구가 검증한 모델 파일과 `retrieval-model.json`을 같은 디렉터리에 둔다. API/worker는 로컬 전용 로딩을 하며 요청 중 다운로드하지 않는다. 새 환경의 모델 준비는 다음 명령으로 수행한다. 이 명령은 최초에 고정 모델 파일을 다운로드하며, 서버 요청과는 별도다.

```bash
uv run --locked python scripts/deployment_embedding.py \
  --manifest deployment/retrieval-release.json --root artifacts/embeddings
```

명령이 출력한 검증된 모델 경로를 아래 `SANAEBI_EMBEDDING_PATH`에 지정한다. 문서 DB는 [최초 구성](document-management.md#새-환경의-db-최초-구성)으로 먼저 준비한다.

```bash
export SANAEBI_DOCUMENT_DB=/absolute/path/documents.sqlite3
export SANAEBI_EMBEDDING_PATH=/absolute/path/koen-e5-tiny
export SANAEBI_RETRIEVAL_ROOT=/absolute/path/retrieval
uv run --locked python -m scripts.index_documents --once
uv run --locked python -m scripts.index_documents --status
# 별도 터미널/프로세스에서 계속 실행
uv run --locked python -m scripts.index_documents --watch
```

API에 같은 경로를 지정하고(기본 `SANAEBI_RETRIEVAL_MODE=rag`) 기존 서버 명령으로 시작한다. worker와 API는 같은 spec의 색인을 사용해야 한다. `--status`는 모델을 로딩하지 않는다. 종료 코드는 준비0·미준비2·오류1이며, `--once`는 준비0·실패1이다. 원본 DB는 기존 [초기 구성](document-management.md) 절차로 준비하며 검색 명령이 원본을 생성하지 않는다.

분할은 본문360토큰·중첩60, 전체 임베딩 입력512 이하를 유지한다. C는 현재 유효 청크 전체의 벡터 점수에서0.35 이상을 선택한다. 후보·최종 근거 개수, 병합·근거당·총 본문 문자, 별도 전달 문맥 토큰 제한은 없다. 임베딩 입력512와 생성 제공자의 입력 한계는 유지하며 입력 초과 시 자동 절단·전체 문서 전환을 하지 않는다. 같은 개정의 겹친 근거는 합치고 source span을 보존한다. schema/spec별 파생 DB를 `SANAEBI_RETRIEVAL_ROOT/schema-v1/<spec>/index.sqlite3`에 둔다.

## 요청·오류 계약

shadow 기본 모드에서는 세 분류 라벨 모두 검색 경로로 진행한다. gate의 비검색 라벨, assistant의 upstream 실패, 빈 snapshot은 기존 안내를 반환하며 검색·생성하지 않는다. 문서는 요청마다 한 번 읽고 생성 전에 DB 연결을 닫는다.

현재 유효 개정 하나라도 색인이 누락되면503이다. 부분 색인으로 정책이 없다고 답하지 않는다. query 접두사·특수 토큰 포함512를 넘으면422로 나누어 질문하도록 안내한다. 문서·모델·검색 장애는503, 생성 오류는502, 일일 예산은 기존429, 예상 밖 코드 오류는500으로 구분한다. 검색 실패 때 생성 예약은 소비하지 않는다. 준비된 색인에서 점수0.35 이상 근거가 없으면 “관련 문서에서 답변에 필요한 근거를 찾지 못했습니다.” 안내로 종료하고 생성·예약하지 않는다. rag 장애를 full로 자동 전환하지 않는다.

`/health/ready`는 rag에서 현재 색인 준비도 검사한다. Tiny는 startup에서 준비하며 health가 외부 LLM을 호출하거나 색인을 만들지 않는다. full에서는 Tiny 없이 기존 서버를 실행할 수 있다. 수동 복구는 `export SANAEBI_RETRIEVAL_MODE=full` 지정 후 서버를 재시작한다. rag의 모델·색인이 준비되지 않은 상태를 정상 준비로 표시하지 않는다.

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

[단계별 비교](../retrieval/reports/2026-10-15-rag-quality-improvement/README.md)에서 제목 경계 문맥·인접 근거 확장·BM25 결합을 검증했다. 인접 확장은 기존18문항15→17건을 회복했지만 신규개발20문항은19건 동률로 사전 기준에 미달해 자동 채택하지 않았다. 서버·worker·자정 기본 묶음은 기존 vector spec과 벡터 검색을 유지한다. 이후 사용자 결정으로 C를 채택했다. BM25·인접 확장·과거 예산 후보는 실험 전용 구현으로 보관하며 서버에는 선택 분기를 두지 않는다. 벡터 spec은 동일해 이번 검색 변경만으로 색인을 재생성하지 않는다.

## 문서 변경 응답과 검색 반영

RAG 모드의 게시·사용 중단·전체 삭제·기본 복원 요청은 문서 저장 뒤 현재 게시 snapshot의 검색 준비를 확인하고 성공 응답한다. 초안 등록·수정은 검색 대상을 바꾸지 않으므로 임베딩하지 않는다. 미래 시행일의 게시본은 아직 검색 대상이 아니므로 현재 snapshot 확인까지만 수행하며, 시행일 도래 시 worker가 색인을 준비한다. `full`에서는 색인 준비를 요구하지 않는다.

API와 worker·관리 CLI는 같은 spec의 작업 단위 잠금을 사용한다. 잠금 획득 후 최신 snapshot을 읽으며, API는 게시 상태 변경부터 색인 확인까지 직렬화한다. 임베딩 중 문서 DB 쓰기 트랜잭션은 유지하지 않는다. worker는 3초 주기 대조로 누락·실패·시행일 도래를 복구하며 실행 시간 전체를 잠그지 않는다.

- 잠금을 10초 안에 얻지 못하면 이번 시도의 저장 전 `retrieval_sync_busy` 503과 `document_saved=false`를 반환한다. 이는 이전 요청까지 미저장이라는 뜻이 아니며, 이전 응답이 불확실하면 같은 키로 결과를 확인한다.
- 문서 저장 뒤 색인 반영이 실패하면 `retrieval_sync_failed` 503과 `document_saved=true`를 반환한다. 문서는 보존한다. 같은 요청 본문·Idempotency-Key로 재시도하면 문서 변경은 재생하고 현재 snapshot의 검색 준비를 다시 확인한다.
- 웹은 검색 반영까지 처리 중으로 표시하며 완료 전 성공 알림을 띄우지 않는다. 부분 실패는 저장 실패와 구별하고 같은 요청으로 수동 재시도한다.
- 전체 삭제는 빈 snapshot 확인으로 끝나며 임베딩·생성하지 않는다. 디스크에 남은 과거 벡터는 현재 개정 필터에서 제외된다.
- 기본 복원은 설정된 원본과 사전 생성 묶음을 쓰기 전에 검증하고, 새 revision에 벡터를 연결한다. 묶음 부재·불일치 시 원본을 초기화하지 않는다. 벡터 연결 실패 후에는 같은 요청으로 재시도하며 원본을 다시 초기화하거나 임베딩하지 않는다. 재시도 사이에 다른 문서가 변경됐고 그 색인이 미완료라면503을 유지하며 해당 변경 요청의 재시도나 worker 복구를 기다린다.

성공 응답은 확인한 시점의 게시 snapshot이 검색 가능함을 뜻한다. 이후 다른 사용자의 게시, 외부 CLI 변경, 시행일 도래까지 영구 보장하는 것은 아니다. 처리 중 새 질문은 미준비503을 받을 수 있고, 이미 시작한 질문은 확보한 snapshot으로 완료한다. 두 DB를 하나의 원자적 트랜잭션으로 취급하지 않는다.

구현·실제 Tiny 로컬 검증과 미확인 운영 범위는 [작업 기록](worklogs/2026-10-16-document-rag-sync.md)을 따른다.

## 실제 답변 비교 상태

[Full·RAG 비교](../retrieval/reports/2026-10-15-rag-answer-comparison/README.md)는 20문항을 준비했지만 5번째 실제 호출의 JSON 형식 오류로 중단했다. 두 쌍만 완료됐으며 재시도·프롬프트 변경은 하지 않았다. 이는 당시 full 기본값에서의 과거 실행이다. 현재 코드 기본값은 rag+C지만 검색 구현과 답변 품질·운영 승격은 별개다. 전체 비교 재개, 사람 검수, 실제2vCPU 및 컨테이너 운영 검증은 후속이다.

[후속 인자·문맥 비교와 C 채택](../retrieval/reports/2026-10-15-c-adoption/README.md)은 검색의 근거 누락 최소화를 우선한 사용자 결정이다. 12문항 답변 비교의 품질 동률과 비용 증가를 보존하며 사람 승인이나 운영 품질 검증으로 표현하지 않는다.

## 검색 구성의 평가 근거

현재 C는 이번 비교에서 대체안을 승인하지 못해 유지한 구성이다. 0.35는 관련 확률이 아닌 정규화 임베딩의 코사인 유사도이며, 모든 선택 근거가 질문에 직접 답한다는 보장은 없다. [v3 평가 보완·검색 최적화](../retrieval/reports/2026-10-15-retrieval-v3/README.md)에서 개발 세트의 문맥 축소 후보가 신규 확인 한 문항을 놓쳐 채택을 보류했다. 이 비교로 생성 답변 품질이나 운영 최적값을 승인하지 않았다.

벡터 입력·분할·schema와 활성 C 정책이 같으므로 기존 색인·자정 기본 벡터를 다시 만들 필요는 없다. 앱·신규 descriptor·Compose·준비 코드의 rag 기본값은 이전 게시분을 유지한다. 명시적 환경변수와 과거 full 릴리스·rollback 경로가 우선하며 이번 게시로 운영 설정을 전환하지 않는다.
