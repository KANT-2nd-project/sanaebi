# 문서 검색 RAG 실행과 초기화

RAG는 현재 게시된 SQLite 문서를 검색해 선택한 발췌를 기존 Luna 생성기에 전달한다. 기본값은 `SANAEBI_RETRIEVAL_MODE=full`이며 운영 자동 전환은 없다. 실제 LLM 품질과 운영 배포 검증은 로컬 연결 검증과 구분한다.

## 준비와 실행

선정 모델은 `exp-models/dragonkue-KoEn-E5-Tiny`, revision `292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9`다. 배포 준비 도구가 검증한 모델 파일과 `retrieval-model.json`을 같은 디렉터리에 둔다. API/worker는 로컬 전용 로딩을 하며 요청 중 다운로드하지 않는다.

```bash
export SANAEBI_DOCUMENT_DB=/absolute/path/documents.sqlite3
export SANAEBI_EMBEDDING_PATH=/absolute/path/koen-e5-tiny
export SANAEBI_RETRIEVAL_ROOT=/absolute/path/retrieval
uv run --locked python -m scripts.index_documents --once
uv run --locked python -m scripts.index_documents --status
# 별도 터미널/프로세스에서 계속 실행
uv run --locked python -m scripts.index_documents --watch
```

API에 같은 경로와 `SANAEBI_RETRIEVAL_MODE=rag`를 지정하고 기존 서버 명령으로 시작한다. worker와 API는 같은 spec의 색인을 사용해야 한다. `--status`는 모델을 로딩하지 않는다. 종료 코드는 준비0·미준비2·오류1이며, `--once`는 준비0·실패1이다. 원본 DB는 기존 [초기 구성](document-management.md) 절차로 준비하며 검색 명령이 원본을 생성하지 않는다.

검색의 초기 설정은 본문360토큰·중첩60, 전체 임베딩 입력512 이하, 후보10개·최대5개 근거, 전달 본문 합계8,000자·근거당2,000자다. 문자 예산은 생성 토큰 한도가 아니다. 같은 개정의 겹친 근거는 합치고 source span을 보존한다. schema/spec별 파생 DB를 `SANAEBI_RETRIEVAL_ROOT/schema-v1/<spec>/index.sqlite3`에 둔다.

## 요청·오류 계약

shadow 기본 모드에서는 세 분류 라벨 모두 검색 경로로 진행한다. gate의 비검색 라벨, assistant의 upstream 실패, 빈 snapshot은 기존 안내를 반환하며 검색·생성하지 않는다. 문서는 요청마다 한 번 읽고 생성 전에 DB 연결을 닫는다.

현재 유효 개정 하나라도 색인이 누락되면503이다. 부분 색인으로 정책이 없다고 답하지 않는다. query 접두사·특수 토큰 포함512를 넘으면422로 나누어 질문하도록 안내한다. 문서·모델·검색 장애는503, 생성 오류는502, 일일 예산은 기존429, 예상 밖 코드 오류는500으로 구분한다. 검색 실패 때 생성 예약은 소비하지 않는다. rag 장애를 full로 자동 전환하지 않는다.

`/health/ready`는 rag에서 현재 색인 준비도 검사한다. Tiny는 startup에서 준비하며 health가 외부 LLM을 호출하거나 색인을 만들지 않는다. full에서는 Tiny 없이 기존 서버를 실행할 수 있다. 원복은 full 지정 후 서버 재시작으로 명시한다.

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
