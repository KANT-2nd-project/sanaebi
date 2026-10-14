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

## 기존 코드 사용처

- [classification/model_report.py](../../../classification/model_report.py)는 과거 질문 모델 보고서 호환 경로에서 `train.csv`, `validation.csv`, `test.csv`를 읽어 `text`를 평가 입력으로, `label`을 정답으로 사용합니다.

이전에 이 질문 CSV를 평가하던 `train_jev.py`는 문서 분류용 [classification/test_jev.py](../../../classification/test_jev.py)로 개편되었습니다. 현재 질문 아카이브의 사용처로 취급하지 않습니다.

현재 확인한 코드 경로는 `smoke.csv`를 읽지 않습니다. 이 데이터와 스크립트는 현재 FastAPI의 `POST /ask`에 연결되어 있지 않습니다. 현재 요청 처리 데이터의 스키마와 사용법은 [데이터 안내](../../README.md)를 따릅니다.
