# 사용자용 표현 v4 초기 비교

v3/v4를 고정9문항에서 각1회 비교한다. 판정 기준은 cases.json에 사전 저장하며 모델 입력에는 넣지 않는다. 실행 결과는 [중간 후보 보고서](../../reports/2026-10-15-user-facing-v4/README.md)에 보존한다. 이후 v5 추가 범위 평가와 구분한다.

```bash
PYTHONPATH=. uv run --locked --env-file .env python \
  generation_evaluation/experiments/user-facing-v4-20261015/run.py \
  --snapshot tmp/user-facing-v4-20261015/snapshot.json \
  --output tmp/user-facing-v4-20261015/comparison
```

위 출력은 이미 존재하며 덮어쓰기·자동재개를 허용하지 않는다. 재실행은 새 출력과 당시 코드·자료를 사용해야 한다. 최대18회·순차 호출·timeout180초·자동재시도 없음이며 시작/완료 이벤트를 남긴다. v4는 사고 대응 조건 왜곡이 관찰돼 기본 채택하지 않았다.
