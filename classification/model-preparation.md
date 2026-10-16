# 서버용 분류 모델 준비

[서버 실행 준비](../app/README.md#실행-준비와-api-확인)에서 사용하는 분류 저장본을 확보하는 방법입니다. 가중치는 Git에 없으며 현재 선정 저장본의 공개 다운로드는 제공하지 않습니다. 아래 두 경로 중 하나를 사용합니다. 명령은 저장소 루트의 Bash에서 실행합니다.

## 권한이 있는 팀원: 선정 저장본 확보

배포용 비공개 Hugging Face 저장소에 읽기 권한이 있는 토큰이 필요합니다. 기존 전달 저장본을 사용하는 경우에도 [모델 manifest](../deployment/model-release.json)의 다섯 파일과 크기·SHA-256을 대조하세요. 일부 파일만 복사하거나 다른 모델의 metadata를 섞지 않습니다.

기존 준비 스크립트는 manifest의 고정 revision·model_id와 파일 해시를 검사하고 검증된 캐시만 재사용합니다. 새 다운로드에는 네트워크와 약 453 MB의 모델 파일 공간, 임시 복사 공간이 필요합니다. 아래 명령은 캐시가 없으면 다운로드하며 이번 문서 작업에서 새 다운로드를 실행한 기록은 아닙니다.

```bash
# 토큰을 명령줄 인자나 저장소 파일에 적지 않습니다.
read -rsp 'Hugging Face read token: ' HF_TOKEN
export HF_TOKEN
uv run --locked python -m scripts.deployment_model \
  --manifest deployment/model-release.json \
  --root artifacts/local-classifier-release
unset HF_TOKEN
```

성공 시 출력된 모델 디렉터리를 `.env`의 `SANAEBI_CLASSIFIER_PATH`로 지정합니다. 폴더 구조는 `<root>/<model_id>/<revision>`입니다. 기존 캐시 검증에 실패하면 덮어쓰지 않고 종료하므로 원자료를 보존한 채 원인을 확인하세요. 토큰은 준비 과정에만 필요하며 서버 실행에는 필요하지 않습니다.

## 외부 사용자: 새 저장본 학습

공개 사전학습 KoELECTRA에서 프로젝트 데이터로 새 모델을 학습할 수 있습니다. 기본 CLI 모델은 RoBERTa이므로 `--model`을 반드시 명시합니다. 아래는 선정 실험의 모델·revision·분할 seed·후보 설정을 참고하되 CPU에서 실행하는 예시입니다.

```bash
uv run --locked python -m classification.transformer \
  --model monologg/koelectra-base-v3-discriminator \
  --revision 68b30cd259f34a4b5aa8786392612ba2a2617fcc \
  --epochs 3 --batch-size 4 --max-length 256 \
  --learning-rates 2e-5 5e-5 --seed 20261013 --device cpu \
  --output artifacts/local-classifier/model
```

이 명령은 실제 다운로드·학습을 수행하며 이번 문서 수정에서는 실행하지 않았습니다. CPU 학습 시간은 측정하지 않았습니다. 기존 선정 실험은 CUDA를 사용했으며 장치·실행 환경에 따라 결과가 달라집니다. 새 model_id를 가진 재학습 결과를 선정 저장본이나 같은 성능으로 취급하지 않습니다. 기존 출력 폴더는 덮어쓰지 않으므로 재실행 시 새 경로를 지정하세요.

학습은 validation 기준으로 후보를 선택하고 모델·tokenizer·metadata를 함께 저장합니다. 필요하면 명시적으로 평가합니다.

```bash
uv run --locked python -m classification.evaluate \
  artifacts/local-classifier/model \
  --output artifacts/local-classifier/results/validation
```

완료한 폴더를 `.env`에 `SANAEBI_CLASSIFIER_PATH=artifacts/local-classifier/model`로 지정합니다. 이 저장본은 선정 배포 manifest와 일치하지 않으므로 위 배포용 검증 명령의 대상이 아닙니다. 모델·데이터의 이용 조건은 원출처를 확인해야 하며 이 안내가 재배포 허가를 부여하지 않습니다.

## 실행에 연결하기

저장본에는 `config.json`, `metadata.json`, `model.safetensors`, `tokenizer.json`과 tokenizer 설정을 함께 유지합니다. 준비 진단의 파일 존재 확인과 서버의 metadata·라벨·가중치 로딩 검증은 다릅니다. 저장 계약·독립 로딩 확인은 [분류 추론 안내](../app/classification/README.md)를 따릅니다.

모델 경로와 생성 키를 설정한 뒤 [로컬 개발 시작](../README.md#로컬-개발-시작)의 setup → check → dev 순서로 실행하세요. `check:local`은 모델 추론·API 키 유효성·실제 답변 품질을 검증하지 않습니다. 모델 파일이나 경로를 바꿨다면 서버를 재시작하세요.
