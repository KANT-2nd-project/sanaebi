# 분류 직접 구현

질문 하나를 3개 처리 경로로 분류하는 학습 공간이다. 기존 구현·보고서는 [아카이브](../archive/classification_v1/README.md)에 보존했다. 기존 `sanaebi` 명령은 계속 아카이브를 실행한다. 학습 명령은 서버 설정을 자동으로 바꾸지 않는다. 서버는 별도로 선정·설정한 저장본을 사용하며, 로딩과 예측 흐름은 [서버 분류기 추론](../app/classification/README.md)에서 설명한다.

## 현재 진행

데이터 읽기·검증·그룹 분할, TF-IDF 학습·validation 오류 확인을 함께 진행했다. 사용자 요청에 따라 C 후보 선택과 아래 저장·명시적 평가 기능은 AI가 구현·실행 검증했다. 이 부분을 사용자 독립 구현·숙달로 기록하지 않는다. 이후 사용자 위임으로 7~8단계 Transformer 한 배치·학습·선택·저장·평가도 AI가 구현했다. 2026-10-15 새 로컬 6종 학습·저장·평가를 완료했고, 별도 Jev API 결과와 7종 비교를 정리했다. MLflow 연결은 9단계이며 새 구현에는 아직 없다.

읽는 순서는 [dataset.py](dataset.py) → [tfidf.py](tfidf.py)의 `select_model` → [persistence.py](persistence.py)의 `save_bundle` → [evaluate.py](evaluate.py)의 `evaluate_bundle`이다.

- 입력은 question만 사용한다. 그룹을 유지한 train/validation/test는 현재 데이터에서 632/133/135건이다.
- `select_model`은 train/validation만 받고 C 후보를 validation Macro-F1으로 선택한다. 동점이면 앞선 후보를 유지한다.
- 학습된 TF-IDF와 선택 분류기를 Pipeline으로 묶는다. 선택 후 다시 fit하지 않는다.
- `model.joblib`와 `metadata.json`을 임시 폴더에 저장하고 재로딩 예측을 확인한 뒤 새 폴더로 이동한다. 로컬에서 신뢰할 수 있는 모델 파일만 로딩한다.
- 메타데이터에는 설정·trial·라벨 순서·데이터 SHA·분할 문항 ID·split_id·model_id·환경·코드 기준을 남긴다. model_id는 식별자이며 파일 무결성 인증이 아니다. Git dirty이면 commit만으로 정확한 실행 코드가 재현되지 않는다.
- 평가에서는 저장된 문항 ID를 복원한다. 기본 validation, 명시적 test만 예측한다. 데이터 전체의 메타데이터 정합성을 읽는 것과 test 예측은 구별한다.
- 현재 test는 이미 열람한 합성 개발 자료다. test 점수를 미열람 최종 성능·실서비스 성능으로 설명하지 않는다.

## 실행

저장소 루트에서 실행한다. 아래 output은 새 경로여야 하며 기존 경로가 있으면 덮어쓰지 않고 종료한다. `--output` 생략 시 학습·평가는 실행하지만 파일은 저장하지 않는다.

```bash
uv run --locked python -m classification.tfidf \
  --output artifacts/experiments/learning-my-run/model

uv run --locked python -m classification.evaluate \
  artifacts/experiments/learning-my-run/model \
  --output artifacts/experiments/learning-my-run/results/validation

# 개발 test가 필요한 때에만 명시적으로 실행
uv run --locked python -m classification.evaluate \
  artifacts/experiments/learning-my-run/model --split test \
  --output artifacts/experiments/learning-my-run/results/test
```

평가 결과는 지정한 새 output 폴더의 `metrics.json`, `predictions.json`이다. 두 결과의 model_id·split_id로 같은 모델·자료인지 확인한다. 모델이 없으면 자동 학습하지 않는다. 이전 학습과 같은 CSV를 `--dataset`으로 전달할 수 있다.

C를 더 크게 탐색할 때는 validation 실험으로 실행한다. 기본 후보 목록은 그대로 유지한다.

```bash
uv run --locked python -m classification.tfidf --candidates 10 30 100 300 1000
```

같은 validation에 반복해서 맞춘 최고 점수는 독립적인 성능 추정치가 아니다. 별도의 실무 평가 자료·모델 선정은 후속이다.

동일 목적지에 대한 쓰기는 배타적인 `.이름.lock` 파일로 보호한다. 예외 발생 시 임시 폴더를 정리하고 기존 경로는 보존한다. 강제 종료 후 자동 복구는 제공하지 않는다. 남은 lock/임시 폴더가 있으면 실행 중인 작업이 없는지와 자료를 먼저 확인하고 수동으로 처리한다. 아카이브 저장 형식과의 호환·기존 폴더 교체는 제공하지 않는다.

## 확인

```bash
uv run --locked python scripts/validate_dataset.py
uv run --locked python -m unittest discover -s tests -p test_learning_classification.py
```

저장·재로딩 일치, 기존 모델·결과 보존, 실패 시 미게시, 분할별 평가·결과 공존, 잘못된 데이터·분할 거부, 동점 선택을 검사한다. 실제 학습 자료·가중치·MLflow는 기존 위치에 보존하며 새 결과는 별도 실험 경로에 둔다.

## Transformer 학습

`transformer.py`는 `select_model`의 배치 학습 → epoch별 validation → 최고 상태 복원 순서로 읽는다. 학습률 후보마다 초기 모델을 다시 로딩한다. 선택 기준은 validation Macro-F1이며 동점이면 먼저 선택한 후보·epoch를 유지한다. 최고 가중치는 CPU에 복사하여 이후 학습의 영향을 받지 않게 한다.

```bash
uv run --locked python -m classification.transformer \
  --epochs 3 --batch-size 4 --learning-rates 2e-5 5e-5 \
  --output artifacts/experiments/learning-transformer-my-run/model

uv run --locked python -m classification.evaluate \
  artifacts/experiments/learning-transformer-my-run/model \
  --output artifacts/experiments/learning-transformer-my-run/results/validation
```

기본 모델은 `klue/roberta-small`, 최대 길이는 256, 실행 장치는 CPU다. CUDA 환경에서는 `--device cuda`로 지정한다. `--revision`으로 원본 모델 버전을 고정할 수 있다. 위 명령은 실제 전체 train 학습을 실행하며, 모델 다운로드가 필요할 수 있다.

tokenizer는 질문을 `[B, L]` 토큰 번호·마스크로, 라벨 매핑은 정답을 `[B]` 정수로 바꾼다. 모델 출력은 `[B, 3]` logits다. 학습에서 `zero_grad → forward/loss → backward → step`을 반복하고, validation에서는 `eval()`과 `no_grad()`를 사용한다. test는 학습 함수에 전달하지 않는다.

저장 형식은 Hugging Face 모델·tokenizer와 `metadata.json`이다. 임시 폴더에 저장하고 validation 질문 최대 4개의 재로딩 예측 일치를 확인한 뒤 새 경로로 옮긴다. 기존 폴더는 덮어쓰지 않는다. 평가 명령은 TF-IDF와 동일하며 `--split test`는 명시했을 때만 test를 예측한다. 학습률·epoch trial과 선택 상태는 metadata에 남는다. MLflow 연결은 아직 후속 9단계다.

검증은 실제 RoBERTa 한 배치 가중치 갱신과 작은 로컬 Transformer의 후보 선택·동점·checkpoint 복사·저장 복원·분할별 평가로 수행했다. 작은 모델 검증 점수는 프로젝트 성능 결과가 아니다.

## 실험 기록

[실험 보고서 목록](reports/README.md)에서 실행 조건·지표·오분류를 확인한다. 2026-10-15 [7종 통합 비교](reports/2026-10-15-seven-model-comparison/README.md)를 완료했다. Jev는 보존된 API 실행 코드를 사용했고, 로컬 6종은 새 학습 코드로 실행했다. 상세 설정·평가·원자료 위치는 각 보고서에 있다.

## 분할을 유지하는 보강 학습과 외부 진단

`--split-manifest`를 지정하면 기존 문항 ID 순서와 그룹 경계를 복원한다. CSV에 문항을 추가한 뒤 같은 seed로 다시 분할하는 방식은 기존 validation/test를 보존하지 않는다. manifest에는 `schema_version: 1`, `dataset_sha256`, `question_ids`(train/validation/test)가 필요하다. 누락·중복·미배정 ID·분할 간 그룹 중복·잘못된 라벨·해시 불일치는 학습 전에 거부한다. 생략하면 기존 그룹 분할을 사용한다. 새 metadata의 `split_manifest_sha256`은 부가 기록이며 이전 저장본도 계속 읽는다.

외부 질문은 `python -m classification.diagnostic_evaluation 모델폴더 --cases 질문.json --output 새결과폴더`로 평가한다. 질문은 id·group_id·question·expected_label·source·pure_lookup_execution을 가진 JSON 배열이다. 서버의 CPU 추론기를 사용하고 지표와 원문별 예측을 보존한다. 학습·재시도·기존 결과 덮어쓰기는 하지 않는다.

[2026-10-15 보강 학습](reports/2026-10-15-routing-augmentation/README.md)은 1회 실행 후 회귀 40/48·새 평가 29/30을 확인했지만, 사전 기준 미달과 퇴행으로 서버 승격을 보류했다. 기존 서버 모델은 유지한다. [고정 자료와 실제 실행 명령](benchmarks/routing-augmentation-2026-10-15/README.md)을 참고하며 이미 완료한 학습을 자동 재실행하지 않는다.
