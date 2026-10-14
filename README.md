# Sanaebi

사내비는 LinkUp 팀이 직원 300명 이상인 가상의 업무·협업 SaaS 회사 이음웍스의 회사 문서 질문을 처리하도록 준비하는 사내 지식 관리·질의응답 프로젝트입니다. 현재 개발 범위는 `POST /ask`의 질문 처리·답변 연결이며, `POST /regist-docs`는 코드가 있지만 현재 범위 밖의 후속 기능입니다. 현재 동작과 목표 설계는 [서비스 아키텍처](docs/service-architecture.md)에 정리했습니다.

## 현재 서비스 상태

| 경로·기능 | 저장소에서 확인한 동작 |
|---|---|
| `GET /` | 서버 실행 메시지를 반환합니다. |
| `POST /ask` | 질문을 검증하고 앞뒤 공백을 제거한 문자열을 응답의 text로 반환합니다. 분류기, 회사 문서, LLM에는 연결되어 있지 않습니다. |
| `POST /regist-docs` | doc 본문을 `app/documents.jsonl`에 JSON Lines 한 줄로 추가하고 등록 응답을 반환합니다. |
| 요청 처리 분류 | 세 처리 경로 기준과 데이터는 준비되어 있습니다. API 런타임에는 분류기가 연결되어 있지 않습니다. |
| 문서 기반 답변 | 전체 회사 문서와 질문을 LangChain을 통해 전달하는 설계입니다. LangChain과 LLM은 아직 API에 연결되지 않았습니다. |

## 데이터와 구현 현황

학습·평가 질문은 [data/dataset.csv](data/dataset.csv), 문항별 작성·검수 이력은 [data/dataset-review.csv](data/dataset-review.csv)에 있습니다. 데이터셋 v0.1은 모두 합성한 한국어 질문 900건이며, `ANSWER_FROM_DOCS`, `CLARIFY`, `UNSUPPORTED`가 각각 300건입니다. 데이터 작성과 두 AI 검수는 완료됐고 전체 `review_status`가 `ai_reviewed`입니다. 사람의 정답 승인은 0건입니다.

CSV는 `question_id`, `question`, `label`, `group_id`, `source`, `review_status`의 여섯 열이며 모델 입력은 `question` 하나뿐입니다. 데이터 사용법·검수·그룹 분할 기록은 [데이터 안내](data/README.md), 라벨 판정의 단일 기준은 [요청 처리 분류·라벨링 기준 v1.0](docs/label-taxonomy.md)에서 확인할 수 있습니다.

현재 완료된 범위는 질문 데이터 작성과 AI 검수입니다. 모델 학습, 실제 질문 분류, 회사 문서 답변 연결, 모델 점수와 서비스 성능 평가는 아직 수행하지 않았습니다.

## 개발 환경

- Python 3.12.14 (.python-version 기준)
- uv 0.12.5 이상 권장
- API와 모델 실험 의존성은 pyproject.toml 및 uv.lock으로 관리
- CSV 검증은 Python 표준 라이브러리를 사용하며 Ruff는 개발 도구로 사용

### Windows PowerShell

uv가 없다면 [공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를 따르세요.

```powershell
New-Item -ItemType Directory -Force "$HOME\workspace\projects"
Set-Location "$HOME\workspace\projects"
git clone https://github.com/KANT-2nd-project/sanaebi.git
Set-Location .\sanaebi
uv python install 3.12.14
uv sync --locked
```

### WSL

Windows 작업 폴더와 가상환경을 공유하지 말고 WSL 파일시스템에 별도로 저장소를 복제하고 환경을 만드세요.

```bash
mkdir -p ~/workspace/projects
cd ~/workspace/projects
git clone https://github.com/KANT-2nd-project/sanaebi.git
cd sanaebi
uv python install 3.12.14
uv sync --locked
```

가상환경을 직접 활성화하지 않고 `uv run`으로 명령을 실행합니다.

## 확인 명령

```bash
uv run --locked python --version
uv run --locked ruff --version
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/validate_dataset.py
uv run --locked python -m unittest discover -s tests -v
```

Windows PowerShell에서의 실행은 별도로 확인하기 전까지 미검증 상태입니다. 데이터 검증은 CSV 계약과 수량, 라벨을 확인하며 모델 정확도나 서비스 성능을 측정하지 않습니다.

## 의존성 변경

런타임 의존성은 `uv add package-name`, 개발 도구는 `uv add --dev package-name`으로 추가하고 `pyproject.toml`과 `uv.lock`을 함께 갱신합니다. 잠금 파일을 직접 편집하지 않습니다.

## 팀 문서

[Notion 팀 문서](https://app.notion.com/p/2bb05a3cdadc82bb813381e3fab45047)에서 팀의 진행 기록과 작업 문서를 확인합니다.
