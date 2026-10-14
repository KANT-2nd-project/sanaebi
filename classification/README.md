# 질문 분류 실험

질문 분류 모델의 학습과 평가를 실행한다. [라벨 기준](../docs/label-taxonomy.md)과 [데이터 안내](../data/README.md)는 각 정보의 기준 문서다. 공통 라벨은 [contracts/classification.py](../contracts/classification.py)에서 가져온다.

## 먼저 읽을 코드

`train_koelectra_small.py` 등 `train_*` 파일은 현재 사용하는 모델별 실행 진입점이다. 레거시 보관 파일이 아니며, 모델 ID·저장 폴더를 설정하고 공통 CLI를 호출한다. 실제 학습 구현은 `models/`에서 읽는다.

처음에는 다음 순서로 한 단계씩 확인한다. 전체 파일을 한 번에 이해할 필요는 없다.

| 단계 | 읽을 곳 | 확인할 질문 |
|---|---|---|
| 1. 실행 설정 | [train_koelectra_small.py](train_koelectra_small.py) | 어떤 모델을 어느 폴더에 저장하는가? import와 main 실행은 어떻게 다른가? |
| 2. 데이터 | [dataset.py](dataset.py)의 `prepare_data()` | CSV 한 행이 train·validation·test 중 어디로 가고, 왜 그룹을 함께 나누는가? |
| 3. 계산 순서 | [workflows/train.py](workflows/train.py)의 `train()` | fit에는 왜 test를 주지 않으며 반환된 모델로 무엇을 하는가? |
| 4. 작은 모델 | [models/tfidf.py](models/tfidf.py)의 `select_tfidf()`·`fit()` | train에서 무엇을 학습하고 validation으로 무엇을 선택하는가? |
| 5. 신경망 | [models/transformer.py](models/transformer.py) | 배치 → loss → 가중치 갱신 → 후보 선택 → 최고 가중치 복원이 어떻게 연결되는가? |
| 6. 실행 조립·저장 | [cli/train.py](cli/train.py), [artifacts.py](artifacts.py) | 계산이 끝난 뒤 어느 시점에 파일을 쓰고 별도 평가를 실행하는가? |
| 7. 평가 | [workflows/evaluate.py](workflows/evaluate.py), [evaluation.py](evaluation.py) | 예측 라벨을 어떻게 점수와 시간 기록으로 바꾸는가? |

첫 실행은 `uv run --locked python -m classification.train_koelectra_small --preview-questions`로 입력과 분할만 확인한다. 각 단계에서는 호출자의 입력 → 함수의 반환값 → 부작용을 메모하고, [types.py](types.py)의 해당 타입만 함께 읽는다. 학습 명령은 기존 결과를 덮어쓸 수 있으므로 아래의 별도 출력 경로 예시를 따른다.

전체 학습 순서는 [workflows/train.py](workflows/train.py)의 `train()`에 있다. 준비된 분할과 학습 함수를 받아 **모델 선택 → test 예측 → 결과 반환**을 수행한다. 저장·CLI·모델 이름 분기가 없다.

1. [train_koelectra_base.py](train_koelectra_base.py)의 `CONFIG`로 모델 설정을 확인한다.
2. [cli/train.py](cli/train.py)에서 데이터·모델 구현·저장 경로를 어떻게 조립하는지 확인한다.
3. [workflows/train.py](workflows/train.py)에서 전체 계산 순서를 읽는다.
4. [models/tfidf.py](models/tfidf.py)의 `fit()`과 `select_tfidf()`로 train/validation의 역할을 이해한다.
5. [models/transformer.py](models/transformer.py)의 `fit()` → `select_transformer()` → `train_epoch()`·`predict_ids()` → `BestCheckpoint` 순서로 신경망 구현을 읽는다.
6. [workflows/evaluate.py](workflows/evaluate.py)에서 같은 예측 계약으로 로컬 모델과 Jev를 평가하는 방법을 확인한다.

[types.py](types.py)는 단계 사이에 오가는 자료를 설명한다. `DatasetSplits`는 질문 분할·분할 기록·해시, `FittedModel`은 선택된 모델의 예측 함수·선택 기록·명시적 저장 함수, `TrainingResult`는 선택 결과·test 지표·선택 시간이다. `Prediction`에는 라벨과 선택적인 확률·모델 버전·토큰 사용량이 들어간다. `EvaluationResult`에는 지표·문항별 예측·측정 기록이 들어간다.

## 구조와 책임

```text
classification/
├── cli/                 # 인자 처리, 구체 구현 조립, 저장·후속 프로세스 실행
│   ├── train.py
│   └── evaluate.py
├── workflows/           # 전달받은 학습·예측 기능으로 실험 순서 구성
│   ├── train.py
│   └── evaluate.py
├── models/              # 모델별 학습·로딩·예측·직렬화
│   ├── transformer.py
│   ├── tfidf.py
│   ├── jev.py
│   └── jev_prompt.py
├── dataset.py           # 질문 읽기·그룹 분할·기록 복원
├── artifacts.py         # 경로·실험 기록 저장 형식·파일 I/O
├── evaluation.py        # 지표 계산·시간 통계·RSS 측정
├── reporting.py         # 전달된 결과를 HTML 문자열로 표현
├── types.py             # 내부 입출력 계약과 실험 기본 시드
├── train_*.py           # 모델별 설정과 기존 학습 명령
├── model_report.py      # 기존 저장 모델 평가 명령
└── test_jev.py          # 기존 Jev 명령
```

`models/`는 구현 코드이며 `model/`은 학습된 가중치의 기존 저장 위치다. `result/`는 기존 평가 산출물이다. 과거 문서 주제 분류의 `document_split.py`는 별도 계약으로 유지한다.

의존 방향은 다음 규칙으로 제한하며 [계층 검사](../tests/test_classification_layers.py)에서 확인한다.

- CLI가 구체 모델, 데이터, workflow, 아티팩트, 보고서를 조립한다. 아래 계층은 CLI나 `train_*`·`model_report`·`test_jev`를 import하지 않는다.
- Workflow는 내부 계약과 평가 계산을 사용한다. 모델 구현·데이터 로더·아티팩트 저장·HTML·argparse·subprocess에 의존하지 않는다.
- 모델 구현끼리는 서로 import하지 않는다. Jev의 고정 프롬프트는 Jev 구현의 일부다. 공통 상속 구조는 사용하지 않는다.
- 지표·보고서는 데이터 분할이나 모델 구현을 알지 않는다. 보고서는 측정 모듈의 실행 상수 대신 전달된 표시 조건을 사용한다.

## 학습 한 번의 흐름

```text
기존 모델별 명령
  → CLI: 설정·경로 준비, CSV 분할
  → workflow: 전달받은 fit(train, validation) 호출
      → 모델 구현: 후보 학습, validation으로 선택, 최고 가중치 복원
      ← FittedModel(예측 함수, 선택 기록, 저장 함수)
  → workflow: 선택한 모델로 test 평가
  ← TrainingResult
  → CLI: 모델·학습 요약 저장
  → CLI: 별도 CPU 평가 프로세스 실행
```

학습 함수가 반환한 저장 함수는 명시적으로 호출할 때만 모델을 저장한다. 사전학습 모델을 새로 학습하는 Transformer `fit()`은 필요한 기반 모델을 다운로드할 수 있지만, 선택한 모델이나 보고서를 자동으로 저장하지 않는다. 저장이나 후속 평가 실패는 호출자에게 전달한다. 후속 평가 실패로 이미 저장된 모델을 지우거나 자동 재학습하지 않는다.

코드에서 학습 계산만 사용하려면 다음처럼 호출한다. 이 예시는 실제 TF-IDF 학습을 수행한다.

```python
from functools import partial
from classification.dataset import prepare_data
from classification.models.tfidf import TfidfConfig, fit
from classification.workflows.train import train

data = prepare_data()
result = train(data, partial(fit, config=TfidfConfig()))
print(result.test_scores["macro_f1"])
# result.fitted.save(path)는 따로 호출하기 전에는 실행되지 않는다.
```

Transformer의 입력·마스크는 `[B, L]`, 정답은 `[B]`, 출력 점수는 `[B, 3]`이다. train에서만 가중치를 수정하고 validation Macro F1으로 후보를 고른다. 동점이면 먼저 선택한 후보를 유지한다. 최고 가중치는 독립 CPU 복사본으로 보관한다. 학습 직후 test는 기존 배치 예측 조건을 유지하고, 저장 모델의 CPU 재평가는 기존 질문 한 건 단위로 실행한다.

## 평가 한 번의 흐름

```text
CLI: 저장 요약 읽기 → 기록된 질문 ID로 분할 복원 → 모델 로딩
  → evaluate_questions(질문 분할, 예측 함수, 측정 정책)
  ← EvaluationResult
  → 아티팩트 저장 → 보고서 HTML 생성·저장
```

로컬 모델은 준비 실행 3회 후 test 전체를 3회 반복 측정하고 CPU 스레드 4개를 사용한다. Jev는 validation·test에 실제 요청을 한 번씩 보내고 test 요청 시간을 기록한다. Jev에 준비 실행이나 반복 측정을 추가하지 않는다. 가중치 없는 모델을 자동 학습하거나 다운로드하는 동작은 저장 모델 평가에 없다.

Jev의 프롬프트·예시는 [models/jev_prompt.py](models/jev_prompt.py), HTTP 요청·응답 변환은 [models/jev.py](models/jev.py)에 있다. train 대표 예시의 정합성 확인과 인증·경로 준비는 실행 조립 단계에서 수행한다. 평가셋을 프롬프트 설계 때 읽었다는 기존 제한도 산출물에 유지한다.

## 실행 명령

저장소 루트에서 실행한다. 모든 기존 모델별 파일 명령과 `python -m` 실행을 유지한다. preview는 키·모델 다운로드·학습·저장 없이 분할과 입력만 확인한다. `--preview-documents`도 같은 옵션의 기존 별칭이다.

```bash
uv run --locked python classification/train_koelectra_base.py --preview-questions
uv run --locked python -m classification.train_tfidf --preview-questions
uv run --locked python -m classification.test_jev --preview-questions
```

실제 학습은 모델과 결과를 저장하고 후속 평가를 실행한다. 기존 결과를 보존하며 실행하려면 경로를 별도로 지정한다.

```bash
uv run --locked python -m classification.train_tfidf \
  --model-dir tmp/classification-run/model \
  --result-dir tmp/classification-run/result

uv run --locked python -m classification.model_report tfidf_lr \
  --model-dir tmp/classification-run/model \
  --result-dir tmp/classification-run/result
```

Transformer도 같은 경로 옵션을 지원한다. 예제 학습 파일은 `CONFIG`의 예시 모델 ID와 저장 폴더를 먼저 바꿔야 한다. 학습·평가 명령의 `--dataset`은 기본 질문 CSV 대신 사용할 파일을 지정한다. 분할 기록 복원은 당시 데이터 해시를 검사한다.

```bash
uv run --locked python classification/model_report.py koelectra_base
uv run --locked python classification/test_jev.py --evaluate
```

Jev는 `--dataset`, `--result-dir`를 지원한다. preview 이외에는 `TYPESAFE_API_KEY`와 실제 API 요청이 필요하다. 옵션 없이 실행하면 설정된 질문 한 건을 요청한다. 기존 Jev metrics에 `model_report.py jev`를 실행하면 요청 없이 HTML만 다시 만든다.

## 모델을 추가할 때

- 새로운 Transformer 모델 ID라면 기존 모델별 진입점의 설정만 추가한다. 공통 학습·workflow·평가 지표는 바꾸지 않는다.
- 새로운 로컬 알고리즘이라면 `models/`에 `fit()`·`load()`를 구현하고 CLI에서 선택·저장 경로를 연결한다. `fit()`은 `FittedModel`, 예측은 `Prediction`을 반환한다.
- 원격 API 모델은 예측 계약과 요청 단위 측정 정책을 사용한다. 로컬 학습 인터페이스를 억지로 구현하지 않는다.
- 저장 모델의 출력 번호는 해당 모델의 `id2label` 또는 `classes_`로 해석한다. 전역 라벨 순서로 덮어쓰지 않는다.

새 구현이 기존 결과 계약을 따르면 workflow·공통 지표·보고서를 수정할 필요가 없다. 기존 진입점에서 재노출한 함수를 내부 코드가 import하는 우회 경로도 만들지 않는다.

## 확인 범위

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
```

테스트는 import·preview 부작용, 분할 복원, train 전용 fit, 후보 선택·동점·최고 가중치, 전처리·라벨 매핑, 기존 결과·HTML 보존을 확인한다. 별도 계층 검사에서는 금지 import, 저장 없는 workflow, 로컬/Jev 공통 평가, API 추가 요청 금지, 저장·후속 평가 실패를 검사한다. 작은 임시 TF-IDF 데이터로 저장과 별도 평가 프로세스도 확인한다.

테스트 통과는 실제 사전학습 모델의 GPU 재학습이나 성능 재현을 의미하지 않는다. 서버 코드와 연결 방식도 변경하지 않았으며, 서버 연결은 [서버 구성 규약](../docs/server-conventions.md)을 따른다.
