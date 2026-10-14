# 분류 모델 6종 학습·개발 평가 — 2026-10-14

## 목적

같은 질문·분할에서 로컬 분류 모델 6종의 성능·속도·크기를 비교한다. 이번 보고서는 실제 새 학습·평가 실행을 정리한 것으로, [과거 제출 결과](../../result/README.md)와 별개다. 최종 서비스 모델 선정은 보류한다.

## 실행 조건

- 코드: `eafaf6ebd7a80c2cd7670985c614143cb1d293dd`. 실행 중 저장한 설정과 run 기록을 근거로 한다.
- 데이터: `data/dataset.csv`, SHA-256 `a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98`.
- 분할 ID: `71556ff9dcf8a834328ebef7891b7266c3dcf1607e91693eb78744ce18eb9a16` (저장된 분할 기록의 digest).
- seed: `20261013`. 층화 그룹 분할 20개 fold를 14/3/3으로 합쳐 train 632 / validation 133 / test 135건을 사용했다. 모든 모델의 실제 문항 ID가 같다.
- 입력은 question 하나이며 라벨은 SEARCH_KNOWLEDGE / CLARIFY / UNSUPPORTED다. 학습은 train, 후보·checkpoint 선택은 validation Macro-F1만 사용했다. 동점은 먼저 선택한 후보를 유지했다.
- TF-IDF 후보 C: 0.1 / 0.5 / 1.0 / 10.0. 문자 2~5그램, min_df=1, balanced LogisticRegression, max_iter=1000.
- Transformer: 학습률 2e-5 / 5e-5, batch 4, 후보당 10 epoch. 길이 후보 256 / 384이며 KoELECTRA small만 256. 최고 checkpoint 복원 후 저장·재로딩 평가했다.
- Transformer 학습: NVIDIA GeForce RTX 5060 Laptop GPU. CPU 추론: 스레드 4, warmup 3회·반복 3회. 비교표 시간은 test 질문의 평균이며 HTTP·LLM 답변 시간을 포함하지 않는다.
- 합성·AI 검수 자료이며 사람 승인·실제 직원 질문 검증은 별도다. test는 이전 개발 과정에서 이미 열람한 자료다. 이번 학습이나 checkpoint 선택에 test를 넣지는 않았지만 독립적인 미열람 최종 평가라고 부르지 않는다.
- Jev는 외부 API 평가이므로 이번 새 학습·평가에서 제외했다.

### 선택된 설정

| 모델 | 선택 설정 | 기반 모델 revision |
|---|---|---|
| roberta_small | `{"max_length": 256, "learning_rate": 2e-05, "best_epoch": 1}` | `b6b4c36d827e0293ae2fcf04d527072f10a23064` |
| bert_base | `{"max_length": 256, "learning_rate": 5e-05, "best_epoch": 9}` | `77c8b3d707df785034b4e50f2da5d37be5f0f546` |
| koelectra_base | `{"max_length": 256, "learning_rate": 2e-05, "best_epoch": 3}` | `68b30cd259f34a4b5aa8786392612ba2a2617fcc` |
| roberta_base | `{"max_length": 256, "learning_rate": 2e-05, "best_epoch": 1}` | `02f94ba5e3fcb7e2a58a390b8639b0fac974a8da` |
| koelectra_small | `{"max_length": 256, "learning_rate": 2e-05, "best_epoch": 4}` | `7488f8db0f208beff4a1f3f9bb3ed04650a89ed7` |
| tfidf | `{"C": 10.0}` | `해당 없음` |

## 비교 결과

Validation Macro-F1 내림차순이다. 동점 모델의 표시 순서만 CPU 평균 추론 시간으로 정렬했으며 별도의 성능 순위를 뜻하지 않는다. CSV는 반올림 전 수치를 보관한다.

| 모델 | Validation 정확도 | Validation F1 | Test 정확도 | Test F1 | Test 오답/135 | CPU 평균 ms | 크기 MiB | 선택 시간 초 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| roberta_small | 0.9925 | 0.9926 | 0.9778 | 0.9779 | 3 | 9.42 | 260.5 | 197.4 |
| bert_base | 0.9925 | 0.9926 | 0.9778 | 0.9778 | 3 | 17.13 | 422.7 | 318.3 |
| koelectra_base | 0.9925 | 0.9926 | 1.0000 | 1.0000 | 0 | 18.30 | 431.6 | 337.7 |
| roberta_base | 0.9850 | 0.9849 | 0.9852 | 0.9853 | 2 | 21.21 | 422.7 | 330.7 |
| koelectra_small | 0.9774 | 0.9777 | 0.9704 | 0.9704 | 4 | 3.94 | 54.7 | 78.6 |
| tfidf | 0.9549 | 0.9550 | 0.9778 | 0.9778 | 3 | 0.28 | 2.0 | 6.1 |

[비교 CSV](comparison.csv). 선택 시간은 구현에서 측정한 후보 학습·선택 구간이며 전체 명령 실행 시간과 다르다. 18개 명령의 실행 시간 합계는 약 24분 17초다.

## 라벨별 지표·오분류

### roberta_small

| 분할 | 라벨 | Precision | Recall | F1 | 문항 수 |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9783 | 1.0000 | 0.9890 | 45 |
| validation | CLARIFY | 1.0000 | 1.0000 | 1.0000 | 43 |
| validation | UNSUPPORTED | 1.0000 | 0.9778 | 0.9888 | 45 |
| test | SEARCH_KNOWLEDGE | 0.9375 | 1.0000 | 0.9677 | 45 |
| test | CLARIFY | 1.0000 | 0.9778 | 0.9888 | 45 |
| test | UNSUPPORTED | 1.0000 | 0.9556 | 0.9773 | 45 |

**validation 오분류 1건:** UNSUPPORTED → SEARCH_KNOWLEDGE 1건

- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

**test 오분류 3건:** UNSUPPORTED → SEARCH_KNOWLEDGE 2건; CLARIFY → SEARCH_KNOWLEDGE 1건

- RQ0203: 제가 신청한 가족돌봄휴가, 지금 승인 단계가 어디까지 왔나요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`
- RQ0706: 사내 추천 채용 안내의 여기 적힌 기간은 추천한 날부터인가요, 입사한 날부터인가요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0735: 제 개인 깃허브 포트폴리오에 올릴 알고리즘 문제 풀이를 대신 작성해 줄 수 있나요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

### bert_base

| 분할 | 라벨 | Precision | Recall | F1 | 문항 수 |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9783 | 1.0000 | 0.9890 | 45 |
| validation | CLARIFY | 1.0000 | 1.0000 | 1.0000 | 43 |
| validation | UNSUPPORTED | 1.0000 | 0.9778 | 0.9888 | 45 |
| test | SEARCH_KNOWLEDGE | 0.9778 | 0.9778 | 0.9778 | 45 |
| test | CLARIFY | 0.9574 | 1.0000 | 0.9783 | 45 |
| test | UNSUPPORTED | 1.0000 | 0.9556 | 0.9773 | 45 |

**validation 오분류 1건:** UNSUPPORTED → SEARCH_KNOWLEDGE 1건

- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

**test 오분류 3건:** UNSUPPORTED → CLARIFY 1건; UNSUPPORTED → SEARCH_KNOWLEDGE 1건; SEARCH_KNOWLEDGE → CLARIFY 1건

- RQ0041: 제가 신청한 교육비 지원이 승인됐는지 상태를 봐줘. — 정답 `UNSUPPORTED`, 예측 `CLARIFY`
- RQ0203: 제가 신청한 가족돌봄휴가, 지금 승인 단계가 어디까지 왔나요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`
- RQ0429: 재택근무자인데 다음 주 출근해요. 사무실 출입 신청이 필요할까요? — 정답 `SEARCH_KNOWLEDGE`, 예측 `CLARIFY`

### koelectra_base

| 분할 | 라벨 | Precision | Recall | F1 | 문항 수 |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9783 | 1.0000 | 0.9890 | 45 |
| validation | CLARIFY | 1.0000 | 1.0000 | 1.0000 | 43 |
| validation | UNSUPPORTED | 1.0000 | 0.9778 | 0.9888 | 45 |
| test | SEARCH_KNOWLEDGE | 1.0000 | 1.0000 | 1.0000 | 45 |
| test | CLARIFY | 1.0000 | 1.0000 | 1.0000 | 45 |
| test | UNSUPPORTED | 1.0000 | 1.0000 | 1.0000 | 45 |

**validation 오분류 1건:** UNSUPPORTED → SEARCH_KNOWLEDGE 1건

- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

**test 오분류 0건:** 없음


### roberta_base

| 분할 | 라벨 | Precision | Recall | F1 | 문항 수 |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9783 | 1.0000 | 0.9890 | 45 |
| validation | CLARIFY | 0.9773 | 1.0000 | 0.9885 | 43 |
| validation | UNSUPPORTED | 1.0000 | 0.9556 | 0.9773 | 45 |
| test | SEARCH_KNOWLEDGE | 1.0000 | 0.9778 | 0.9888 | 45 |
| test | CLARIFY | 0.9574 | 1.0000 | 0.9783 | 45 |
| test | UNSUPPORTED | 1.0000 | 0.9778 | 0.9888 | 45 |

**validation 오분류 2건:** UNSUPPORTED → CLARIFY 1건; UNSUPPORTED → SEARCH_KNOWLEDGE 1건

- RQ0414: 이 문장도 너무 딱딱하지 않게 영어로 옮겨줘: 오래간만이라 반가워. — 정답 `UNSUPPORTED`, 예측 `CLARIFY`
- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

**test 오분류 2건:** UNSUPPORTED → CLARIFY 1건; SEARCH_KNOWLEDGE → CLARIFY 1건

- RQ0203: 제가 신청한 가족돌봄휴가, 지금 승인 단계가 어디까지 왔나요? — 정답 `UNSUPPORTED`, 예측 `CLARIFY`
- RQ0429: 재택근무자인데 다음 주 출근해요. 사무실 출입 신청이 필요할까요? — 정답 `SEARCH_KNOWLEDGE`, 예측 `CLARIFY`

### koelectra_small

| 분할 | 라벨 | Precision | Recall | F1 | 문항 수 |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9375 | 1.0000 | 0.9677 | 45 |
| validation | CLARIFY | 1.0000 | 0.9767 | 0.9882 | 43 |
| validation | UNSUPPORTED | 1.0000 | 0.9556 | 0.9773 | 45 |
| test | SEARCH_KNOWLEDGE | 0.9556 | 0.9556 | 0.9556 | 45 |
| test | CLARIFY | 0.9574 | 1.0000 | 0.9783 | 45 |
| test | UNSUPPORTED | 1.0000 | 0.9556 | 0.9773 | 45 |

**validation 오분류 3건:** UNSUPPORTED → SEARCH_KNOWLEDGE 2건; CLARIFY → SEARCH_KNOWLEDGE 1건

- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`
- RQ0660: 제품 안내 영상 검토에 "초반을 조금 줄여 주세요"라는 코멘트가 있습니다. 어느 구간을 편집해야 하는지 알 수 있을까요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0754: 금액이 다른 청구서와 세금계산서의 정정 요청이 처리됐는지 알려주세요. — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

**test 오분류 4건:** SEARCH_KNOWLEDGE → CLARIFY 2건; UNSUPPORTED → SEARCH_KNOWLEDGE 2건

- RQ0099: 이번 주 장애 대응 당번인데 임시 관리자 권한 승인 절차가 궁금합니다. 제 계정에도 해당 권한을 지금 추가해 주세요. — 정답 `SEARCH_KNOWLEDGE`, 예측 `CLARIFY`
- RQ0203: 제가 신청한 가족돌봄휴가, 지금 승인 단계가 어디까지 왔나요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`
- RQ0429: 재택근무자인데 다음 주 출근해요. 사무실 출입 신청이 필요할까요? — 정답 `SEARCH_KNOWLEDGE`, 예측 `CLARIFY`
- RQ0735: 제 개인 깃허브 포트폴리오에 올릴 알고리즘 문제 풀이를 대신 작성해 줄 수 있나요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

### tfidf

| 분할 | 라벨 | Precision | Recall | F1 | 문항 수 |
|---|---|---:|---:|---:|---:|
| validation | SEARCH_KNOWLEDGE | 0.9167 | 0.9778 | 0.9462 | 45 |
| validation | CLARIFY | 0.9756 | 0.9302 | 0.9524 | 43 |
| validation | UNSUPPORTED | 0.9773 | 0.9556 | 0.9663 | 45 |
| test | SEARCH_KNOWLEDGE | 0.9565 | 0.9778 | 0.9670 | 45 |
| test | CLARIFY | 1.0000 | 1.0000 | 1.0000 | 45 |
| test | UNSUPPORTED | 0.9773 | 0.9556 | 0.9663 | 45 |

**validation 오분류 6건:** SEARCH_KNOWLEDGE → UNSUPPORTED 1건; CLARIFY → SEARCH_KNOWLEDGE 3건; UNSUPPORTED → SEARCH_KNOWLEDGE 1건; UNSUPPORTED → CLARIFY 1건

- RQ0052: 재택근무 신청은 몇 단계인지 알려주시고 다음 주 월요일 일정으로 제 대신 등록해 주세요. — 정답 `SEARCH_KNOWLEDGE`, 예측 `UNSUPPORTED`
- RQ0174: 회의실 문 수리를 접수하려는데 하나만 확인하고 싶어요. — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0210: 인사 쪽 그거 지금 해야 하나요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0424: 거실 와이파이가 자주 끊깁니다. 공유기 설정을 어떻게 바꾸면 좋을까요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`
- RQ0666: 다음 주 모임이 회사 행사라던데 그쪽 지원도 같은 방식으로 신청하면 되나요? — 정답 `CLARIFY`, 예측 `SEARCH_KNOWLEDGE`
- RQ0799: 제가 제출한 입사 서류 중 검토 완료된 항목이 무엇인지 보여주세요. — 정답 `UNSUPPORTED`, 예측 `CLARIFY`

**test 오분류 3건:** SEARCH_KNOWLEDGE → UNSUPPORTED 1건; UNSUPPORTED → SEARCH_KNOWLEDGE 2건

- RQ0099: 이번 주 장애 대응 당번인데 임시 관리자 권한 승인 절차가 궁금합니다. 제 계정에도 해당 권한을 지금 추가해 주세요. — 정답 `SEARCH_KNOWLEDGE`, 예측 `UNSUPPORTED`
- RQ0203: 제가 신청한 가족돌봄휴가, 지금 승인 단계가 어디까지 왔나요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`
- RQ0735: 제 개인 깃허브 포트폴리오에 올릴 알고리즘 문제 풀이를 대신 작성해 줄 수 있나요? — 정답 `UNSUPPORTED`, 예측 `SEARCH_KNOWLEDGE`

## 해석·결정

- **최종 모델 선정은 보류한다.** Validation 최고 그룹은 RoBERTa small·BERT base·KoELECTRA base이며 점수가 정확히 같다. 세 모델 모두 RQ0424(거실 와이파이 설정 질문) 1건을 UNSUPPORTED 대신 SEARCH_KNOWLEDGE로 예측했다.
- KoELECTRA base는 이번 개발 test 135건을 모두 맞췄다. 실서비스 정확도 100%나 독립적인 최종 평가 완료를 뜻하지 않는다. Test 결과를 근거로 추가 설정을 고르면 이후 비교도 개발 선택의 영향을 받는다.
- 같은 validation 성능에서 속도·크기를 고려할 후보는 RoBERTa small이다. 이번 CPU 측정에서 두 base 모델보다 빠르고 작았다. 이는 이번 환경의 관측이며 모든 환경에서 우월하다는 결론이 아니다.
- TF-IDF는 가장 가볍고 빠르지만 validation 오분류는 6건이었다. KoELECTRA small은 Transformer 중 가장 작고 빠르지만 이번 두 분할 점수는 최고 그룹보다 낮았다.
- 개인/업무 경계, 개인 신청 상태 조회, 안내와 실행 요청이 섞인 질문은 다음 검수·평가에서 확인할 항목이다. 공통 오류가 관측됐다는 사실과 데이터 문체·범위 편향이 원인일 수 있다는 가설을 구분한다.
- 단일 seed·단일 분할과 작은 합성 평가셋의 한계가 있다. 새 미열람 실제 사용 질문을 준비해 후보를 확인한 뒤 선정한다. 이번 실험에서 서버 모델·경로를 교체하지 않았다.

## 원자료 접근 방법

### 실행과 보관 위치

저장소 기준 로컬 경로는 `artifacts/experiments/full-training-2026-10-14/`다. Git에서 제외한 자료이며 팀원에게 자동 공유되는 다운로드 링크가 아니다. 기존 모델·과거 결과는 교체하지 않았다. 아래 명령은 기록된 실행 방식 안내이며 보고서 작성 과정에서 재실행하지 않았다.

```bash
uv run --locked sanaebi train MODEL --artifact-root artifacts/experiments/full-training-2026-10-14
uv run --locked sanaebi eval MODEL --artifact-root artifacts/experiments/full-training-2026-10-14
uv run --locked sanaebi eval MODEL --split test --artifact-root artifacts/experiments/full-training-2026-10-14
```

MODEL은 비교표의 모델 이름이다. 기존 폴더에서는 train이 안내 종료한다. 재현 실험은 다른 artifact-root를 사용한다. 원래 모델을 덮어쓰지 않는다.

- `execution-plan.json`: 실행 당시 코드·설정·전체 분할 기록.
- `execution-status.json`, `logs/`: 명령 종료 코드·시간·실행 로그.
- `models/<모델명>/`: 가중치·학습 요약·manifest.
- `results/<모델명>/<validation|test>/`: 지표·문항별 예측 JSON.
- `tracking/mlflow.db`, `tracking/artifacts/`: 설정·trial CSV·후보별 epoch 기록·환경·평가 산출물.

로컬 자료를 가진 환경에서 저장소 루트 기준으로 다음을 실행하고 Model training → classification을 연다.

```bash
MLFLOW_DISABLE_TELEMETRY=true uv run --locked mlflow server \
  --backend-store-uri sqlite:///artifacts/experiments/full-training-2026-10-14/tracking/mlflow.db \
  --host 127.0.0.1 --port 5050 --workers 1 --no-serve-artifacts
```

브라우저 주소는 `http://127.0.0.1:5050`이다. 로컬 산출물 경로는 절대 경로로 기록되어 있어 다른 컴퓨터로 옮길 때 경로 접근을 별도로 확인해야 한다. 가중치는 MLflow에 중복 업로드하지 않았다.

### 모델과 run 연결

아래 model_id는 모델 묶음 식별자이며 무결성 인증값이 아니다.

| 모델 | model_id | 학습 run | Validation run | Test run |
|---|---|---|---|---|
| `roberta_small` | `e925fc8c0002435fb408d938bdb41aea` | `d21ce00246ca497ba0e7b8cd8e339613` | `3739f5640d074cf5879b3d9da056f5a8` | `25efdbf640ea4775a6fc0b434046f8d4` |
| `bert_base` | `ce5d4d7a6dac4252a7ee2c8846609db6` | `873edc26d55845d7a034d66a7c129f44` | `992e0db91beb46b9be6fbe0dc5f93fbd` | `503e2e497c0643fb98ba1a49dca03dcc` |
| `koelectra_base` | `35524a6b8e6244cf9c54f8af70e4b425` | `328ae4c578364b9aa1ad6d919e1939e7` | `73f6eb3aec8e45feb40ab8fbe76fbb6c` | `8983b8db673b44b7bff35a5522823449` |
| `roberta_base` | `966dd3f4202243e98572e116ea192e38` | `6c8a48f5f7b84ffd9b103d49db876532` | `45eac0cfb12742949763be49be02d93d` | `49df42d2728c4cacb2654ab4913a0310` |
| `koelectra_small` | `2b7ff566d0d04d7580e563aaf2d86d2b` | `faff4e737de8480187e502e07907ec88` | `6e1a41962e0946c8bfcf6cfa419a22c9` | `a9ce9f1754e14e80abe814d175f9a05e` |
| `tfidf` | `93a1811d940847659ece4b413b3ccfa8` | `f24e2ba17446430ba15a81887b8af09b` | `6859da58bf1540c1b8cf2b967b3a3a2a` | `a62591fb291046908d4cc187c157108f` |

### 검증 범위

6종의 동일 데이터·실제 분할 ID, 모델·학습·평가 run 연결을 대조했다. 12개 예측 파일에서 정확도·Macro-F1·라벨별 지표·혼동행렬·오분류 수를 재계산해 저장 결과와 일치함을 확인했다. 저장 후 validation 지표는 학습 요약과 모두 같고 18개 명령은 종료 코드 0, MLflow 18개 run은 FINISHED다. 보고서 작성에는 재학습·추론·외부 API 요청이 포함되지 않는다.
