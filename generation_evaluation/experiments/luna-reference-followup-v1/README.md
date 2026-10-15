# Luna reference follow-up v1

2026-10-15 사용자 승인 계획에 따른 독립 후속 실험이다. 과거 중단 실험의 원장과 결과는 재사용하거나 변경하지 않는다.

- 후보: reference, scope, reference-strict, 조건부 scope-strict.
- 생성 호출은 호환성 확인을 포함해 최대 166회. 금액·전체 시간 상한 없이 호출별 180초 timeout과 비용 원장을 유지한다.
- 새 프로필은 조사 폴더의 최소 문단만 추가하며 기존 프로필을 보존한다. 전체 system 교체안은 사용하지 않는다.
- `protocol.json`은 결과 열람 전 고정한 선택·승격 기준이다. `candidates.json`은 실제 실행 설정이다.
- 신규 dev12/holdout20 및 루브릭은 `generation_evaluation/benchmarks/luna-reference-followup-v1/`에서 관리한다. 합성 사례와 원본 질문 출처를 구분한다.
- 원응답·원장·가림 판정 작업물은 `tmp/luna-reference-followup-v1/`에 저장한다. 보고서는 후속 결과 디렉터리에서 관리한다.
- 구현 완료와 실제 모델 검증 완료는 구분한다. 실행 결과를 보기 전 작성한 설정이며 성능 개선을 주장하지 않는다.

기본 실행은 저장소 루트에서 `python -m generation_evaluation.selection`에 `--candidates`, `--candidate`, `--cases`, `--documents`, `--rubric`, `--phase`, `--repeats`, `--start-repeat`, `--ledger`, `--output`, `--unlimited-budget --max-calls 166`을 전달한다. 모든 후보가 같은 원장을 공유하며 output은 서로 달라야 한다. 같은 output 재개는 원래 인자를 유지한다.
