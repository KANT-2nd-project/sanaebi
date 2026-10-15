# 답변 출처 표시·문서 충실성 비교

2026-10-15 사용자 승인 계획에 따른 고정 비교다. `examples_answer_scope_v1`은 기존 기준, `examples_answer_scope_v2`는 답변 표시·판단 경계를 추가한 후보다. 모델·추론·출력 형식은 변경하지 않는다.

## 고정 입력과 판정

- `cases.json`: 신규 합성 12문항. 각 프로필 2회, 총 48회.
- 기존 `../../benchmarks/luna-reference-followup-v1/dev.json`: 이미 노출된 개발 12문항을 회귀용으로만 사용. 각 프로필 1회, 총 24회. 원본 71문서 코퍼스·루브릭은 보존한다.
- `holdout.json`: 프롬프트 예시에 없는 표현 변경 4문항. 후보 2회, 총 8회. 작성 AI가 알고 있는 소규모 표현 변형이며 독립 블라인드 holdout이나 정책 일반화 검증이 아니다.
- 별도 임시 SQLite·실제 생성 API 2회. 분류만 고정 대역을 사용하며 실제 게시 문서의 읽기 전용 snapshot을 복제한다.
- `criteria.json`: 실행 전에 고정한 기본값 승격 기준. 총 82회 계획, 최대 90회·보수적 추정 비용 5달러. 자동 재시도·응답 보정·실험 결과를 본 후 프롬프트 수정은 하지 않는다.

모든 신규 응답은 필수 주장·금지 주장을 의미로 검토한다. 답변의 내부 문서 ID·개정 번호 노출, 출처 생성, 요청하지 않은 타당성 판단을 검사한다. 정보 부족·조건·충돌·명시적 검토 질문에서는 해당 한계나 의견이 질문에 필요한지 구분한다. 기존 문항은 required_claims를 단위로 대조해 v1에서 안내한 필수 내용을 v2가 새로 누락하면 승격하지 않는다. 형식 성공은 품질 성공이 아니다.

## 실행

저장소 루트에서 프로젝트 환경의 Python을 사용한다. API 키는 출력하거나 기록하지 않는다.

```bash
PYTHONPATH=. python generation_evaluation/experiments/answer-grounding-20261015/run.py --env-file /path/to/private.env --output tmp/answer-grounding/runs
```

API 재현은 같은 원장과 별도 비공개 snapshot을 사용한다. 게시용 `api_check.py`는 실제 실행한 임시 스크립트의 경로를 인자로 바꿔 정리한 것으로, 정리 후 추가 모델 호출은 하지 않았다.

```bash
PYTHONPATH=. python generation_evaluation/experiments/answer-grounding-20261015/api_check.py --env-file /path/to/private.env --snapshot /path/to/private-snapshot.json --output tmp/answer-grounding/runs
```

입력·프롬프트·설정·lock 해시가 달라지면 같은 출력 디렉터리 재개를 거절한다. 완료·실패 기록은 재호출하지 않고, 원장에 예약만 남은 요청도 중복 실행하지 않는다. 실행 기록과 원장은 tmp에 보존한다. 비용은 저장소의 보수적 추정 함수이며 실제 청구액이 아니다.

[평가 결과](../../reports/2026-10-15-answer-grounding/README.md)에서 채택 여부·문항별 판정·한계를 확인한다.
