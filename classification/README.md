# 질문 분류 실험

질문 분류 모델의 학습과 평가를 실행한다. [라벨 기준](../docs/label-taxonomy.md)과 [데이터 안내](../data/README.md)는 각 정보의 기준 문서다. 공통 라벨은 [contracts/classification.py](../contracts/classification.py)에서 가져온다.

## 먼저 읽을 코드

학습은 `sanaebi train 모델명`으로 실행한다. `experiments/train_*.py`는 같은 공통 설정과 CLI를 호출하는 기존 실행 진입점이다. 실제 학습 구현은 `models/`에서 읽는다.

먼저 `dataset.prepare_data()`로 질문·분할을 확인하고, 아래 세 곳에서 설정 → 실행 조립 → 학습 계산을 읽는다.

1. [models/presets.py](models/presets.py)의 `CONFIGS`: 선택한 모델 이름에 연결된 설정을 확인한다.
2. [cli/train.py](cli/train.py)의 `execute()`: 데이터 준비 → preview 또는 재사용 검사 → 학습 → 임시 저장·검증 → 모델 교체 순서가 한곳에 있다. 옵션은 [cli/main.py](cli/main.py)에서 한 번 읽는다.
3. [workflows/train.py](workflows/train.py)의 `train()`: 전달된 `fit(train, validation)`으로 모델을 선택하고 validation 예측·점수를 반환한다. train과 validation 행만 받으며 test에는 접근하지 않는다. 이 함수는 저장 없이 계산만 재사용할 때도 쓴다.

```text
sanaebi train → execute
               ├─ 데이터 준비 → preview면 종료
               ├─ train → 모델 fit → 선택 checkpoint의 validation 평가
               └─ 모델·요약 임시 저장 → 로컬 재로딩 검증 → 게시
sanaebi eval  → validation CPU 평가 → 분할별 결과·보고서 게시
             → --split test를 명시하면 test만 평가
```

첫 실행은 `uv run --locked sanaebi train koelectra_small --preview-questions`로 입력과 분할만 확인한다. 각 함수에서는 입력·반환값·부작용을 메모한다. 같은 조건의 정상 모델은 재사용하며, 명시적인 `--force`만 재학습한다.

전체 흐름을 이해한 뒤 [dataset.py](dataset.py)의 `prepare_data()`로 데이터 분할을, [models/tfidf.py](models/tfidf.py)의 `fit()`·`select_tfidf()`로 후보 선택을 읽는다. 이후 [models/transformer.py](models/transformer.py)의 `fit()` → `select_transformer()` → `train_epoch()`·`predict_ids()` → `BestCheckpoint`로 신경망 학습을 살펴본다. 평가·저장·HTML 구현은 필요할 때 각각 `workflows/evaluate.py`·`artifacts.py`·`evaluation/reporting.py`에서 확인한다.

[types.py](types.py)는 단계 사이에 오가는 자료를 설명한다. `DatasetSplits`는 질문 분할·분할 기록·해시, `FittedModel`은 선택된 모델의 예측 함수·선택 기록·명시적 저장 함수, `SelectionResult`는 선택 결과·validation 지표·선택 시간이다. `Prediction`에는 라벨과 선택적인 확률·모델 버전·토큰 사용량이 들어간다. `EvaluationResult`에는 지표·문항별 예측·측정 기록이 들어간다.

## 구조와 책임

```text
classification/
├── experiments/         # 사용자 실행 진입점: 모델 설정·학습·평가 명령
│   ├── train_*.py       # 6개 모델 학습 명령과 train_example.py
│   ├── evaluate_saved.py
│   └── evaluate_jev.py
├── cli/                 # 옵션·구체 구현·저장 조립
│   ├── main.py           # sanaebi 하위 명령의 인자 처리
│   ├── train.py
│   ├── evaluate.py      # 현행 로컬 단일 분할 평가
│   └── jev.py           # 기존 Jev 실행 조립
├── workflows/           # 저장 없는 학습·평가 계산 흐름
│   ├── train.py
│   └── evaluate.py
├── models/              # 모델별 학습·로딩·예측·직렬화
│   ├── presets.py        # CLI가 공유하는 설정·로더 조립
│   ├── transformer.py
│   ├── tfidf.py
│   ├── jev.py
│   └── jev_prompt.py
├── evaluation/          # 평가 결과 계산·표현
│   ├── metrics.py
│   ├── reporting.py     # HTML 렌더링
│   └── comparison.py    # 유효 validation 결과 수집·게시
├── legacy/              # 과거 형식의 호환 경계
│   ├── evaluate.py      # 구형 로컬 모델·저장 API 결과
│   └── document_split.py
├── dataset.py           # 질문 읽기·그룹 분할·기록 복원
├── artifacts.py         # 기존 경로·파일 읽기/쓰기·직렬화
├── storage.py           # manifest·재사용 조건·잠금·복구 가능한 교체
├── types.py             # 단계 간 내부 계약
└── result/              # 기존 평가 산출물
```

`models/`는 구현 코드이며 `model/`은 학습된 가중치의 기존 저장 위치다. `result/`는 기존 평가 산출물이다. 과거 문서 주제 분류 코드는 [legacy 안내](legacy/README.md)의 별도 계약으로 유지한다.

의존 방향은 다음 규칙으로 제한하며 [계층 검사](../tests/test_classification_layers.py)에서 확인한다.

- CLI가 구체 모델, 데이터, workflow, 아티팩트, 보고서를 조립한다. 아래 계층은 CLI나 `experiments/`의 실행 진입점을 import하지 않는다.
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
  → workflow: 선택한 모델로 validation 평가
  ← SelectionResult
  → CLI: 임시 저장 → 재로딩·단건 예측·해시 검증 → 모델 교체
  → 종료 (저장 모델 CPU 평가는 별도 sanaebi eval 명령)
```

학습 함수가 반환한 저장 함수는 명시적으로 호출할 때만 모델을 저장한다. 사전학습 모델을 새로 학습하는 Transformer `fit()`은 필요한 기반 모델을 다운로드할 수 있지만, 선택한 모델이나 보고서를 자동으로 저장하지 않는다. 저장 실패는 호출자에게 전달하며 기존 정상 모델을 보존한다. 별도 평가가 실패해도 모델과 직전 평가 결과를 보존하고 자동 재학습하지 않는다.

코드에서 학습 계산만 사용하려면 다음처럼 호출한다. 이 예시는 실제 TF-IDF 학습을 수행한다.

```python
from functools import partial
from classification.dataset import prepare_data
from classification.models.tfidf import TfidfConfig, fit
from classification.workflows.train import train

data = prepare_data()
result = train(
    data.rows["train"], data.rows["validation"], partial(fit, config=TfidfConfig())
)
print(result.validation_scores["macro_f1"])
# result.fitted.save(path)는 따로 호출하기 전에는 실행되지 않는다.
```

Transformer의 입력·마스크는 `[B, L]`, 정답은 `[B]`, 출력 점수는 `[B, 3]`이다. train에서만 가중치를 수정하고 validation Macro F1으로 후보를 고른다. 동점이면 먼저 선택한 후보를 유지한다. 최고 가중치는 독립 CPU 복사본으로 보관한다. 선택 checkpoint의 validation을 배치로 채점한다. 저장 모델 CPU 평가는 지정 분할의 질문 한 건 단위로 실행한다. 신규 학습 요약에 test 점수를 생성하지 않으며 과거 요약의 test 필드는 읽기 호환만 유지한다.

## 평가 한 번의 흐름

```text
CLI: 저장 요약 읽기 → 기록된 질문 ID로 분할 복원 → 모델 로딩
  → evaluate_questions(질문 분할, 예측 함수, 측정 정책, split="validation" 또는 "test")
  ← EvaluationResult
  → 아티팩트 저장 → 보고서 HTML 생성·저장
```

현행 로컬 모델은 지정한 분할을 한 번 채점하고 준비 실행 3회 후 같은 분할 전체를 3회 반복 측정하고 CPU 스레드 4개를 사용한다. Jev는 validation·test에 실제 요청을 한 번씩 보내고 test 요청 시간을 기록한다. Jev에 준비 실행이나 반복 측정을 추가하지 않는다. 가중치 없는 모델을 자동 학습하거나 다운로드하는 동작은 저장 모델 평가에 없다.

Jev의 프롬프트·예시는 [models/jev_prompt.py](models/jev_prompt.py), HTTP 요청·응답 변환은 [models/jev.py](models/jev.py)에 있다. train 대표 예시의 정합성 확인과 인증·경로 준비는 실행 조립 단계에서 수행한다. 평가셋을 프롬프트 설계 때 읽었다는 기존 제한도 산출물에 유지한다.

## 결과를 해석할 때

보고서 첫 화면은 model_id, 데이터 SHA·분할 해시, 입력, 평가 분할·용도, 데이터 검수·test 열람 상태를 표시한다. 기록이 없는 항목은 미기록이다. 현재 900건 자료는 알려진 CSV 해시와 일치할 때만 합성·AI 검수·사람 승인 0건, 이미 열람한 개발 평가 자료로 표시한다. 새 CSV에 이 설명을 자동 적용하지 않는다.

`--split test`를 실행했다고 미열람 최종 평가가 되는 것은 아니다. 기존 test는 이미 열람한 개발 자료이며 최종 선정용 새 평가가 필요하다. 구조 변경은 정확도 개선이나 모델 선정 완료를 뜻하지 않는다.

## 실행 명령과 저장

`uv sync --locked`로 프로젝트 가상환경에 `sanaebi` 명령을 설치한다. 가상환경이 활성화되어 있으면 아래처럼 실행한다. 활성화하지 않았다면 명령 앞에 `uv run --locked`를 붙인다.

```bash
sanaebi train koelectra_small --preview-questions
sanaebi train koelectra_small
sanaebi eval koelectra_small                 # validation만
sanaebi eval koelectra_small --split test    # test 명시
sanaebi train koelectra_small --force
```

preview는 입력·라벨·분할 수량·그룹 교집합·후보 수·epoch·선택 기준·저장 위치·test 미평가를 보여주며 다운로드와 저장을 하지 않는다.

KoELECTRA small은 현재 자료의 최대 65토큰 진단을 근거로 길이 후보를 `(256,)`으로 줄였다. 다른 모델 설정은 유지한다. 설정과 학습 코드가 바뀌었으므로 기존 모델의 train 재사용은 조건 불일치가 날 수 있다. 자동 재학습하지 않으며 기존 가중치의 eval은 가능하다. 새 학습은 별도 `--artifact-root`로 격리하는 것을 권한다.

모델 이름은 `bert_base`, `koelectra_base`, `koelectra_small`, `roberta_base`, `roberta_small`, `tfidf`다. `--dataset CSV`와 `--artifact-root DIR`는 train·eval에서 공통으로 사용한다. 기본 경로는 저장소 기준 절대 경로이므로 외부 작업 폴더에서도 동일한 자료를 찾는다. 상대 옵션 경로는 호출한 작업 폴더 기준이다. 예를 들어 작은 별도 데이터는 `sanaebi train tfidf --dataset tmp/questions.csv --artifact-root tmp/experiment`로 격리한다.

```text
artifacts/                       # Git 제외, 모델별 현재 묶음
├── models/<모델명>/              # 가중치·토크나이저 또는 model.joblib
│                                # training_summary.json + manifest.json
├── results/<모델명>/validation/  # metrics.json·predictions.json·report.html
├── results/<모델명>/test/        # 명시적 test 평가 결과 (별도 보존)
├── results/comparison.html       # 같은 조건의 유효 결과끼리 비교
├── .staging/                    # 저장 중 자료·교체 복구 기록
├── .backup/models/<모델명>/       # 직전 정상 모델
├── .backup/results/<모델명>/<분할>/ # 분할별 직전 평가 결과
└── .locks/                      # OS 배타 잠금 파일
```

- **train**: 모델이 없으면 학습한다. 파일 해시와 요청 조건이 일치하면 학습을 생략한다. 평가 결과가 없다는 이유로 재학습하지 않는다. 조건 불일치·불완전 저장은 오류와 `--force` 안내를 반환한다.
- **force**: 새 학습·저장·로컬 로딩·단건 예측 검증이 성공해야 교체한다. 실패하면 기존 모델을 보존한다. 손상된 구형 묶음은 `.staging/previous-*`에 남기고 정상 백업을 덮어쓰지 않는다.
- **eval**: 기본 validation만 평가한다. `--split test`는 test만 평가하며 `both`는 지원하지 않는다. 두 분할은 별도 경로에 저장해 서로 덮지 않는다. 없거나 손상되면 train 명령을 안내하며 자동 학습하지 않는다. train은 별도 CPU 평가를 자동 실행하지 않는다.
- **종료 코드**: 완료·스킵 0, 실행 실패 1, 잘못된 명령·인자 2다. 교체 직후 비교 페이지 생성 등이 실패하면 모델 저장은 유지되며 명령은 실패를 반환한다.

manifest는 완료 상태, 파일 해시, 묶음 식별값, 데이터·분할·라벨·전처리와 전체 후보 설정·시드·학습 관련 코드·라이브러리·장치를 기록한다. 경로·실행 시각·UI·HTML은 재사용 판단에서 제외한다. 새 Transformer 학습은 기반 모델과 토크나이저에 같은 revision SHA를 전달하고 기록한다. help·preview·정상 스킵에는 원격 조회나 다운로드가 없다. preview 별칭 `--preview-documents`도 유지한다.

모델과 평가 결과는 `model_id`로 연결한다. 모델 교체 후 이전 결과 파일은 보존하지만 현재 모델의 비교 대상에서 제외한다. 기본 비교는 validation만 표시하고 데이터·분할·라벨·측정 정책·평가 환경·결과 형식이 같은 결과끼리 묶는다. 새 validation 결과가 있으면 이를 우선하고, 없을 때만 과거 분할 미구분 metrics의 validation을 읽는다. 과거 파일은 이동하거나 삭제하지 않는다. 평가 시간과 환경이 다른 과거 결과는 현재 비교에 섞지 않는다. 같은 시드만으로 컴퓨터 간 동일한 학습 결과를 보장하지 않는다.

원 실행 `runs/koelectra_small/20261014T074121Z-abcd0686`의 small 모델을 해시·분할·예측 대조 후 채택했다. 과거에 기록하지 않은 환경·코드·기반 revision은 미확인으로 남기고, 이전 시점의 조건을 별도 재사용 기준으로 기록한다. 따라서 스킵은 과거 학습 환경의 인증이 아니다. 원본 `runs/`, 재현성 확인 실행, `classification/result/`의 역사 결과는 보존한다. 이 small 채택은 서버 모델 선정·연결을 의미하지 않는다.

### 공유할 실험 결과

`artifacts/results/`는 eval마다 갱신되는 로컬 산출물이므로 모델과 함께 Git에서 제외한다. 팀이 검토할 확정 결과는 별도 실험 기록으로 선별해 보관한다. 데이터 해시·분할·설정·환경·model_id·지표·모델 보관 위치를 함께 남기고, 현재 실행 폴더 전체를 커밋하지 않는다. 기존 `classification/result/`는 역사 기록으로 유지한다. Gitignore와 직전 백업 하나는 장기 보관을 대신하지 않는다.

### 기존 명령에서 전환

`sanaebi-train MODEL`과 `experiments/train_*.py`의 파일·모듈 명령도 새 저장·재사용 정책을 호출한다. 예제 `train_example.py`만 사용자 정의 설정을 작성한다. 이전 `--runs-dir`, 학습의 `--model-dir`·`--result-dir` 대신 `--artifact-root`를 사용한다. 기본 실행마다 새 runs 폴더를 만들지 않는다.

```bash
uv run --locked python -m classification.experiments.train_koelectra_small --preview-questions
uv run --locked python -m classification.experiments.evaluate_saved koelectra_small
uv run --locked python -m classification.experiments.evaluate_jev --preview-questions
```

`evaluate_saved`의 기본 로컬 평가는 새 저장소의 validation을 사용하며 `--split test`를 지원한다. 구형 형식 명령에는 `--split`을 지원하지 않고 기존 두 분할 평가 의미를 유지한다. 과거 저장 형식을 읽어야 할 때만 `--model-dir`·`--result-dir`를 명시한다. 기존 API 결과의 HTML 재생성도 이 명령에서 지원한다. Jev 실제 평가는 기존 `--evaluate`와 `TYPESAFE_API_KEY`가 필요하며 외부 요청을 수행한다. Jev는 로컬 학습 모델 목록에 넣지 않는다.

## 모델을 추가할 때

- 새로운 Transformer 모델 ID라면 `CONFIGS`에 이름과 설정을 추가한다. 공통 학습·workflow·평가 지표는 바꾸지 않는다.
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

테스트는 import·preview 부작용, 분할 복원, train 전용 fit, 후보 선택·동점·최고 가중치, 전처리·라벨 매핑, 기존 결과 파일 보존·새 HTML 의미을 확인한다. 별도 계층 검사에서는 금지 import, 저장 없는 workflow, 로컬/Jev 공통 평가, API 추가 요청 금지, 저장·평가 실패를 검사한다. 작은 임시 TF-IDF 데이터로 설치된 train → 스킵 → validation → test → force 명령과 백업을 확인한다. 모델 무결성·동시 실행 차단·교체 복구도 임시 저장소에서 검사한다.

테스트 통과는 실제 사전학습 모델의 GPU 재학습이나 성능 재현을 의미하지 않는다. 서버 코드와 연결 방식도 변경하지 않았으며, 서버 연결은 [서버 구성 규약](../docs/server-conventions.md)을 따른다.
