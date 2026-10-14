# 질문 주제 분류 아카이브

이 폴더에는 기존 질문 주제 분류 실험의 CSV가 보관되어 있습니다. 다섯 업무 영역 라벨을 쓰는 과거 과제이며, 현재 요청 처리 데이터셋의 `SEARCH_KNOWLEDGE`, `CLARIFY`, `UNSUPPORTED`와는 별도입니다. 문서 주제 분류 데이터는 [문서 주제 아카이브](../document-topics-v0.2/README.md)에 있습니다.

## 파일과 스키마

| 파일 | 보관된 용도 |
|---|---|
| `train.csv` | 과거 학습 분할 |
| `validation.csv` | 과거 검증 분할 |
| `test.csv` | 과거 테스트 분할 |
| `smoke.csv` | 추가 보관 파일. 아래 코드 경로에서는 읽지 않음 |

| 열 | 과거 코드에서 확인한 용도 |
|---|---|
| `id` | 평가 결과와 원래 문항을 연결 |
| `text` | 질문 입력 |
| `label` | 정답 라벨: `it`, `hr`, `finance`, `general_affairs`, `other` |
| `group_id`, `source` | 보관된 메타데이터. 아래 평가 경로에서는 읽지 않음 |

## 과거 코드와 현재 사용 여부

과거 질문 평가 코드는 `train.csv`, `validation.csv`, `test.csv`의 `text`와 `label`을 사용했습니다. 이전 `model_report.py`·`train_jev.py`·`test_jev.py` 이름은 과거 실행 이력이며 현재 이 CSV를 평가하는 명령이 아닙니다.

현재 [저장 모델 평가](../../../classification/experiments/evaluate_saved.py)와 [Jev 평가](../../../classification/experiments/evaluate_jev.py)는 요청 처리 3분류 데이터와 기록된 분할을 사용합니다. 이 아카이브의 다섯 주제 라벨과는 호환되지 않습니다. `smoke.csv`를 포함한 보관 CSV는 현재 활성 분류 실행 경로에서 읽지 않습니다.

현재 요청 처리 데이터의 스키마와 사용법은 [데이터 안내](../../README.md)를 따릅니다. 과거 데이터·출처 조건·실험 결과는 보존합니다.
