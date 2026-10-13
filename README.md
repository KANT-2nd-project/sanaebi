# Sanaebi

LinkUp 팀이 이음웍스 구성원을 위해 준비하는 사내 지식 관리·질의응답 포털입니다. 현재 저장소에는 문서 등록·질문 입력 반환 API 초안, 기존 질문 분류 실험 코드와 새 문서 분류 데이터가 있습니다. 회사 근거 검색·답변 생성과 새 문서 분류 모델 연결은 아직 완료되지 않았습니다.

학습에 사용할 [문서 데이터 600건 CSV](data/dataset.csv)를 저장소에 포함합니다. [데이터 사용 안내](data/README.md)에서 열 설명·분할·검수 상태를, [출처와 이용 조건](data/ATTRIBUTION.md)에서 원문 정보를 확인하세요.

## 현재 학습 목표

현재 목표는 문서의 제목과 본문으로 6개 업무 주제 중 대표 주제 하나를 선택하는 단일 라벨 분류입니다. [분류·라벨링 기준 v2.0](docs/label-taxonomy.md)을 적용하며, 데이터셋 v0.2는 분할을 저장하지 않는 7개 열의 CSV입니다. 입력은 `title`·`text`, 정답은 `label`입니다. 학습 코드에서 시드 `20261013`으로 원문 계열을 묶어 분할하고, 합성 자료는 학습에만 배치하도록 정했습니다. 전체 70:15:15를 목표로 하되 원문 계열 보존을 우선합니다. 이 런타임 분할과 새 문서 CSV 연결은 아직 구현되지 않았습니다. 600건 모두 AI 검수 자료이며 사람의 정답 승인과 이 데이터로 수행한 모델 학습·평가는 아직 없습니다.

`classification/`과 `data/questions/`는 다른 팀원의 기존 질문 분류 실험입니다. 새 문서 CSV를 읽도록 변경하지 않았으며 기존 결과를 새 6종 문서 분류의 성능으로 사용하지 않습니다. 질문의 지원 범위와 검색 후 근거 부족은 별도 서비스 처리 기준입니다.

## 개발 환경

- Python 3.12.14 (`.python-version` 기준)
- uv 0.12.5 이상 권장
- API·기존 분류 실험 의존성은 `pyproject.toml`과 `uv.lock`으로 관리
- 문서 CSV 읽기·기본 검증은 Python 표준 라이브러리만 사용
- Ruff는 개발 도구로만 사용

### Windows PowerShell

uv가 설치되어 있지 않다면 [공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를 따르세요. 이미 설치되어 있으면 다시 설치할 필요가 없습니다.

```powershell
New-Item -ItemType Directory -Force "$HOME\workspace\projects"
Set-Location "$HOME\workspace\projects"
git clone https://github.com/KANT-2nd-project/sanaebi.git
Set-Location .\sanaebi
uv python install 3.12.14
uv sync --locked
```

### WSL

Windows 작업 폴더와 가상환경을 공유하지 말고 WSL 파일시스템에 별도로 clone하고 환경을 만드세요. uv가 없다면 [공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를 따르고, 기존 uv는 재설치하지 않아도 됩니다.

```bash
mkdir -p ~/workspace/projects
cd ~/workspace/projects
git clone https://github.com/KANT-2nd-project/sanaebi.git
cd sanaebi
uv python install 3.12.14
uv sync --locked
```

명령은 가상환경을 직접 활성화하지 않고 `uv run`으로 실행합니다.

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

Windows PowerShell에서의 실행은 별도로 확인하기 전까지 미검증 상태입니다. 데이터 검증은 CSV의 형식·수량·중복을 확인합니다. 원문 계열 분리와 합성 자료의 학습 전용 배치는 후속 학습 코드에서 검증해야 하며, 현재 CSV 검증은 모델 정확도나 서비스 성능 검증을 뜻하지 않습니다.

## 의존성 변경

런타임 의존성은 `uv add <패키지>`, 개발 도구는 `uv add --dev <패키지>`로 추가하고 `pyproject.toml`과 `uv.lock`을 함께 커밋합니다. 잠금 파일은 임의로 편집하지 않습니다.

## 협업과 기록

`main` 브랜치를 함께 사용합니다. 작업 전 최신 내용을 가져오고, 같은 파일을 수정할 때는 먼저 조율합니다. 충돌이나 덮어쓰기 위험이 있으면 임의로 강제 진행하지 말고 팀 리더와 함께 해결합니다.

회의 전에 [개인 일지](https://app.notion.com/p/8a405a3cdadc834ab02001bc72f02534)에 역할, 접근 방법, 실제 수행 내용, 실행·검증 결과, 막힌 점과 다음 할 일, 커밋·실험 링크를 현재 상태에 맞게 적습니다. 팀 문서는 [Notion](https://app.notion.com/p/2bb05a3cdadc82bb813381e3fab45047)에서 확인합니다.
