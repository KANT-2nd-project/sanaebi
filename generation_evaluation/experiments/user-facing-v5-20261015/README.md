# 사용자용 표현·범위 안내 v5 검증

먼저 v3/v4를 9문항 각1회 비교한 후 사용자의 세그먼트 트리 범위 안내 요청과 독립 검토를 반영한 별도13문항 검증이다. 이전18응답과 최종13응답을 합산 정확도로 보고하지 않는다. cases.json은 v5 실호출 전에 고정하며 판정 기준은 모델 입력에 넣지 않는다.

현재 게시 snapshot을 읽기 전용으로 한 번 고정했다. U11만 합성 사내 기술 문서1개를 추가한다. 실제 DB에는 추가하지 않는다. 같은 질문 U10/U11에 문서 유무가 미치는 범위 판단을 확인한다. snapshot 원본은 tmp/에 보존하고 manifest에 해시·fingerprint를 남긴다.

```bash
PYTHONPATH=. uv run --locked --env-file .env python \
  generation_evaluation/experiments/user-facing-v5-20261015/run.py \
  --snapshot tmp/user-facing-v4-20261015/snapshot.json \
  --output tmp/user-facing-v5-20261015/comparison
```

최대13회, 각 요청180초, 순차 호출, 자동 재시도·재개 없음. 출력 경로가 존재하면 거부한다. 시작/완료 이벤트와 원응답·상태·프로필·문서/프롬프트 해시·사용량·지연·비용 추정치를 보존한다. 중단된 실행은 자동 재실행하지 않는다. 재현할 때는 기록한 프롬프트/코드 버전과 snapshot을 사용한다.

HTTP·분류기·브라우저가 아닌 공통 generation/run_case 검증이다. 서비스 연결은 mock 회귀로 별도 검사한다. 소수 문항·각1회와 AI 판정의 한계를 명시하며 사람 검수·전체 품질 승인을 주장하지 않는다.
