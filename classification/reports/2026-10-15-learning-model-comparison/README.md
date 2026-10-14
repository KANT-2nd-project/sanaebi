# 새 학습 구현으로 분류 모델 6종 비교 — 2026-10-15

## 목적

직접 구현 학습 공간의 새 코드로 6종의 학습·저장·평가를 실행하고 같은 분할의 validation 결과를 비교한다. 실행과 보고서 작성은 사용자 위임으로 AI가 수행했다. 사용자 독립 구현·사람 검수·실서비스 검증 기록이 아니다. 기존 아카이브의 실험과 별도 실행이다.

## 실행 조건

- 데이터 SHA-256: `a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98`
- 분할 ID: `2d077b252bb5b43e9f9457b8dba3b1dd989406a179099ecdbc8948000810866f`
- train/validation/test: 632/133/135, seed=20261013. SGKF 20개 fold를 14/3/3으로 합친 한 번의 holdout이다.
- 입력은 question만 사용한다. TF-IDF는 train에서만 어휘를 학습한다. 후보와 epoch는 validation Macro-F1으로 선택하며 동점은 첫 상태를 유지한다.
- TF-IDF: char 2~5gram, balanced Logistic Regression, C=[0.1, 0.5, 1, 10].
- Transformer: max_length=256, batch=4, 학습률=[2e-5, 5e-5], 후보당 3 epoch, AdamW 기본 weight_decay=0.01. 후보마다 동일 seed로 초기화한다. 전체 사전학습 본체와 분류층을 갱신한다. AMP·scheduler·gradient accumulation은 사용하지 않는다.
- 이 탐색 범위 안의 비교이며 각 모델의 최적 성능을 보장하지 않는다. 과거 10 epoch·길이 탐색 실험과 설정이 다르다.
- 기준 Git commit: `608f86d5d2f4e1384407e0e7a1713d131c14a453`. 미커밋 코드로 실행했으므로 commit만으로 재현되지 않는다. 원자료의 code-snapshot과 execution-plan.json에 실제 코드와 SHA를 보존했다.
- 라이브러리: `{'torch': '2.14.1', 'transformers': '5.19.0', 'scikit-learn': '1.9.1'}`.
- CPU: Intel Core Ultra 9 275HX. GPU: NVIDIA RTX 5060 Laptop 8GB. 모델별 실제 학습 장치는 아래 기록을 따른다. 학습 시간은 최종 완료 시도의 모델 로딩·저장을 포함한 벽시계 시간이며 중단된 시도는 제외한다. 장치와 자원 경합이 달라 학습 속도 순위를 매기지 않는다.
- 추론 시간: 모든 모델 CPU, 스레드 4, batch 1, validation 133문항, 1문항 warmup 후 3회 평균. tokenizer/벡터화 포함, 모델 로딩 제외. 모델 크기는 저장 폴더 전체 MiB다.
- 학습 중에는 다른 서버와 자원을 공유했다. 최종 CPU 추론 측정은 학습과 llama-server 종료 후 수행했지만 다른 백그라운드 작업이 있는 로컬 측정이다. CPU 시간은 실행 중 부하의 영향을 받을 수 있으며 통제된 서버 벤치마크가 아니다.
- test는 이미 열람한 합성 개발 자료다. validation 선택 완료 후 별도 평가했으며 새로운 독립 최종 평가나 실제 직원 질문 성능이 아니다.

## 비교 결과

| 모델 | Validation 정확도 | Macro-F1 | 오류 | 개발 test 정확도 | Macro-F1 | 오류 | CPU ms/질문 | MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tfidf | 0.9549 | 0.9550 | 6 | 0.9778 | 0.9778 | 3 | 0.32 | 2.0 |
| roberta_small | 0.9774 | 0.9775 | 3 | 0.9778 | 0.9778 | 3 | 10.29 | 260.5 |
| koelectra_small | 0.9850 | 0.9850 | 2 | 0.9556 | 0.9556 | 6 | 4.43 | 54.7 |
| bert_base | 0.9850 | 0.9852 | 2 | 0.9852 | 0.9851 | 2 | 20.20 | 422.7 |
| roberta_base | 1.0000 | 1.0000 | 0 | 0.9630 | 0.9629 | 5 | 18.60 | 422.7 |
| koelectra_base | 0.9850 | 0.9851 | 2 | 0.9852 | 0.9851 | 2 | 17.91 | 431.6 |

### 선택 설정과 실행 연결

| 모델 | 선택 설정 | 학습 장치 | 로딩·저장 포함 초 | model_id |
|---|---|---|---:|---|
| tfidf | {"C": 10.0} | cpu | 미측정 | `425c8558f40448ba9b3ca5a4c5061a68` |
| roberta_small | {"learning_rate": 2e-05, "epoch": 3} | cpu | 436.8 | `a4b09f6f283541caaba45b7e9c22215c` |
| koelectra_small | {"learning_rate": 2e-05, "epoch": 3} | cuda | 39.1 | `7ae873d4e5744701bf6e601dd1c9e341` |
| bert_base | {"learning_rate": 2e-05, "epoch": 1} | cuda | 136.7 | `910fee4faefe492eba65108589956c81` |
| roberta_base | {"learning_rate": 2e-05, "epoch": 2} | cuda | 144.2 | `20017d88b9f345c0a638bab71b0b80c5` |
| koelectra_base | {"learning_rate": 2e-05, "epoch": 2} | cuda | 56.7 | `9f51682d82d4455d8296077c339afd58` |

## 라벨별 지표·오분류

### Validation 라벨별 지표

| 모델 | 라벨 | Precision | Recall | F1 | Support |
|---|---|---:|---:|---:|---:|
| tfidf | SEARCH_KNOWLEDGE | 0.9167 | 0.9778 | 0.9462 | 45.0 |
| tfidf | CLARIFY | 0.9756 | 0.9302 | 0.9524 | 43.0 |
| tfidf | UNSUPPORTED | 0.9773 | 0.9556 | 0.9663 | 45.0 |
| roberta_small | SEARCH_KNOWLEDGE | 0.9778 | 0.9778 | 0.9778 | 45.0 |
| roberta_small | CLARIFY | 0.9773 | 1.0000 | 0.9885 | 43.0 |
| roberta_small | UNSUPPORTED | 0.9773 | 0.9556 | 0.9663 | 45.0 |
| koelectra_small | SEARCH_KNOWLEDGE | 0.9783 | 1.0000 | 0.9890 | 45.0 |
| koelectra_small | CLARIFY | 1.0000 | 0.9767 | 0.9882 | 43.0 |
| koelectra_small | UNSUPPORTED | 0.9778 | 0.9778 | 0.9778 | 45.0 |
| bert_base | SEARCH_KNOWLEDGE | 0.9574 | 1.0000 | 0.9783 | 45.0 |
| bert_base | CLARIFY | 1.0000 | 1.0000 | 1.0000 | 43.0 |
| bert_base | UNSUPPORTED | 1.0000 | 0.9556 | 0.9773 | 45.0 |
| roberta_base | SEARCH_KNOWLEDGE | 1.0000 | 1.0000 | 1.0000 | 45.0 |
| roberta_base | CLARIFY | 1.0000 | 1.0000 | 1.0000 | 43.0 |
| roberta_base | UNSUPPORTED | 1.0000 | 1.0000 | 1.0000 | 45.0 |
| koelectra_base | SEARCH_KNOWLEDGE | 0.9574 | 1.0000 | 0.9783 | 45.0 |
| koelectra_base | CLARIFY | 1.0000 | 0.9767 | 0.9882 | 43.0 |
| koelectra_base | UNSUPPORTED | 1.0000 | 0.9778 | 0.9888 | 45.0 |

### Validation 대표 오분류

모델별 저장 예측 순서에서 최대 3개를 제시한다. 원인 분석이나 사람 검수를 수행했다는 의미가 아니다. 전체 오류 방향은 각 metrics.json의 혼동행렬, 전체 질문은 predictions.json에 있다.

**tfidf**

- RQ0666: 다음 주 모임이 회사 행사라던데 그쪽 지원도 같은 방식으로 신청하면 되나요? — CLARIFY → SEARCH_KNOWLEDGE
- RQ0174: 회의실 문 수리를 접수하려는데 하나만 확인하고 싶어요. — CLARIFY → SEARCH_KNOWLEDGE
- RQ0052: 재택근무 신청은 몇 단계인지 알려주시고 다음 주 월요일 일정으로 제 대신 등록해 주세요. — SEARCH_KNOWLEDGE → UNSUPPORTED

**roberta_small**

- RQ0414: 이 문장도 너무 딱딱하지 않게 영어로 옮겨줘: 오래간만이라 반가워. — UNSUPPORTED → CLARIFY
- RQ0052: 재택근무 신청은 몇 단계인지 알려주시고 다음 주 월요일 일정으로 제 대신 등록해 주세요. — SEARCH_KNOWLEDGE → UNSUPPORTED
- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — UNSUPPORTED → SEARCH_KNOWLEDGE

**koelectra_small**

- RQ0174: 회의실 문 수리를 접수하려는데 하나만 확인하고 싶어요. — CLARIFY → UNSUPPORTED
- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — UNSUPPORTED → SEARCH_KNOWLEDGE

**bert_base**

- RQ0754: 금액이 다른 청구서와 세금계산서의 정정 요청이 처리됐는지 알려주세요. — UNSUPPORTED → SEARCH_KNOWLEDGE
- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — UNSUPPORTED → SEARCH_KNOWLEDGE

**roberta_base**

- 이 validation에서 오분류 없음.

**koelectra_base**

- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — UNSUPPORTED → SEARCH_KNOWLEDGE
- RQ0466: 관리자 역할로 가능한가요? — CLARIFY → SEARCH_KNOWLEDGE

## 해석·결정

- 이번 범위에서 validation Macro-F1 최고: roberta_base (1.000000).
- 최종 서비스 모델 선정은 보류한다. 작은 합성 holdout, 단일 seed, 제한된 탐색 예산의 결과다. test 점수로 후보를 재선택하지 않았다.
- 높은 개발 점수와 별개로 경계 질문·실제 사용자 분포의 별도 평가가 필요하다. 속도·크기·오류 비용을 함께 검토한 후 서비스 모델을 결정한다.
- 기존 서버 모델·기존 가중치·아카이브 보고서는 교체하지 않았다.

## 원자료 접근 방법

원자료는 이 작업 환경의 저장소 상대 경로에 있다. Git에 포함된 공개 다운로드 자료가 아니다.

```text
artifacts/experiments/learning-comparison-2026-10-15/
  execution-plan.json
  code-snapshot/
  logs/<model>-train.log
  logs/<transformer>-execution.json
  <model>/model/metadata.json
  <model>/results/validation/{metrics,predictions}.json
  <model>/results/test/{metrics,predictions}.json
  <model>/benchmark.json
```

- 이번 새 구현에는 MLflow 연결이 없으므로 학습·평가 run ID도 없다. model_id와 split_id로 연결한다. 아카이브 MLflow run으로 대체하지 않는다.
- 모델 원본 이름·요청 revision·해결 revision과 모든 trial은 metadata.json, 실제 실행 명령·장치·벽시계 시간은 logs에 있다.
- [비교표 CSV](comparison.csv), [실험 목록](../README.md), [학습 코드 안내](../../README.md).

검증: 12개 평가의 예측에서 정확도·Macro-F1·오류 수 재계산, 모델별 선택 점수와 저장 모델 validation 점수 일치, 6종 데이터 SHA·split_id 일치, 문항 ID·model_id 연결 확인.
