# 로컬 재현과 원자료

이 비교는 유료 답변 API를 호출하지 않는다. KoEn-E5-Tiny와 BGE 모델은 사전에 준비된 로컬 파일만 사용한다. 모델·SQLite·가상환경은 Git에 포함하지 않는다.

## 준비 조건

- `uv sync --locked`로 프로젝트 의존성을 준비한다.
- 기존 [답변 비교 준비 자료](../2026-10-15-rag-answer-comparison/README.md)와 동일한 71문서 snapshot 및 298청크 색인이 필요하다. 파일 경로는 실행 당시 로컬 자료 위치이며 공개 다운로드 링크가 아니다.
- Tiny revision은 `292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9`이다. 모델 디렉터리에 런타임의 `retrieval-model.json` 계약을 충족하는 파일이 있어야 한다.
- BGE는 `BAAI/bge-reranker-v2-m3` revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`를 사전에 준비한다. 실행 중 다운로드나 모델 대체를 하지 않는다.
- 동결 qrel과 원자료가 일치하지 않으면 실행기를 실패시키며, 기존 결과 폴더를 덮어쓰지 않는다. 새로 실행한 결과는 이 보고서의 당시 실행과 별도로 보관한다.

## 개발 검색 비교

아래 경로 변수는 각 환경의 실제 준비 위치로 바꾼다. `ARTIFACT_ROOT`는 `manifest.json`, `source/documents.sqlite3`, `retrieval/schema-v1/.../index.sqlite3`를 포함하는 격리된 준비 자료다. 원본 색인은 임시 복사본으로 읽는다.

```bash
uv run --locked python -m retrieval.experiments.optimization \
  --qrels retrieval/reports/2026-10-15-retrieval-v3/qrels-v3.json \
  --artifact-root "$ARTIFACT_ROOT" --model "$TINY_MODEL" \
  --reranker-model "$BGE_MODEL" --reranker-manifest "$BGE_MANIFEST" \
  --output tmp/retrieval-v3/reproduction-development \
  --execute-frozen
```

기본값은 10개 구성이다. `--query-cache`를 생략하면 원문 질문을 새로 임베딩한다. 캐시를 사용할 때는 질문 SHA·Tiny revision·정규화·차원·캐시 SHA를 검증한다. 캐시는 품질 비교에서만 사용하며 실제 warm 성능 측정에는 사용하지 않는다.

`search.json`은 최종 원문과 구간·청크 ID, 별도 코사인/재정렬 점수를 저장한다. `relevance-packet.json`은 설정·점수·순위가 없는 독립 검수 입력이다. BGE 점수는 관련 확률이 아니며 0.35는 코사인 기준에만 적용한다.

## CPU 2개 제한 측정

```bash
uv run --locked python -m retrieval.experiments.optimization_benchmark \
  --qrels retrieval/reports/2026-10-15-retrieval-v3/qrels-v3.json \
  --artifact-root "$ARTIFACT_ROOT" --model "$TINY_MODEL" \
  --variant C_unlimited --rounds 1 --concurrency 1 2 \
  --output tmp/retrieval-v3/reproduction-benchmark.json \
  --execute-frozen-benchmark
```

각 동시성은 별도 프로세스에서 실행한다. 한 라운드는 48문항이며 실제 표본 수·cold load·warm p95·최대 RSS를 결과에 기록한다. BGE 구성일 때만 모델·manifest 옵션을 추가한다. 제출부터 완료까지의 대기를 포함하며 동시에 실행 중인 요청 수를 넘는 인위적인 작업 대기열은 만들지 않는다.

## 확인 세트 사용

[신규 40문항](new-confirmation.json)은 개발 결과로 정한 후보와 C를 한 번 비교하기 위해 동결했다. 실행 시 `--variants 선정된구성 C_unlimited`로 제한한다. 이 세트의 결과를 본 뒤 같은 문항으로 반복 튜닝하지 않는다. 이번 보고서를 읽은 뒤 해당 세트를 다시 사용하면 미열람 확인 자료라고 표현할 수 없다.
