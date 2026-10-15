# 요청 분류 보강 자료 v1

사용자가 보고한 짧은 안내 질문 차단과 48문항·표현 비교 진단을 바탕으로 만든 AI 작성·AI 검수 개발 자료입니다. 사람 정답 승인이나 독립 검수 결과가 아닙니다. 라벨 기준은 [요청 처리 기준](../../../docs/label-taxonomy.md)을 유지합니다.

- `augmentation.csv`: 90문항(SEARCH 36 / UNSUPPORTED 27 / CLARIFY 27). 원본 train의 17개 그룹에 연결하고 문항별 의도·판정 근거·출처를 기록했습니다.
- `combined.csv`: 원본 900행을 그대로 보존하고 보강 90행을 추가한 합본입니다. 원본 `data/dataset.csv`는 변경하지 않습니다.
- `split-manifest.json`: 원본 train 632행 뒤에 90행만 추가(722/133/135). validation/test 문항과 순서를 유지합니다. 데이터 해시와 기준 모델 ID를 고정합니다.
- `regression.json`: 기존 진단 48문항. 결과가 이미 알려진 개발 회귀 자료입니다.
- `phrasing.json`: 이미 실행한 4주제×6표현 24문항. 회귀 세트와 중복이 있어 두 결과를 단순 합산하지 않습니다.
- `fresh.json`: 새 의도 그룹 10개×3표현, 30문항(SEARCH 12 / UNSUPPORTED 9 / CLARIFY 9). 학습 전에 고정하고 후보 확정 후에만 예측합니다. 독립적인 30개 상황이나 운영 모집단을 대표하지 않습니다.
- `criteria.json`: 결과 확인 전 고정한 서버 승격 기준입니다. 모든 조건이 참이어야 교체할 수 있습니다.
- `review.json`: AI 검수 범위와 한계입니다. 기존 그룹 보존과 정확한 중복 검사는 의미상 누수 부재의 완전한 증명이 아닙니다.

원본 train의 의도에 문체를 보강했으며, 짧은 명령형을 특정 라벨에 몰아넣지 않았습니다. `pure_lookup_execution`은 안내 없는 실제 조회·실행 요청만 표시하고 혼합 요청은 제외합니다. 혼합 요청은 안내만 제공하는 SEARCH 경로입니다.

고정 분할: `uv run --locked python -m classification.transformer --dataset classification/benchmarks/routing-augmentation-2026-10-15/combined.csv --split-manifest classification/benchmarks/routing-augmentation-2026-10-15/split-manifest.json ...`

평가: `uv run --locked python -m classification.diagnostic_evaluation 모델폴더 --cases classification/benchmarks/routing-augmentation-2026-10-15/regression.json --output 새결과폴더`

학습은 원본 KoELECTRA 고정 revision에서 1회·3epoch, LR 2e-5·batch 4·길이 256·seed 20261013을 사용합니다. validation Macro-F1로 epoch를 선택하며 동점이면 앞선 epoch입니다. 새 평가 확인 후 추가 튜닝하지 않습니다.
