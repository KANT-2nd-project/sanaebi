# 재현과 원자료

별도 로컬 작업 공간 `/home/jake/workspace/projects/.sanaebi-rag-answer-evaluation-20261015` 기준이다. 기준 HEAD는 `2dbe3f7`이고 새 실험 코드·보고서는 미커밋 상태다. 모델·DB·실제 환경 파일은 보고서에 넣지 않는다.

## 검색만 재현

기존 `tmp/answer-evaluation`의 고정 snapshot·색인, `tmp/tiny-model`의 pinned Tiny와 기존 질문 벡터가 필요하다. 새 출력 폴더를 사용한다.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked python -m retrieval.experiments.calibration_search \
  --qrels retrieval/reports/2026-10-15-rag-calibration/qrels-v2.json \
  --artifact-root tmp/answer-evaluation --model tmp/tiny-model \
  --query-cache tmp/calibration/development-search-validated/query-vectors.npz \
  --context-limits --output tmp/context-limit-reproduce/search
```

실제 모델 입력을 새로 분할·임베딩하지 않고 기존 벡터로 점수·순위를 재계산한다. Tiny tokenizer로 전체 전달 문맥을 세므로512 초과 경고가 나올 수 있지만 그 긴 문맥을 임베딩 모델에 넣지는 않는다. 검색 실행기의 상수 patch는 단일 프로세스 실험 전용이며 동시 서버 요청 안에서 호출하면 안 된다.

원자료는 `evidence/search.json.gz`에 JSON 그대로 압축했다. Python의 `gzip.decompress`와 `json.loads`로 읽을 수 있다. `tmp/context-limit-comparison/search/`에는 검색 원본·벡터 캐시가 유지된다.

## 답변 입력과 중단 기록

입력 준비는 다음과 같았다. 준비 명령 자체는 API를 호출하지 않는다.

```bash
uv run --locked python -m retrieval.experiments.context_limit_prepare \
  --qrels retrieval/reports/2026-10-15-rag-calibration/qrels-v2.json \
  --selection retrieval/reports/2026-10-15-context-limits/selection.json \
  --search tmp/context-limit-reproduce/search/search.json \
  --output tmp/context-limit-reproduce/inputs.json
```

실제 실행은 Luna·v5·xhigh·출력16,384·기존 JSON 파서로 수행했다. 원본 입력은 `tmp/context-limit-comparison/inputs.json`, 원장은 `tmp/context-limit-comparison/ledger.json`, 실행 기록은 `tmp/context-limit-comparison/answers/`에 있다. 입력 복사본은 `evidence/inputs.json.gz`다. 키 파일은 복사하지 않았다.

quick_context는12문항·3구성·1회, 별도 신규 원장, 최대72호출을 강제한다. 과거448슬롯 실험 원장을 공유하지 않는다. 실행 표시가 남은 이번 중단 폴더는 자동 재개할 수 없다. 파일 삭제·새 원장 발급으로 재시도 상한을 우회하지 않는다. 보고서 확인을 위해 실제 호출 명령을 다시 실행할 필요가 없다.

사전 비용 예약 추정은33정상호출 약$0.7427, 모든 재시도 포함 약$1.4855였다. 이는 실제 청구나 완주 비용이 아니며 실제 실행은 첫 요청의 두 거절에서 멈췄다.

## 개인 API 키 교체 후 후속 실행

사용자 승인으로 새 원장·별도 디렉터리에서36슬롯을 완료했다. 기존 실패 원자료를 보존했다. 실행·비용·블라인드 판정·현재 검증은 [재개 후 결과](resumed-results.md)를 따른다.
