# 짧은 안내 요청 보강 학습 — 개선 확인, 서버 승격 보류

## 결론

KoELECTRA base를 원본 pretrained revision에서 보강 자료로 한 번 학습했다. **서버 교체는 보류한다.** 사전 기준 중 회귀 정답 수(40/48, 기준 42)와 CLARIFY 정답 수(5/8, 기준 6)가 미달했다. 새 평가 29/30만으로 승격하지 않는다. 기존 서버 모델 `9f51682d82d4455d8296077c339afd58`과 Luna 설정은 그대로 유지한다.

사용자가 보고한 “우리 회사 연차 규정에 대해 알려줘”는 UNSUPPORTED에서 SEARCH_KNOWLEDGE로 개선됐다. 그러나 “우리 회사 연차 규정에 대해 알려주세요.”는 여전히 차단된다. 업무 무관 질문 두 개와 모호한 요청을 검색으로 보내는 퇴행도 생겼다. 실제 서버 모델 교체·재시작·생성 호출·공개 배포는 하지 않았다.

## 발견과 접근

초기 진단은 48문항 29개 정답, 4개 주제×6개 표현 비교에서 18/24 정답이었다. 같은 절차를 “알려줘”로 끝내면 0/4, “를 알려주세요”로 끝내면 4/4였다. 원본 CSV에서 “알려줘”로 끝나는 문항은 4개(모두 train, SEARCH 1·UNSUPPORTED 3)였다. 표현에 민감한 현상과 자료 부족 가설을 구분했다. 기존 라벨 자체를 잘못된 것으로 일괄 수정하지 않았다.

개발 API의 502는 별도 환경 문제였다. 사용자가 `package.json`의 API 실행에 `--env-file .env`를 추가했고 AI는 이를 별도 커밋했다. 새 `uv` 프로세스가 키를 읽는지 값 노출 없이 확인했다. 이번 작업에서는 실행 중인 서버의 인증·생성 성공을 재검증하지 않았다.

## 사전 고정 자료와 조건

[평가·보강 자료](../../benchmarks/routing-augmentation-2026-10-15/README.md), [승격 기준](../../benchmarks/routing-augmentation-2026-10-15/criteria.json), [검수 범위](../../benchmarks/routing-augmentation-2026-10-15/review.json)를 학습 전에 커밋했다.

- 원본 900행은 유지. 기존 train 그룹 17개에 90문항(SEARCH 36 / UNSUPPORTED 27 / CLARIFY 27)을 추가했다.
- 원본 train 632행 뒤에 보강을 추가하여 722/133/135로 고정했다. validation/test의 ID·순서·행 내용은 양 모델에서 일치한다.
- 기존 회귀 48문항과 표현 24문항은 결과가 알려진 개발 자료다. 서로 중복되어 합산하지 않는다.
- 새 평가 30문항은 새 의도 그룹 10개×3표현(SEARCH 12 / UNSUPPORTED 9 / CLARIFY 9). 학습 전에 질문·라벨을 고정하고 모델 확정 후 양 모델의 예측을 처음 확인했다.
- 자료 작성·검수는 같은 AI가 수행했으며 독립 검수·사람 승인으로 표현하지 않는다. 기존 그룹 ID 보존은 의미상 중복 부재의 완전한 증명이 아니다.

| 조건 | 값 |
|---|---|
| 원본 모델 | monologg/koelectra-base-v3-discriminator |
| revision | 68b30cd259f34a4b5aa8786392612ba2a2617fcc |
| 초기화 | pretrained에서 새 분류 head로 시작; 서비스 가중치 이어 학습 아님 |
| 후보 | 1회, LR 2e-5, 최대 3epoch |
| batch / 길이 / seed | 4 / 256 / 20261013 |
| 장치 | RTX 5060 Laptop GPU, CUDA 13.0 |
| 선택 | 기존 validation Macro-F1 최고, 동점이면 앞선 epoch |
| 실행 시간 | 48.29초(프로세스·저장 검증 포함) |
| 후보 model_id | a3d0ea88baeb4e35ab2dd5facb394a6c |

기존 모델은 LR 2개×3epoch 중 선택한 결과이고 이번은 LR 1개×3epoch다. 한 seed의 재학습 비교이며 데이터 보강 외 효과까지 분리한 인과 실험은 아니다. 전체 Python 테스트의 작은 fixture 학습은 후보 추가 학습에 해당하지 않는다.

| epoch | train loss | validation Macro-F1 |
|---|---:|---:|
| 1 (선택) | 0.629514 | 0.985178 |
| 2 | 0.111133 | 0.977565 |
| 3 | 0.043271 | 0.962249 |

더 오래 학습한 상태의 validation 성능은 떨어졌다. 새로운 평가 결과를 본 뒤 epoch를 다시 고르거나 추가 학습하지 않았다.

## 비교 결과와 승격 판정

| 평가 자료 | 기존 | 후보 | 해석 |
|---|---:|---:|---|
| 기존 validation | 131/133, F1 0.985087 | 131/133, F1 0.985178 | 1개 개선·1개 퇴행 |
| 기존 개발 test | 133/135, F1 0.985098 | 132/135, F1 0.977694 | 1개 퇴행; 이미 노출된 합성 개발 자료 |
| 회귀 | 29/48 | 40/48 | 15개 개선·4개 퇴행 |
| 새 그룹 평가 | 20/30 | 29/30 | 9개 개선, 퇴행 없음 |
| 표현 비교 | 18/24 | 24/24 | 6개 개선; 모두 SEARCH인 자료 |

| 사전 기준 | 후보 결과 | 판정 |
|---|---|---|
| validation F1 하락 ≤ 0.01 | +0.000091 | 통과 |
| 회귀 ≥ 42/48 | 40/48 | **미달** |
| 회귀 SEARCH→UNSUPPORTED ≤ 4 | 1 (기존 13) | 통과 |
| 회귀 CLARIFY ≥ 6/8 | 5/8 (기존 3) | **미달** |
| 새 평가 ≥ 27/30 | 29/30 | 통과 |
| 새 평가 라벨별 recall ≥ 0.8 | SEARCH 1.0, CLARIFY 1.0, UNSUPPORTED 8/9 | 통과 |
| 회귀·새 평가 순수 조회/실행→SEARCH = 0 | 0 | 통과 |

마지막 조건은 **지정된 회귀·새 평가에 한정**된다. 기존 validation에서는 “금액이 다른 청구서와 세금계산서의 정정 요청이 처리됐는지 알려주세요.”가 UNSUPPORTED에서 SEARCH로 퇴행했다. 모든 자료에서 위험한 통과가 없었다고 주장하지 않는다.

### 남은 회귀 오류 8개

| 질문 | 기대 | 후보 | 변화 |
|---|---|---|---|
| 우리 회사 연차 규정에 대해 알려주세요. | SEARCH | UNSUPPORTED | 기존 오류 유지 |
| 내 연차가 며칠 남았어? | UNSUPPORTED | CLARIFY | 기존 오류 유지 |
| 김치찌개 만드는 법 알려줘 | UNSUPPORTED | SEARCH | **퇴행** |
| 오늘 야구 경기 결과 알려줘 | UNSUPPORTED | SEARCH | **퇴행** |
| 연애 운세 봐줘 | UNSUPPORTED | CLARIFY | **퇴행** |
| 이 제도를 어떻게 적용하면 될까? | CLARIFY | SEARCH | **퇴행** |
| 휴가 신청 도와줘 | CLARIFY | SEARCH | 오분류 지속; 기존 UNSUPPORTED |
| 출장비 처리 도와줘 | CLARIFY | SEARCH | 오분류 지속; 기존 UNSUPPORTED |

새 평가의 남은 오류는 “내 동호회 가입 승인됐어?”(UNSUPPORTED→CLARIFY)다. 질문형 개인 상태 조회를 여전히 어려워한다. 기존 test의 추가 퇴행은 “그룹웨어로 정기 회의를 등록하는 중인데 하나만 확인 부탁드립니다.”(CLARIFY→UNSUPPORTED)다.

## 해석과 다음 제안

안내 요청 차단은 크게 줄었으나, 안내처럼 보이는 업무 무관 질문과 대상을 특정하지 않은 질문까지 검색으로 넓히는 문제가 생겼다. 짧은 안내 예시 추가가 유효한 방향이라는 근거는 있지만 이번 후보를 그대로 배포할 근거는 부족하다.

후속 실험을 별도로 승인받는다면 회사/비회사 정보 요청 대조, 대상 없는 설명 요청, “승인됐어?” 같은 질문형 개인 조회, “방법 알려줘”와 “도와줘”의 차이를 보강한다. 이번 fresh는 이제 관찰된 자료이므로 다음 미열람 평가로 재사용하지 않는다. 현 서버에는 키워드 우회·질문 재작성·UNSUPPORTED 전부 검색 전환을 넣지 않는다.

## 재현·원자료

- 원자료: `artifacts/experiments/routing-augmentation-2026-10-15/`의 model, training.log, training-run.json, evaluation.log, results/{baseline,candidate}/{validation,test,regression,fresh,phrasing}.
- 기준 모델: `artifacts/experiments/learning-comparison-2026-10-15/koelectra_base/model`.
- [학습 실행 환경·코드/자료 해시](training-run.json), [후보 식별·가중치 해시·전이 집계](candidate.json), [지표·승격 판정](comparison.json).
- [370행의 문항별 전후 예측](predictions.csv): 각 자료 내 ID·질문·정답·양 모델 예측·개선/퇴행. 자료 간 중복 때문에 370개 독립 질문으로 해석하지 않는다.
- 모든 저장 예측에서 Macro-F1을 재계산했다. 표현 세트는 SEARCH만 있으므로 3라벨 Macro-F1보다 24개 정답 수를 해석한다.

```bash
# 원래 실행 명령. 재학습은 이번 범위에서 이미 1회 완료했으며 자동 재실행하지 않는다.
uv run --locked python -m classification.transformer \
  --dataset classification/benchmarks/routing-augmentation-2026-10-15/combined.csv \
  --split-manifest classification/benchmarks/routing-augmentation-2026-10-15/split-manifest.json \
  --model monologg/koelectra-base-v3-discriminator \
  --revision 68b30cd259f34a4b5aa8786392612ba2a2617fcc \
  --learning-rates 2e-5 --epochs 3 --batch-size 4 --max-length 256 \
  --seed 20261013 --device cuda \
  --output artifacts/experiments/routing-augmentation-2026-10-15/model

# 이미 존재하는 결과 폴더는 거부한다. 재평가 시 새 output 경로를 지정한다.
uv run --locked python -m classification.diagnostic_evaluation \
  artifacts/experiments/routing-augmentation-2026-10-15/model \
  --cases classification/benchmarks/routing-augmentation-2026-10-15/regression.json \
  --output tmp/routing-candidate-regression-recheck
```

가중치와 비밀키는 Git에 포함하지 않는다. 자료·설정·코드·작은 결과를 게시하며 로컬 모델 경로만으로 새 clone에서 실행 가능하다고 표현하지 않는다. 검증·Git·Notion 게시와 기여 구분은 [작업 기록](../../../docs/worklogs/2026-10-15-routing-augmentation.md)에 연결한다.
