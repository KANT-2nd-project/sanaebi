# 원자료 확인과 재현

이 기록의 기준 작업 공간은 `/home/jake/workspace/projects/.sanaebi-rag-answer-evaluation-20261015`다. 아래 경로는 이 저장소 기준이다. 공개 다운로드 주소가 아니며, DB·모델은 Git 산출물에 포함하지 않는다. 서버 기본값은 변경하지 않았다.

## 저장한 자료

- `qrels-v2.json`, `new-confirmation.json`: 실행 전 동결 질문·필수 사실·원문 위치. 기존 v1은 기존 실험 폴더에 보존했다.
- `relevance-grades-*.json`: 설정·점수·승패를 가린 passage 관련도 AI 판정. 필수 사실은 판정자에게 제공했다.
- `answer-grades-*.json`: 질문별 A/B/C 및 반복·시도별 블라인드 AI 판정. A/B/C의 의미는 질문마다 다르다.
- `evidence/*-responses.jsonl`: 재시도 전 실패를 포함한 모든 실제 provider 응답·사용량·추정 비용.
- `evidence/*-inputs.json.gz`: 전달한 system/user prompt의 원본. `.gz`는 JSON을 손실 없이 압축한 것이다.
- `evidence/*-search.json.gz`: 질문별 전체 순위·점수, 최종 전달 근거·위치·예산과 측정값.
- `evidence/development-relevance-packet.json.gz`: 독립 관련도 판정자에게 전달한 공통 풀.
- `*-answers-summary.json`: 모드를 공개한 후 모든 시도를 결합한 집계. 좋은 응답만 고르지 않는다.
- `qrel-errata.md`: 동결 뒤 발견한 과잉 필수 기준. 원래 점수를 수정하지 않았다.
- `code-snapshot*.json`: 실험 당시의 미커밋 실행기 및 관련 코드 해시. 기록된 Git HEAD만으로 새 실행기를 복원할 수 있다는 뜻이 아니다.

압축 자료는 예를 들어 다음과 같이 읽는다. 모델·API 호출은 없다.

```bash
uv run --locked python -c 'import gzip,json; from pathlib import Path; p=Path("retrieval/reports/2026-10-15-rag-calibration/evidence/development-search.json.gz"); d=json.loads(gzip.decompress(p.read_bytes())); print(len(d["rows"]))'
```

## 로컬 자료와 검색 재현

기존 고정 snapshot·manifest는 `tmp/answer-evaluation/`, 로컬 Tiny 모델은 `tmp/tiny-model/`, 이번 실행의 원본은 `tmp/calibration/`에 있다. 개발용 PC의 준비 자료이며 새 checkout에서 자동으로 생기지 않는다. 원본 snapshot·model revision·retrieval spec·qrel SHA가 일치해야 같은 실험을 재현할 수 있다.

출력 폴더는 새 경로를 사용한다. 실행기는 기존 결과 덮어쓰기를 거절한다. 아래는 로컬 검색만 수행하며 실제 LLM을 호출하지 않는다.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked python -m retrieval.experiments.calibration_search \
  --qrels retrieval/reports/2026-10-15-rag-calibration/qrels-v2.json \
  --artifact-root tmp/answer-evaluation --model tmp/tiny-model \
  --output tmp/calibration/reproduce-development

uv run --locked python -m retrieval.experiments.calibration_summary \
  --search tmp/calibration/reproduce-development/search.json \
  --packet tmp/calibration/reproduce-development/relevance-packet.json \
  --grades retrieval/reports/2026-10-15-rag-calibration/relevance-grades-*.json \
  --output tmp/calibration/reproduce-comparison.csv
```

질문 벡터 캐시를 재사용하려면 같은 모델 revision·정규화·차원의 `query-vectors.npz`와 SHA sidecar가 필요하다. 모델·본문 임베딩은 이번 비교에서 재학습하지 않았다. 신규 확인 세트는 한 번 비교한 결과를 보존하며 다시 튜닝하는 개발 자료로 사용하지 않는다.

## 답변 실행·검증 경계

실제 답변 생성은 `calibration_prepare` → `calibration_answers --preflight` → `--execute` 순서였다. preflight는 API·원장·결과를 만들지 않는다. 실행에는 별도 출력 폴더와 전체 개발/확인 단계가 공유하는 원장을 사용한다. 기존 `execution.started.json`이 있는 실행은 자동 재개하지 않으며, 미확인 호출을 임의 재요청하지 않는다.

이번 원본 입력은 `tmp/calibration/development-inputs-execution.json`, `tmp/calibration/confirmation-inputs.json`; 원장은 `tmp/calibration/calls-ledger.json`이다. 실제 키 파일은 보고서에 복사하지 않는다. 단순 보고서 확인을 위해 `--execute`를 다시 실행할 필요가 없다.

기존 실행을 재집계하는 명령은 다음과 같다. API 호출은 없다.

```bash
uv run --locked python -m retrieval.experiments.calibration_answer_summary \
  --run-root tmp/calibration/development-answers \
  --grades retrieval/reports/2026-10-15-rag-calibration/answer-grades-dev-*.json \
  --ledger tmp/calibration/calls-ledger.json \
  --output tmp/calibration/reproduce-development-answers.json
```

형식 검사에는 기존 생성 파서를 사용했다. 원문의 일반 텍스트를 JSON으로 보정하지 않았다. 일시적 명시적 거절 또는 형식 오류만 1회 재시도하고, 내용상 누락은 재시도하지 않았다. 원장·원응답 저장 실패나 비용·완료 불명확은 중단한다.

최종 확인 재집계는 원 판정5 대신 재검토5를 지정한다. `answer-grades-confirmation-*.json` 전체 glob은 원판정과 정정판정을 중복으로 읽으므로 사용하지 않는다.

```bash
uv run --locked python -m retrieval.experiments.calibration_answer_summary \
  --run-root tmp/calibration/confirmation-answers \
  --grades retrieval/reports/2026-10-15-rag-calibration/answer-grades-confirmation-{1,2,3,4,5-rechecked}.json \
  --ledger tmp/calibration/calls-ledger.json \
  --output tmp/calibration/reproduce-confirmation-answers.json
```
