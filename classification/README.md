# 질문 분류 실험

질문 하나를 `SEARCH_KNOWLEDGE`, `CLARIFY`, `UNSUPPORTED`로 분류하는 모델을 학습·평가한다. [라벨 기준](../docs/label-taxonomy.md), [데이터 안내](../data/README.md)가 각각 판정·검수·분할의 기준이다. 실행 기록은 로컬 MLflow에서 확인한다. 모델 비교의 결과·해석·결정은 [분류 실험 보고서](reports/README.md)에서 관리한다.

## 먼저 실행하기

저장소 루트에서 `uv sync --locked` 후 실행한다. 처음에는 별도 실험 폴더를 권한다.

```bash
uv run --locked sanaebi train tfidf --artifact-root tmp/my-classification-lab --preview-questions
uv run --locked sanaebi train tfidf --artifact-root tmp/my-classification-lab
uv run --locked sanaebi eval tfidf --artifact-root tmp/my-classification-lab
uv run --locked sanaebi eval tfidf --artifact-root tmp/my-classification-lab --split test
```

preview는 입력·라벨·분할 수량·그룹 중복·후보 수·선택 기준·저장 위치를 보여준다. 모델 다운로드·학습·결과 저장·MLflow 초기화를 하지 않는다.

모델 폴더가 이미 있으면 train은 **조건·무결성을 검사하지 않고** 안내 후 종료한다. 재학습은 `--force` 또는 새로운 `--artifact-root`로 명시한다. 이전 결과가 없다고 재학습하지 않는다. 명령 완료·기존 폴더 안내는 종료 코드 0, 실행 실패는 1, 잘못된 인자는 2다.

모델 이름은 `tfidf`, `bert_base`, `koelectra_base`, `koelectra_small`, `roberta_base`, `roberta_small`이다. `--dataset CSV`와 `--artifact-root DIR`를 공통 지원한다. 기본 데이터·저장 경로는 저장소 기준이며 상대 옵션 경로는 실행한 디렉터리 기준이다.

## 코드 읽는 순서

1. `pyproject.toml`의 명령 등록 → [cli/main.py](cli/main.py): 옵션을 해석하고 학습·평가를 선택한다.
2. [cli/train.py](cli/train.py)의 `execute()`: 기존 폴더 안내 또는 데이터 준비 → 학습 → 임시 저장·재로딩 검증 → 교체 → 실험 기록.
3. [dataset.py](dataset.py)의 `prepare_data()`: CSV를 읽고 그룹을 유지하며 분할한다.
4. [models/presets.py](models/presets.py) → [workflows/train.py](workflows/train.py) → [models/tfidf.py](models/tfidf.py): 설정·학습 계약·후보 선택.
5. [models/transformer.py](models/transformer.py): `fit()` → `select_transformer()` → `train_epoch()`·`predict_ids()` → `BestCheckpoint`.
6. [cli/evaluate.py](cli/evaluate.py) → [workflows/evaluate.py](workflows/evaluate.py): 저장된 분할 복원·예측·지표·시간 측정.
7. 필요할 때 [storage.py](storage.py)의 저장 보호와 [tracking.py](tracking.py)의 MLflow 기록을 읽는다.

```text
CLI → 데이터·설정 준비 → workflow → 모델별 계산
                      ↓
             모델/결과 저장 → MLflow 기록
```

`models/`와 `workflows/`는 MLflow·HTML·CLI를 참조하지 않는다. `FittedModel`은 예측·저장 함수와 설정, `SelectionResult`는 선택 모델·validation 점수·선택 시간을 담는다. `DatasetSplits`는 문항·분할 기록·분할 해시를 담는다. 상세 계약은 [types.py](types.py)에 있다.

`experiments/`는 기존 실행 진입점, `legacy/`는 과거 형식의 호환 경계다. `evaluation/metrics.py`는 지표 계산, `evaluation/reporting.py`는 과거 HTML 재출력용이다. 신규 실행은 자체 HTML·비교 페이지를 생성하지 않는다.

## 학습과 평가의 경계

TF-IDF 어휘·IDF는 train에만 맞추고 validation으로 C 후보를 선택한다. Transformer 입력·마스크는 `[B, L]`, 정답은 `[B]`, 출력은 `[B, 3]`이다. train에서만 가중치를 갱신하고 validation Macro-F1으로 후보·epoch를 선택한다. 동점은 먼저 선택한 후보를 유지하고 최고 가중치는 독립 복사·복원한다. 저장 모델의 출력 번호는 해당 모델의 `id2label`·`classes_`로 해석한다.

학습 workflow는 train/validation만 받으며 선택 모델의 validation 지표를 반환한다. 신규 학습 요약에 test 점수를 생성하지 않는다. eval 기본값은 validation만이며 `--split test`는 test만 평가한다. `both`는 현행 로컬 평가에서 지원하지 않는다. 속도 측정도 선택 분할에서 준비 3회·반복 3회, CPU 스레드 4개로 수행한다.

현재 test는 이미 열람한 개발 자료다. `--split test`가 미열람 최종 평가를 뜻하지 않는다. 합성·AI 검수 데이터의 결과를 실제 직원 질문 성능이나 사람 승인으로 해석하지 않는다.

현재 층화 그룹 분할은 20개 fold를 14/3/3으로 합치며 632/133/135건이다. 기존 모델은 저장된 문항 ID로 당시 분할을 복원한다. 서로 다른 분할의 지표를 같은 실험으로 비교하지 않는다.

KoELECTRA small의 길이 후보는 `(256,)`이다. 현재 900건의 해당 tokenizer 최대 65토큰 관측에 따른 설정이며 미래 질문에 대한 보장은 아니다. 다른 모델 설정은 유지한다. 기존 모델을 자동 재학습하지 않는다.

## MLflow에서 확인하기

실행 시 `<artifact-root>/tracking/mlflow.db`에 직접 기록하므로 학습할 때 서버를 켤 필요가 없다. 위 예제 폴더를 보려면 저장소 루트에서 실행한다.

```bash
MLFLOW_DISABLE_TELEMETRY=true uv run --locked mlflow server \
  --backend-store-uri sqlite:///tmp/my-classification-lab/tracking/mlflow.db \
  --host 127.0.0.1 --port 5050 --workers 1 --no-serve-artifacts
```

브라우저에서 http://127.0.0.1:5050 을 열고 `Model training` → `classification` 실험을 선택한다. 기본 저장소를 사용했다면 DB 경로는 `sqlite:///artifacts/tracking/mlflow.db`다. 다른 디렉터리에서 UI를 실행할 때는 DB 절대 경로를 사용한다. 산출물의 로컬 절대 경로를 기록하므로 폴더를 이동하면 원래 위치의 링크가 자동 수정되지 않는다. DB와 tracking 산출물 폴더를 함께 보관한다. Windows에서는 환경변수 설정 문법을 셸에 맞게 적용한다.

- validation 비교 필터: `tags.kind = 'eval' AND tags.split = 'validation'`. 성공한 run끼리 비교한다.
- 같은 `dataset_sha256`, `split_id`, `measurement_policy`를 선택하고 `environment.json`도 확인한다. UI가 다른 조건의 비교를 자동 차단하지는 않는다.
- `model_name`은 모델 이름, `model_id`는 저장 모델 묶음 식별자, `training_run_id`는 해당 학습 실행이다. 구형 모델은 학습 run ID가 없을 수 있다.
- 학습은 설정·선택 validation 지표·시간, 후보별 epoch 곡선과 `trials.csv`를 기록한다. 기록은 완료 후 일괄 생성하며 실시간 곡선이 아니다.
- 평가는 선택 분할 지표·라벨별 지표·측정 시간, `metrics.json`의 혼동행렬·오분류, `predictions.json`을 기록한다.
- 과거 모델 평가의 기록도 앞으로 실제 실행한 평가 run부터 생성한다. 과거 학습 이력을 추정하거나 일괄 이관하지 않는다.

새 재학습은 새 model_id를 만든다. MLflow에는 이전 run도 남으므로 모델 위치가 같다는 이유로 과거 run의 모델이라고 생각하지 않는다. **가중치는 MLflow에 중복 업로드하지 않으며 현재 모델과 직전 백업만 유지한다.** 모든 과거 run의 가중치를 영구 보존하려면 실험별 `--artifact-root`를 사용한다.

MLflow 기록 실패를 숨기지 않는다. 초기화 실패는 학습·외부 요청 전에 중단한다. 로컬 저장 후 추적 기록이 실패하면 저장 경로와 미완료 상태를 알리고 종료 코드 1을 반환한다. 이미 저장된 모델을 자동 재학습하지 않으며 결과 파일을 먼저 확인한다. 다음 eval은 새 평가 run이다. 실패한 과거 run 자동 복구나 중복 실행은 하지 않는다.

공식 참고: [로컬 SQLite Tracking](https://www.mlflow.org/docs/latest/ml/tracking/tutorials/local-database/), [Tracking Quickstart](https://www.mlflow.org/docs/latest/ml/getting-started/quickstart/). autolog·레지스트리·원격 배포는 사용하지 않는다.

## 저장과 기존 모델 호환

```text
<artifact-root>/
├── models/<모델명>/              # 가중치 + training_summary.json + manifest.json
├── results/<모델명>/validation/  # metrics.json + predictions.json
├── results/<모델명>/test/        # 명시적 test 결과
├── tracking/mlflow.db            # 실행·설정·지표
├── tracking/artifacts/           # run별 JSON·CSV 등, 가중치 제외
├── .staging/                     # 임시 저장, 중단 흔적은 수동 확인
├── .backup/                      # 직전 모델·평가 결과
└── .locks/                       # 모델별 OS 잠금
```

버전 2 manifest는 모델명·완료 상태·생성 시각·model_id·학습 run ID만 기록한다. model_id는 무결성 인증이 아닌 식별자다. 소스 파일별 해시·자동 재사용 fingerprint·전체 파일 해시 검사는 제거했다. 데이터 SHA와 분할 ID는 평가 자료 일치를 위해 유지한다. 설정·분할·선택 기록은 `training_summary.json`, 환경·코드 버전은 MLflow에 남긴다.

버전 1 manifest는 원본을 바꾸지 않고 기존 model_id로 읽는다. 평가에서는 필수 파일·메타데이터·라벨·데이터 SHA와 실제 모델 로딩을 검사한다. 잠재적인 모든 파일 손상을 사전에 검출하는 방식은 아니다. Transformer는 저장 후 재로딩을 확인하며 새 학습의 기반 모델·tokenizer revision SHA를 함께 고정한다.

저장 시 임시 폴더에서 완성·재로딩 검증 후 교체한다. 교체 예외는 기존 폴더를 복원한다. 강제 종료 후에는 자동 복구하지 않는다. `.staging`의 해당 작업 흔적·구형 journal이 발견되면 파일을 보존하고 중단한다. 실행 중인 작업이 없는지 확인하고, 최종 모델·임시 폴더·`.backup` 중 사용할 묶음을 확인한 뒤 나머지는 별도 위치로 옮긴다. 불확실한 폴더를 삭제하거나 가중치를 재학습으로 대체하지 않는다.

`runs/`와 기존 결과·HTML은 보존한다. 이전 small 채택은 서버 최종 모델 선정이 아니다. 현재 서버 연결은 [서버 규약](../docs/server-conventions.md)을 따른다. 산출물·SQLite·모델을 통째로 Git에 넣지 않는다.

## Jev와 과거 진입점

`sanaebi-train MODEL`과 `experiments/train_*.py`도 같은 명시적 재학습 정책을 사용한다. 사용자 정의 모델 설정은 `train_example.py`를 참고한다.

```bash
uv run --locked python -m classification.experiments.evaluate_jev --preview-questions
uv run --locked --env-file .env python -m classification.experiments.evaluate_jev --evaluate --artifact-root tmp/my-classification-lab
```

Jev 실제 평가는 `TYPESAFE_API_KEY`가 필요하다. 위 예시는 Git 제외 로컬 `.env`의 값을 uv로 전달한다. 이미 환경변수로 설정했다면 `--env-file .env`를 생략할 수 있다. 기존대로 train 대표 예시 12개를 사용하고 validation/test 합계 268회 요청한다. test 요청 시간만 측정하며 준비·반복 요청을 추가하지 않는다. MLflow에서 `split=both`로 표시해 로컬 validation 전용 run과 구분한다. preview·단건 확인은 MLflow run을 만들지 않는다. 신규 Jev 결과는 기본 `<artifact-root>/results/jev/`이며 `--result-dir`도 호환 지원한다.

`evaluate_saved`의 기본 로컬 평가는 현행 저장소의 validation이다. 과거 `--model-dir`·`--result-dir` 방식은 구형 두 분할 평가 계약을 유지한다. 새로 실행한 구형 로컬 평가는 `kind=eval_legacy`, `split=both`로 결과 디렉터리의 부모 아래 tracking에 기록하고 HTML을 생성하지 않는다. 저장된 과거 API 결과의 HTML 재출력도 유지한다. 구형 명령에는 현행 `--split`을 혼용하지 않는다.

## 검증

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/validate_dataset.py
```

분할 복원·학습/test 경계·checkpoint 선택·라벨 매핑·preview 무부작용·저장 실패 보호·구형 모델 읽기와 실제 임시 SQLite 기록을 검사한다. TF-IDF 명령 전체 흐름은 작은 임시 데이터로, Transformer 계약은 대체 모델로 확인한다. 테스트 통과는 실제 Transformer 재학습·성능 재현·서버 모델 변경을 뜻하지 않는다.
