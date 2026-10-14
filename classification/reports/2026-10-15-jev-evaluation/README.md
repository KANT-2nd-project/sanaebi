# Jev API 분류 평가 — 2026-10-15

## 목적

로컬 모델 학습 중단 기간에 Jev만 별도로 실제 API 평가했다. 사용자 위임으로 AI가 실행·검증·기록했다. 가중치 학습이나 새 로컬 모델 재개가 아니다.

## 실행 조건

- 보존된 `archive.classification_v1.cli.jev.evaluate_jev`를 재사용했다. 새 학습 구현으로 Jev를 재구현한 것은 아니다. 프롬프트·예시·호출 계약은 변경하지 않았다.
- 요청 모델: `jev-latest`. 응답 모델: `['jev-1.13.0']`.
- 데이터 SHA-256: `a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98`. seed=20261013.
- train 632 / validation 133 / 개발 test 135. train 대표 예시 12개를 사용했다. 새 학습 코드와 분할별 문항 집합은 일치하지만 순서는 다르다. 순서를 포함하는 분할 ID가 같다고 주장하지 않는다.
- 프롬프트 설계 시 전체 데이터가 열람된 기존 조건을 유지한다. test는 이미 열람한 합성 개발 평가 자료이며 독립 최종 평가가 아니다.
- 총 268회 요청. 재시도·warmup·속도 측정용 추가 API 요청 없음. 성공 응답은 즉시 JSONL에 기록했다.
- 보고된 input_tokens 합계: 909,965. 청구 금액은 조회하지 않았다.
- 시간은 HTTP 요청·응답 처리 시간으로 네트워크와 원격 서비스 지연을 포함한다. 로컬 모델의 CPU 연산 시간과 직접 동일시하지 않는다.
- 기존 .env 설정을 uv --env-file로 전달했다. 키 값은 보고서·코드·추적 산출물에 기록하지 않았다.

## 비교 결과

| 분할 | 문항 수 | 정확도 | Macro-F1 | 오분류 | 평균 요청 ms |
|---|---:|---:|---:|---:|---:|
| validation | 133 | 0.969925 | 0.969324 | 4 | 194.50 |
| test | 135 | 0.962963 | 0.962545 | 5 | 203.73 |

## 라벨별 지표·오분류

| 분할 | 라벨 | Precision | Recall | F1 | Support |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9375 | 1.0000 | 0.9677 | 45 |
| validation | CLARIFY | 1.0000 | 0.9070 | 0.9512 | 43 |
| validation | UNSUPPORTED | 0.9783 | 1.0000 | 0.9890 | 45 |
| test | SEARCH_KNOWLEDGE | 0.9184 | 1.0000 | 0.9574 | 45 |
| test | CLARIFY | 1.0000 | 0.8889 | 0.9412 | 45 |
| test | UNSUPPORTED | 0.9783 | 1.0000 | 0.9890 | 45 |

### validation 오분류

- RQ0402: 행사 신청 건 좀 부탁드려도 될까요? — CLARIFY → UNSUPPORTED
- RQ0527: 사무실로 온 택배가 훼손돼서 신고하려는데, 제가 표시한 사진이면 되는 건가요? — CLARIFY → SEARCH_KNOWLEDGE
- RQ0596: 사내 행사 지원 공지에 적힌 그 조건은 외부에서 참여하는 저도 포함하나요? — CLARIFY → SEARCH_KNOWLEDGE
- RQ0666: 다음 주 모임이 회사 행사라던데 그쪽 지원도 같은 방식으로 신청하면 되나요? — CLARIFY → SEARCH_KNOWLEDGE

### test 오분류

- RQ0140: 사무실 대피 안내도에 표시된 이 통로가 평소 출입로와 같은 건가요? — CLARIFY → SEARCH_KNOWLEDGE
- RQ0331: 연차 기록에 뭔가 떠 있는데 어떤 내용인지 몰라서요. 이거 좀 봐주실 수 있나요? — CLARIFY → UNSUPPORTED
- RQ0387: 그 봉투는 보안 우편으로 맡기면 되는 거 맞나요? — CLARIFY → SEARCH_KNOWLEDGE
- RQ0505: 그 신고 건은 대리 수령한 분 이름을 넣으면 되나요? — CLARIFY → SEARCH_KNOWLEDGE
- RQ0706: 사내 추천 채용 안내의 여기 적힌 기간은 추천한 날부터인가요, 입사한 날부터인가요? — CLARIFY → SEARCH_KNOWLEDGE

## 해석·결정

- validation 4건·test 5건의 오류는 모두 정답이 CLARIFY인 질문이다. 모호한 요청의 경계를 후속 검토할 근거다.
- 현재 프롬프트와 원격 응답 버전에서 관측한 개발 평가 결과다. 오분류의 원인은 별도 검토 없이 단정하지 않는다.
- 이 Jev 평가 당시 로컬 6종 실험은 사용자 요청으로 중단 상태였다. 이후 재개해 완료한 비교는 [7종 통합 보고서](../2026-10-15-seven-model-comparison/README.md)에 별도 기록했다. 이 보고서의 Jev 응답은 그대로 재사용했다.
- 최종 모델 선정·서버 교체·사람 검수·실서비스 성능 검증은 수행하지 않았다.

## 원자료와 재실행

- model_id: `96231a428a22477f8b4c7e76ed69f908` (평가 묶음 식별자)
- MLflow run: `65d00c68bc7b4ae5b9a913c608669d38`, FINISHED, `kind=eval`, `split=both`.
- 로컬 artifact-root: `artifacts/experiments/learning-jev-2026-10-15/`. Git에 게시된 다운로드 자료가 아니다.
- `results/jev/metrics.json`, `predictions.json`, `prediction_probabilities.csv`: 평가·문항별 원자료.
- `execution-plan.json`, `execution-status.json`, `completed-responses.jsonl`, `execution.log`: 실행 조건·완료 상태·성공 응답·로그.
- `tracking/mlflow.db`, `tracking/artifacts/`: 이번 실행의 로컬 MLflow 기록. 새 학습 구현의 로컬 모델은 아직 MLflow에 연결하지 않았다.
- [비교표 CSV](comparison.csv), [보고서 목록](../README.md), [과거 Jev 평가](../../../archive/classification_v1/reports/2026-10-14-jev-comparison/README.md).

다음 명령은 새 API 요청 268회를 발생시킨다. 이미 완료한 결과를 읽을 때는 재실행할 필요가 없다. 다른 artifact-root를 사용한다.

```bash
uv run --locked --env-file .env python -m archive.classification_v1.experiments.evaluate_jev \
  --evaluate --artifact-root artifacts/experiments/jev-another-run
```

검증: 268개 예측·성공 응답·문항 ID·정답 대조, 정확도·Macro-F1·라벨별 지표·혼동행렬 재계산, input_tokens 합계, MLflow 완료 상태와 model_id/run 연결 확인.
