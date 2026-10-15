# v3 채택 API 확인

[채택 일지](../../../docs/worklogs/2026-10-15-adopt-grounding-v3.md)의 실행 도구다. 저장소 기본 설정을 그대로 읽고 v3임을 검사한다. 설정 로더를 대체하지 않으며 임시 SQLite·분류 대역·실제 생성 모델로 `/ask`와 `/assistant`를 각1회 확인한다. SDK 재시도는0이다.

실행 당시 snapshot은 공개 `data/company-knowledge/documents.jsonl` 전체71개를 JSON 배열로 변환하고 ieum-068의 document만 `../answer-grounding-20261015/cases.json`의 G02 documents[0].document로 교체했다. 실제 DB를 읽거나 수정하지 않았다. 비공개 env는 커밋하지 않는다.

```bash
PYTHONPATH=. uv run --locked python generation_evaluation/experiments/adopt-grounding-v3-20261015/api_check.py \
  --env-file /path/to/private.env --snapshot /path/to/synthetic-snapshot.json \
  --output tmp/adopt-grounding-v3/api
```

실행 전 출력 폴더를 생성한다. 새 실행은 별도 출력 경로를 사용한다. 이미 저장한 API 결과를 덮어쓰거나 실패를 자동 재호출하지 않는다. 기존 예산 원장의 최대90회·추정5달러 상한을 사용하지만 이 도구의 호출 목록은2개로 고정돼 있다.
