# Jev 추가 평가와 분류 후보 7종 비교 — 2026-10-14

## 목적

[로컬 6종 학습·평가](../2026-10-14-model-comparison/README.md)에 빠졌던 Jev를 실제 API로 평가해 후보 7종 비교를 완성한다. 기존 6종 결과와 가중치는 그대로 사용하며 재학습·재추론하지 않았다. 이 보고서는 앞선 보고서를 덮어쓰지 않는 후속 기록이다.

## 실행 조건

- Jev 실행 코드: `87d6efc623c609334c1c0566ee5a4e7009a85b50`. 로컬 6종 실행 코드: `eafaf6ebd7a80c2cd7670985c614143cb1d293dd`.
- 데이터 SHA-256: `a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98`.
- 분할 ID: `71556ff9dcf8a834328ebef7891b7266c3dcf1607e91693eb78744ce18eb9a16`. seed 20261013, train 632 / validation 133 / test 135건. 실제 문항 ID를 기존 6종과 대조했다.
- 가중치 학습 없이 기존 프롬프트와 train 대표 예시 12개를 사용했다. 프롬프트·예시·호출 횟수는 변경하지 않았다.
- 요청 모델 `jev-latest`, 응답 모델 `jev-1.13.0`. validation 133회·test 135회, 총 268회 호출 완료. 재시도·warmup·반복 평가 요청은 추가하지 않았다.
- 보고된 input_tokens 합계는 909,965이다. 청구 금액은 조회하지 않았으므로 비용으로 환산하지 않는다.
- 프롬프트 설계 때 전체 900개 질문(train·validation·test)을 검토했다는 기존 기록을 유지한다. 현재 test는 이미 열람한 합성 개발 자료이며 미열람 최종 평가가 아니다. 로컬 모델과 같은 질문으로 평가했지만 학습·사전 노출 조건까지 동일한 통제 실험은 아니다.
- 로컬 6종은 CPU 4스레드·warmup 3회·반복 3회로 test 추론을 측정했다. Jev는 test 135회의 HTTP 요청 시간을 한 번씩 측정했고 네트워크·서비스·클라이언트 응답 기록 시간이 포함된다. 두 시간을 같은 종류의 모델 연산 시간으로 해석하지 않는다.

## 비교 결과

Validation Macro-F1 순으로 정렬했다. 로컬 최고 3종은 정확히 동점이며 표시 순서가 성능 순위를 뜻하지 않는다.

| 후보 | Validation 정확도 | Validation F1 | Test 정확도 | Test F1 | Test 오답/135 | 평균 ms | 측정 방식 |
|---|---:|---:|---:|---:|---:|---:|---|
| roberta_small | 0.9925 | 0.9926 | 0.9778 | 0.9779 | 3 | 9.42 | 로컬 CPU |
| bert_base | 0.9925 | 0.9926 | 0.9778 | 0.9778 | 3 | 17.13 | 로컬 CPU |
| koelectra_base | 0.9925 | 0.9926 | 1.0000 | 1.0000 | 0 | 18.30 | 로컬 CPU |
| roberta_base | 0.9850 | 0.9849 | 0.9852 | 0.9853 | 2 | 21.21 | 로컬 CPU |
| koelectra_small | 0.9774 | 0.9777 | 0.9704 | 0.9704 | 4 | 3.94 | 로컬 CPU |
| jev | 0.9699 | 0.9693 | 0.9556 | 0.9550 | 6 | 230.43 | API 요청 |
| tfidf | 0.9549 | 0.9550 | 0.9778 | 0.9778 | 3 | 0.28 | 로컬 CPU |

[반올림 전 수치·모델/run 연결 CSV](comparison.csv). Jev는 원격 API이므로 로컬 모델 크기와 학습 run ID는 해당 없음으로 비워 두었다.

## Jev 라벨별 지표·오분류

| 분할 | 라벨 | Precision | Recall | F1 | 문항 수 |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9375 | 1.0000 | 0.9677 | 45 |
| validation | CLARIFY | 1.0000 | 0.9070 | 0.9512 | 43 |
| validation | UNSUPPORTED | 0.9783 | 1.0000 | 0.9890 | 45 |
| test | SEARCH_KNOWLEDGE | 0.9000 | 1.0000 | 0.9474 | 45 |
| test | CLARIFY | 1.0000 | 0.8667 | 0.9286 | 45 |
| test | UNSUPPORTED | 0.9783 | 1.0000 | 0.9890 | 45 |

### validation: 오분류 4건

- RQ0402: 행사 신청 건 좀 부탁드려도 될까요? — 정답 `CLARIFY`, 예측 `UNSUPPORTED`
- RQ0527: 사무실로 온 택배가 훼손돼서 신고하려는데, 제가 표시한 사진이면 되는 건가요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0596: 사내 행사 지원 공지에 적힌 그 조건은 외부에서 참여하는 저도 포함하나요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0666: 다음 주 모임이 회사 행사라던데 그쪽 지원도 같은 방식으로 신청하면 되나요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`

### test: 오분류 6건

- RQ0140: 사무실 대피 안내도에 표시된 이 통로가 평소 출입로와 같은 건가요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0331: 연차 기록에 뭔가 떠 있는데 어떤 내용인지 몰라서요. 이거 좀 봐주실 수 있나요? — 정답 `CLARIFY`, 예측 `UNSUPPORTED`
- RQ0387: 그 봉투는 보안 우편으로 맡기면 되는 거 맞나요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0505: 그 신고 건은 대리 수령한 분 이름을 넣으면 되나요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0706: 사내 추천 채용 안내의 여기 적힌 기간은 추천한 날부터인가요, 입사한 날부터인가요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0773: 업체 지급 서류를 봐주셨으면 하는데 어떤 단계까지 맡기면 되는지 잘 모르겠습니다. — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`

로컬 6종의 라벨별 지표·오분류는 [선행 보고서](../2026-10-14-model-comparison/README.md)에 보존한다.

## 해석·결정

- **7종 비교 실행은 완료했으며 최종 모델 선정은 보류한다.** Validation 최고 그룹은 RoBERTa small·BERT base·KoELECTRA base로 유지된다. Jev는 이번 validation에서 7종 중 6번째, test Macro-F1은 7종 중 가장 낮았다. 이는 이번 데이터·프롬프트·응답 버전의 결과다.
- Jev 오류 10건은 모두 실제 CLARIFY 질문이다. Validation에서 SEARCH_KNOWLEDGE로 3건·UNSUPPORTED로 1건, test에서 각각 5건·1건을 예측했다. Test CLARIFY recall은 39/45=0.8667이다. 질문의 불명확한 지시 대상을 해석해 안내로 분류했을 가능성은 원인 가설이며, 내부 판단 과정을 확인한 사실은 아니다.
- KoELECTRA base의 개발 test 135/135 정답, validation 동점 그룹에서 RoBERTa small의 속도·크기 이점은 선행 관측으로 유지한다. 서버 모델·경로는 이번 평가에서 바꾸지 않았다.
- 새 미열람 실제 사용 질문으로 경계·모호성·개인 조회 요청을 확인해야 한다. 이번 test를 보고 프롬프트를 수정한 뒤 같은 test에서 오른 점수는 독립 성능 개선으로 해석하지 않는다.

## 원자료 접근 방법

Jev 로컬 artifact-root: `artifacts/experiments/jev-comparison-2026-10-14/`. Git 제외 자료이며 팀원에게 자동 공유되는 다운로드 링크가 아니다. 기존 6종 원자료는 선행 보고서의 경로에 그대로 있다.
- 평가 run: `5a04b45af4b141a1ab12f87fdae6db4c` (`kind=eval`, `split=both`, FINISHED).
- 평가 묶음 model_id: `c13cdcdeab054b3981baf308024b6cf2`. 원격 모델 가중치 식별자나 무결성 인증값이 아니다.
- 실제 응답 모델 버전·프롬프트·대표 예시 ID·분할은 `results/jev/metrics.json`에, 문항별 예측은 같은 폴더의 `predictions.json`에 있다.
- `execution-plan.json`, `execution-status.json`, `execution.log`, `completed-responses.jsonl`에 실행 조건·완료 상태·성공 응답을 남겼다. 추적 정보는 `tracking/mlflow.db`와 `tracking/artifacts/`에 있다.
- Jev는 하나의 both run이므로 `split=validation` 전용 필터에 나타나지 않는다. UI에서 `model_name=jev`, `kind=eval`, `split=both`를 확인한다. 로컬 6종 DB와 이번 Jev DB는 별도이며 Git 비교표가 두 실행을 연결한다.

### 다시 실행하는 경우

아래 명령은 새 API 요청 268회를 발생시킨다. `.env`에 TYPESAFE_API_KEY가 설정된 로컬 환경에서만 사용하고, 다른 artifact-root로 새 실행을 구분한다. 키는 문서·Git·MLflow에 기록하지 않는다. 기존 CLI는 .env를 자동으로 읽지 않으므로 uv의 --env-file 옵션으로 전달한다.

```bash
uv run --locked --env-file .env python -m archive.classification_v1.experiments.evaluate_jev \
  --evaluate --artifact-root artifacts/experiments/jev-new-run
```

이번 기록 열람은 API 요청 없이 다음 UI를 실행한다.

```bash
MLFLOW_DISABLE_TELEMETRY=true uv run --locked mlflow server \
  --backend-store-uri sqlite:///artifacts/experiments/jev-comparison-2026-10-14/tracking/mlflow.db \
  --host 127.0.0.1 --port 5051 --workers 1 --no-serve-artifacts
```

브라우저에서 `http://127.0.0.1:5051`을 연다. 로컬 산출물 절대 경로는 다른 환경으로 자동 이전되지 않는다.

### 검증

268개 예측의 질문 ID·정답·분할을 기존 분할과 대조하고 정확도·Macro-F1·라벨별 지표·혼동행렬·오분류 수를 재계산했다. 성공 응답 268개, 완료 상태, MLflow run·model_id·분할 ID 연결을 확인했다. 기존 6종 수치는 원 비교 JSON에서 가져왔으며 총 7종이 포함된다. 기존 18개 run에 Jev 1개 run이 추가된 구성이다.
