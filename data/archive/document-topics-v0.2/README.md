# 문서 분류 데이터셋 v0.2

[단일 라벨 기준 v2.0](label-taxonomy.md)에 따른 한국어 문서 분류용 CSV 600건입니다. 준비 원본과 전체 검수 증거는 로컬 보관 자료로 유지하며, 이 CSV를 읽는 데 필요하지 않습니다. 공개 자료의 `source_id`는 [출처·이용 조건 표](ATTRIBUTION.md)에서 원문 제목, URL, 제공자, 이용 조건과 근거를 확인할 수 있습니다.

이 자료는 문서 제목·본문에서 HR 등 6개 업무 주제를 분류하는 기존 학습 과제입니다. 서비스의 질문 처리 라벨 학습 데이터가 아니며, 회사 규정 원문이나 답변 근거로도 사용하지 않습니다. 현재 서비스 상태와 후속 요청 처리 흐름은 [서비스 아키텍처](../../../docs/service-architecture.md)를 참고하세요.

## CSV 바로 읽기

파일: [`dataset.csv`](dataset.csv), UTF-8 BOM 포함. Python 표준 라이브러리로 읽을 수 있습니다.

```python
import csv

with open(
    "data/archive/document-topics-v0.2/dataset.csv",
    encoding="utf-8-sig",
    newline="",
) as file:
    rows = list(csv.DictReader(file))

inputs = [row["title"] + "\n" + row["text"] for row in rows]
targets = [row["label"] for row in rows]
```

저장소 루트에서 실행하면 이 아카이브의 전체 자료를 읽습니다. 제목과 본문을 줄바꿈으로 연결해 입력을 만들고, 다른 열은 입력에 붙이지 않습니다.

| 열 | 의미 |
|---|---|
| `document_id` | 문서의 고유 ID |
| `title`, `text` | 모델 입력인 제목과 전체 본문 |
| `label` | 대표 업무 주제 하나인 정답 |
| `source_id` | ATTRIBUTION의 원문 ID 또는 합성 설정 ID |
| `source_group_id` | 개정·복제·파생 문서가 분할 사이에 섞이지 않게 묶은 계열 ID |
| `kind` | `excerpt`(한국어 발췌), `translation`(한국어 번역), `synthetic`(합성) |

공개 자료의 `source_id`는 하나뿐인 원문 조상의 ID이며, 합성 자료는 `ieumworks-synthetic-v1.2`입니다. 제목·본문 외의 열은 모델 입력에 붙이지 않습니다. 본문의 줄바꿈은 CSV 안에 그대로 보존됩니다.

## 구성과 범위

전체 600건이며 여섯 라벨(`HR`, `IT`, `FINANCE_PROCUREMENT`, `WORKPLACE`, `SECURITY_LEGAL`, `COMPANY`)은 각각 100건입니다. 유형별로는 발췌 105건, 번역 255건, 합성 240건입니다. 각 라벨에는 공개 발췌·번역 60건과 합성 40건이 있습니다. 라벨 버전은 2.0, 데이터셋 버전은 0.2입니다.

v0.2는 v0.1 CSV에서 `split` 열만 제거한 7개 열 형식입니다. 600건의 순서와 나머지 값, 본문 줄바꿈은 유지했습니다. 기존 고정 분할은 로컬 원본 묶음에 보존하며, 현재 CSV에는 분할 정보를 저장하지 않습니다.

### 분할 계획과 현재 구현

초기 v0.2 작업 문서에는 `document_id` 순서와 시드 `20261013`을 사용하고, 합성 240건을 학습에만 두며 공개 발췌·번역 360건을 50:25:25로 나누는 계획이 기록되어 있습니다. 전체 70:15:15, 총 420/90/90건, 라벨별 70/15/15건은 목표였으며 정확한 행 수를 강제하지 않았습니다. 아래 코드의 현재 분할 설정과는 구분되는 과거 계획입니다.

보관된 문서 분할 구현은 [classification/legacy/document_split.py](../../../classification/legacy/document_split.py)입니다. 기본 시드는 `42`이며 `document_id`로 입력 순서를 고정하고 `source_group_id`를 보존합니다. 합성 자료가 속한 그룹의 모든 행은 train에 두고, 나머지 공개 자료를 셔플된 `StratifiedGroupKFold(n_splits=4)`로 나눕니다. fold 2·3은 train, fold 0은 validation, fold 1은 test에 배치합니다. 따라서 실제 분할 크기는 이 구현과 데이터에 따라 정해지며 과거 계획의 목표 수량과 같다고 가정하지 않습니다. 이 구현은 분할 기록에 데이터 지문, 시드, 문서 ID를 저장합니다. 현재 활성 TF-IDF·Transformer 학습은 별도의 요청 처리 질문 분할을 사용하며, 이 보관 모듈을 호출하지 않습니다.

모델 선택은 validation, 최종 평가는 test에서 수행합니다. 학습에 맞추는 전처리는 train에만 적용합니다. 같은 `source_group_id`는 여러 분할에 나뉘지 않습니다.

600건 모두 기록된 절차에 따른 AI 검수를 거쳤고, 사람 승인 상태인 `approved`는 0건입니다. 따라서 사람 정답으로 확정된 평가 자료가 아니며, 이 데이터만으로 현재 6개 라벨 모델의 학습·평가 결과나 실제 서비스 성능을 주장하지 않습니다.

두 별도 AI 검수 세션(`gpt-6-luna`)이 후보 라벨과 상대 판단을 보지 않고 단일 라벨을 판정했고 불일치는 별도 재검수했습니다. 동일 모델 계열의 오류가 겹칠 수 있으며 번역·합성 작성 모델의 일부 ID는 실행 환경에서 공개되지 않았습니다. 전체 작성·검수 기록은 기존 로컬 묶음에 보존했습니다.

공개 자료는 GitLab 핸드북 73개 항목과 한국 공식 행정규칙 36개 항목에서 왔습니다. 출처와 문체가 라벨별로 고르게 섞이지 않아 출처·번역체·문서 형식의 편향이 남아 있습니다. 균형 표본은 실제 기업 문서의 주제 비율을 나타내지 않습니다. 합성 자료는 가상의 이음웍스 설정으로 만든 예시입니다.

기존 질문 분류 데이터/실험은 별도 태스크이며 이 문서 분류 데이터셋에 포함되지 않습니다.

## 저장소의 검증 범위

```bash
uv run --locked python scripts/validate_dataset.py
uv run --locked python -m unittest discover -s tests -v
```

첫 명령의 기본 대상은 현재 요청 처리 질문 데이터와 검수 기록이며, 이 문서 분류 CSV를 검사하지 않습니다. 저장소 단위 테스트에는 문서 분할·보고서 코드 확인이 포함되지만, 아카이브 CSV 전체의 별도 스키마 검증 명령은 제공하지 않습니다. 이 검사는 문서 라벨의 의미상 정답이나 모델 성능을 보증하지 않습니다. 기존 수집·준비 도구는 로컬 `data/local/preparation-archive/`에 보존하며 CSV 사용에는 필요하지 않습니다.
