# 분류 학습·평가 구조 개선 피드백

작성일: 2026-10-14. 기준: `55b3519`에서 출발한 구조 개선. 구현 커밋은 `52d4105`, small 설정 커밋은 `e53e968`입니다. [작업·검증 기록](2026-10-14-classification-evaluation.md)을 함께 확인합니다.

## 전달용 요약

질문만 입력하고, 그룹을 보존해 분할하며, validation으로 최고 checkpoint를 고르는 핵심 학습 구현은 잘 구성되어 있어 유지했습니다. 이번에는 학습 함수가 test까지 평가하던 책임을 분리하고, 기본 평가를 validation으로 바꾸었습니다. test는 `--split test`로 명시하며 두 결과를 별도 보관합니다. 모델 ID·데이터·평가 용도를 보고서 첫 화면에서 확인할 수 있게 하고 현행 평가·구형 형식·Jev 실행 코드를 나눴습니다.

전체 Python 테스트 266개 실행은 성공했고, 기존 예상 실패 2개와 실모델 호출 제외 1개가 있습니다. 작은 TF-IDF로 학습→재사용→validation→test를 실제 실행했습니다. 이번 변경은 구조와 검증 절차 개선이며, 모델을 재학습하거나 정확도가 향상됐음을 확인한 작업은 아닙니다. 기존 small에서 발견한 짧은 표현의 오분류는 별도 데이터·품질 개선 과제로 남겼습니다.

## 1. 유지한 좋은 구현

- question만 입력하고 ID·정답·그룹·검수 정보를 입력에서 제외합니다.
- 같은 원형 상황의 변형을 그룹으로 묶어 train/validation/test 간 공유를 막습니다.
- TF-IDF 어휘·IDF는 train에만 맞추고 validation은 변환만 합니다.
- Transformer는 train에서만 가중치를 갱신하고 validation은 추론 모드로 실행합니다.
- validation Macro-F1이 개선될 때 가중치를 CPU에 복사하고, 동점은 첫 후보를 유지합니다.
- 모델을 임시 저장·재로딩·검증한 뒤 교체하며 기존 정상 모델과 실패 복구 경로를 보존합니다.

즉, 학습 전체가 잘못되어 다시 만든 것이 아닙니다. 계산·실행·저장 경계를 더 명확히 한 변경입니다.

## 2. 개선 전후 비교

| 부분 | 기존 동작과 혼동 | 변경 후 | 기대 효과 | 검증 근거 |
|---|---|---|---|---|
| 학습 반환 | 전체 DatasetSplits를 받고 test_scores 반환 | train/validation만 받아 SelectionResult의 validation_scores 반환 | 학습 단계에서 test를 실수로 사용하는 경로 제거 | 집중 테스트·workflow 검사 |
| 기본 평가 | validation과 test를 함께 평가 | 기본 validation, `--split test`는 test만 | test 열람을 의식적인 실행으로 구분 | test 접근 시 실패하는 fixture, CLI 실행 |
| 속도 측정 | 기본 평가에서 test를 반복 추론 | 선택한 분할만 반복 측정 | 기본 validation 실행이 test를 건드리지 않음 | warmup·반복 호출 수 검사 |
| 결과 보관 | 모델별 한 결과 폴더 | 모델별 validation/test 하위 폴더 | 서로 덮지 않고 같은 model_id로 대조 | 두 결과 공존·모델 ID·파일 보존 확인 |
| 과거 결과 | 현재와 과거 결과를 혼동하기 쉬움 | 원본 보존, 새 validation 우선, 과거 validation 읽기 지원 | 모델 이름만으로 다른 실험의 점수를 섞는 위험 감소 | 우선순위·stale ID 제외·과거 지표 복원 검사 |
| 평가 코드 | 현행·구형·Jev·비교 게시가 한 파일 | cli/evaluate, legacy/evaluate, cli/jev, evaluation/comparison으로 분리 | 각 실행 계약을 필요한 곳에서 읽음 | import/계층 검사·Jev 호출 계약 검사 |
| preview | 분할·첫 질문 위주 | 입력·라벨·그룹 중복·선택 기준·후보 수·epoch·저장 위치·test 미평가 안내 | 실행 전 무엇을 할지 확인 가능 | 네트워크·저장 없는 preview 검사 |
| small 길이 | 256·384 두 후보 | 256 한 후보 | 현재 질문에서 차이가 없는 길이 탐색 제거 | preset 변경, 기존 900건 길이 진단 |
| 보고서 | test 지표 중심 | 정체·용도·한계, 선택 분할 지표·오류 방향·오분류, 접힌 상세 기록 | 숫자의 대상과 의미를 먼저 파악 | 생성 HTML 내용·내부 링크 확인 |

small 길이 변경의 근거는 현재 로컬 tokenizer에서 전체 900건 최대 65토큰이라는 관측입니다. 모든 모델 tokenizer나 앞으로 들어올 질문도 같다는 뜻은 아닙니다.

## 3. 구조 변경으로 해결한 것

학습 workflow의 입력 계약에서 test를 제거했습니다. 선택 결과와 평가 결과가 구분되고, 기본 명령은 validation만 사용합니다. 결과 저장 경로·보고서·명령 도움말·문서가 이 계약을 따릅니다. 기존 저장 요약의 test 필드는 읽을 수 있지만 신규 학습에서 만들지 않고 새 기본 보고서에 과거 test 지표를 노출하지 않습니다.

과거 결과 파일과 가중치는 보존했습니다. 저장 실패 검사는 test 결과 게시가 실패해도 validation과 과거 파일을 유지하는 경우까지 포함합니다. Jev 프롬프트와 validation/test 요청 횟수, 구형 평가 명령의 의미는 유지했습니다.

`--split test` 자체가 미열람 최종 평가의 증명은 아닙니다. 이미 관찰한 현재 test는 개발 평가이며, 최종 선정의 독립 근거에는 새로운 평가 자료가 필요합니다.

## 4. 구조 변경과 별개로 남은 모델 품질

이번 조사에서 직접 실행한 것은 현재 로컬 KoELECTRA small입니다. 기존 평가 263건은 현재 기록과 일치했지만, 짧은 대표 문장에서 아래 실패가 있었습니다.

| 입력 | 기대 라벨 | small 예측 |
|---|---|---|
| 연차 신청 방법 알려줘 | SEARCH_KNOWLEDGE | UNSUPPORTED |
| VPN 연결 방법 알려줘 | SEARCH_KNOWLEDGE | UNSUPPORTED |
| 내 연차가 며칠 남았어? | UNSUPPORTED | SEARCH_KNOWLEDGE |
| 휴가 신청 도와줘 | CLARIFY | UNSUPPORTED |

“연차 신청 방법을 알려주세요.”는 SEARCH_KNOWLEDGE로 바뀌었습니다. 문체·길이 편향은 원인 후보이지 입증된 원인은 아닙니다. SEARCH_KNOWLEDGE 300개에 15자 이하 문항이 없다는 데이터 관측도 함께 확인했습니다. 이 진단 예시는 대표 성능을 측정한 holdout이 아닙니다.

전량 합성·AI 검수 자료라는 한계, 중요한 세부 유형의 적은 표본, 사람 승인과 실제 직원 표현 검증은 그대로 남습니다. base·RoBERTa 등 다른 모델에서 같은 실패를 재현했다고 주장하지 않습니다. 개별 작성자의 실수나 전체 학습 실패로 단정하지 않습니다.

진단 원본은 로컬 `tmp/classification-review-2026-10-14/`의 `boundary-probes.json`, `extra-evidence.json`, `small-reproduction.json`에 보존했습니다. 공개 성능 벤치마크로 게시한 자료는 아닙니다.

## 5. 새 사용법과 호환 주의

```bash
uv run --locked sanaebi train koelectra_small --preview-questions
uv run --locked sanaebi eval koelectra_small
uv run --locked sanaebi eval koelectra_small --split test
```

- 모델: `artifacts/models/<모델명>/`.
- validation: `artifacts/results/<모델명>/validation/`.
- test: `artifacts/results/<모델명>/test/`.
- 분할별 `metrics.json`, `predictions.json`, `report.html`. 기본 비교는 validation입니다.
- `--split both`는 지원하지 않습니다. 구형 `--model-dir`·`--result-dir` 방식에는 새 `--split`을 지원하지 않습니다.
- small의 길이 후보뿐 아니라 학습 workflow·타입 코드도 바뀌어 기존 모델 train 재사용 조건이 달라질 수 있습니다. 오류를 없애려고 자동으로 재학습하지 않습니다. eval은 기존 저장 모델을 평가할 수 있습니다.
- 재학습이 필요하면 별도 `--artifact-root`로 분리하거나 기존 결과를 보존한 뒤 명시적으로 `--force`를 사용합니다. 이번 작업은 실제 모델 재학습을 수행하지 않았습니다.
- 내부 Python 호출은 `train(train_rows, validation_rows, fit)`와 `SelectionResult`로 바뀌었습니다. 외부 사용자 코드가 이전 `train(dataset, fit)`를 호출한다면 변경해야 합니다. 기존 실험 명령 진입점은 유지합니다.

## 6. 후속 권장 순서

1. 짧은 정보 요청·조회·실행·모호한 도움 요청을 사람이 검수합니다.
2. 같은 문장 암기 확인이 되지 않도록 학습 보완군·회귀군·새 평가군을 상황 그룹으로 분리합니다.
3. 고정한 validation 기준으로 후보를 비교하고, 학습 seed 변화와 분할 변화는 별도로 다룹니다.
4. 최종 모델·설정을 고정한 뒤 새로운 미열람 평가를 수행합니다.
5. 선정된 모델·tokenizer·설정 묶음을 API에 연결하고 단건 추론과 API 결과를 대조합니다.

## 검증 기록

- 집중 실패 기록(로컬 `implementation/red.log`): 기존 기본 평가의 test 접근을 검출했습니다.
- 전체 검사(로컬 `implementation/prepublish-tests.log`): 266개 실행 성공, 예상 실패 2개·제외 1개.
- CLI·HTML(로컬 `implementation/cli-html-check.json`): 임시 TF-IDF의 실제 명령과 생성 HTML 링크.
- 기존 테스트 중 byte 단위 HTML 동일성은 새 표시 계약과 충돌해 의미 검사로 바꿨으며, 과거 metrics·HTML 원본 바이트 보존은 계속 검사합니다.
- Ruff 검사·형식 검사·데이터 검증 성공. 서버 공개 계약은 변경하지 않았습니다.

Notion 기술 요약은 원격 게시 후 실제 커밋과 작업 일지로 연결합니다. 기존 업무의 담당자·기한·상태는 변경하지 않으며 이 자료도 작성자에게 직접 전송하지 않습니다.
