# 문서 변경과 RAG 색인 동기화 검증

이 폴더는 문서 API가 검색 색인 준비를 기다린 뒤 성공 응답을 반환하는지 확인하는 로컬 통합 검증 기록이다. 운영 서비스나 실제 생성 모델 호출은 사용하지 않는다.

## 실행

KoEn-E5-Tiny의 고정 revision 파일이 이미 로컬에 있어야 한다. 아래 경로는 예시이며, `retrieval-model.json`과 모델 파일이 들어 있는 로컬 디렉터리를 지정한다.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked python \
  retrieval/reports/2026-10-16-document-sync/run_smoke.py \
  --embedding-path /path/to/local/koen-e5-tiny
```

실행기는 기본 문서 원본으로 임시 SQLite baseline bundle을 준비하고, 임시 문서 DB와 검색 DB로 API lifespan을 시작한다. 준비 bundle의 벡터 계산 시간과 API 요청 중 임베딩 횟수는 별도 기록한다. 임시 DB·bundle은 종료 시 삭제되며, 결과 JSON에는 비밀값·문서 원문을 저장하지 않는다.

## 시나리오

실제 Tiny 검색 모델과 모의 분류기·답변기를 사용해 다음을 검사한다.

1. 초안 등록은 문서 임베딩을 실행하지 않는다.
2. 게시 중 한 번의 임베딩 실패를 주입하면 API가 503을 반환하고, 게시된 문서는 보존된다.
3. 동일한 본문·멱등성 키로 다시 게시하면 새 revision을 만들지 않고 색인을 복구하며, 요청 직후 `/ask`에서 새 근거를 검색한다.
4. 초안을 수정할 때는 임베딩하지 않고, 재게시 후 새 근거가 검색되며 이전 근거는 전달되지 않는다.
5. 철회·전체 삭제 뒤 오래된 청크는 검색 근거로 전달되지 않는다.
6. 기본 문서 복원은 사전 준비한 벡터를 연결해 완료하고, 복원 요청에서 문서 임베딩 호출이 0회이며 요청 직후 기본 문서를 검색한다.

## 결과

검증 실행 결과는 [actual-tiny-smoke.json](evidence/actual-tiny-smoke.json)에 기록한다. `baseline_bundle_preparation`은 원본 묶음을 만드는 일회성 로컬 준비 작업이며, `baseline_restore.document_encode_calls`는 복원 요청 자체에서 모델을 호출했는지 나타낸다.

현재 실행에서는 초안 등록과 수정에서 문서 벡터 계산 0회, 게시 임베딩 오류 시 503과 저장 유지, 같은 키 재시도 뒤 revision 1개 유지, 재게시 직후 새 본문 검색, 철회·전체 삭제 뒤 예전 근거 미전달을 확인했다. 기본 복원은 71개 게시 revision을 모두 준비했고, 복원 요청의 문서 임베딩 계산은 0회였다. 복원 직후 실제 Tiny 검색도 모의 답변기로 확인했다.

2026-10-16 최종 실행에서 개발 환경 지연은 게시 오류 주입 응답 2.92 ms, 같은 요청 재시도 게시 31.63 ms(문서 벡터 1개 계산 포함), 수정본 재게시 28.27 ms(벡터 1개 계산 포함), 기본 복원 78.88 ms(71개 revision 연결)였다. baseline 묶음 준비는 298개 벡터를 계산하는 데 41.16초 걸렸으며 이는 게시 요청 지연에 포함되지 않는다. 모델 첫 로딩은 약 2.99초였다.

측정은 WSL2 개발 환경에서 CPU affinity 24개로 수행했으므로 실제 2 vCPU 운영 서버의 성능을 예측하지 않는다. 보고서의 코드 파일 SHA와 Git HEAD를 함께 확인해야 하며, 검증 당시 구현 변경은 미커밋 작업 트리에 있었다. 운영 서비스 접속, 실제 LLM 요청, 운영 worker·백업 실행은 검증하지 않았다.

최종 실행의 구현 파일 SHA를 현재 소스와 대조해 일치함을 확인했다. [전체 검사 요약](evidence/verification.json)과 [모의 API 브라우저17개 확인](evidence/browser-check.json)을 함께 보되, 브라우저 UI 검사와 실제 Tiny HTTP 검증은 별도 실행이다.
