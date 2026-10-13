# 문서 분류 데이터셋 v0.1

[단일 라벨 기준 v2.0](../docs/label-taxonomy.md)에 따른 한국어 문서 분류용 CSV 600건입니다. 준비 원본과 전체 검수 증거는 로컬 보관 자료로 유지하며, 이 CSV를 읽는 데 필요하지 않습니다. 공개 자료의 `source_id`는 [출처·이용 조건 표](ATTRIBUTION.md)에서 원문 제목, URL, 제공자, 이용 조건과 근거를 확인할 수 있습니다.

## CSV 바로 읽기

파일: [`dataset.csv`](dataset.csv), UTF-8 BOM 포함. Python 표준 라이브러리로 읽을 수 있습니다.

```python
import csv

with open("data/dataset.csv", encoding="utf-8-sig", newline="") as file:
    rows = list(csv.DictReader(file))

train = [row for row in rows if row["split"] == "train"]
inputs = [row["title"] + "\n" + row["text"] for row in train]
targets = [row["label"] for row in train]
```

| 열 | 의미 |
|---|---|
| `document_id` | 문서의 고유 ID |
| `title`, `text` | 모델 입력인 제목과 전체 본문 |
| `label` | 대표 업무 주제 하나인 정답 |
| `split` | 고정된 `train`, `validation`, `test` 분할 |
| `source_id` | ATTRIBUTION의 원문 ID 또는 합성 설정 ID |
| `source_group_id` | 개정·복제·파생 문서가 분할 사이에 섞이지 않게 묶은 계열 ID |
| `kind` | `excerpt`(한국어 발췌), `translation`(한국어 번역), `synthetic`(합성) |

공개 자료의 `source_id`는 하나뿐인 원문 조상의 ID이며, 합성 자료는 `ieumworks-synthetic-v1.2`입니다. 제목·본문 외의 열은 모델 입력에 붙이지 않습니다. 본문의 줄바꿈은 CSV 안에 그대로 보존됩니다.

## 구성과 범위

전체 600건은 `train` 420건, `validation` 90건, `test` 90건입니다. 여섯 라벨(`HR`, `IT`, `FINANCE_PROCUREMENT`, `WORKPLACE`, `SECURITY_LEGAL`, `COMPANY`)은 각각 100건입니다. 유형별로는 발췌 105건, 번역 255건, 합성 240건입니다. 라벨 버전은 2.0, 데이터셋 버전은 0.1로 유지됩니다.

| 분할 | 공개 발췌·번역 | 합성 | 라벨별 |
|---|---:|---:|---:|
| train | 180 | 240 | 70 |
| validation | 90 | 0 | 15 |
| test | 90 | 0 | 15 |

시드 `20261013`으로 정한 원문 계열 분할을 그대로 유지합니다. 합성 자료는 학습에만 사용했고 검증·테스트 자료로 학습용 합성을 만들지 않았습니다. 전처리는 train으로만 맞추고 모델 선택은 validation, 최종 평가는 test로 수행합니다.

600건 모두 기록된 절차에 따른 AI 검수를 거쳤고, 사람 승인 상태인 `approved`는 0건입니다. 따라서 사람 정답으로 확정된 평가 자료가 아니며, 이 데이터만으로 현재 6개 라벨 모델의 학습·평가 결과나 실제 서비스 성능을 주장하지 않습니다.

두 별도 AI 검수 세션(`gpt-6-luna`)이 후보 라벨과 상대 판단을 보지 않고 단일 라벨을 판정했고 불일치는 별도 재검수했습니다. 동일 모델 계열의 오류가 겹칠 수 있으며 번역·합성 작성 모델의 일부 ID는 실행 환경에서 공개되지 않았습니다. 전체 작성·검수 기록은 기존 로컬 묶음에 보존했습니다.

공개 자료는 GitLab 핸드북 73개 항목과 한국 공식 행정규칙 36개 항목에서 왔습니다. 출처와 문체가 라벨별로 고르게 섞이지 않아 출처·번역체·문서 형식의 편향이 남아 있습니다. 균형 표본은 실제 기업 문서의 주제 비율을 나타내지 않습니다. 합성 자료는 가상의 이음웍스 설정으로 만든 예시입니다.

기존 질문 분류 데이터/실험은 별도 태스크이며 이 문서 분류 데이터셋에 포함되지 않습니다.

## 기본 검증

```bash
uv run --locked python scripts/validate_dataset.py
uv run --locked python -m unittest discover -s tests -v
```

필수 열·빈 값·단일 라벨·수량·중복·원문 계열 분리·합성의 학습 전용 배치를 검사합니다. 이는 문서의 의미상 정답이나 모델 성능을 보증하지 않습니다. 기존 수집·준비 도구는 로컬 `data/local/preparation-archive/`에 보존하며 CSV 사용에는 필요하지 않습니다.
