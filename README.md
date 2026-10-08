# Sanaebi

LinkUp 팀이 이음웍스 구성원을 위해 준비하는 사내비 프로젝트 저장소입니다. 현재 저장소에는 Python 개발 환경 설정만 있으며, 서비스 기능은 아직 구현되지 않았습니다.

## 개발 환경

- Python 3.12.14 (`.python-version` 기준)
- uv 0.12.5 이상 권장
- 런타임 의존성 없음
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
```

초기 환경은 WSL에서 위 명령으로 확인합니다. Windows PowerShell에서의 실행은 별도로 확인하기 전까지 미검증 상태로 기록합니다. 아직 Python 소스가 없으므로 Ruff 검사의 성공은 도구와 설정이 동작한다는 뜻이며, 서비스 코드의 품질을 검증한 것은 아닙니다.

## 의존성 변경

런타임 의존성은 `uv add <패키지>`, 개발 도구는 `uv add --dev <패키지>`로 추가하고 `pyproject.toml`과 `uv.lock`을 함께 커밋합니다. 잠금 파일은 임의로 편집하지 않습니다.

## 협업과 기록

`main` 브랜치를 함께 사용합니다. 작업 전 최신 내용을 가져오고, 같은 파일을 수정할 때는 먼저 조율합니다. 충돌이나 덮어쓰기 위험이 있으면 임의로 강제 진행하지 말고 팀 리더와 함께 해결합니다.

회의 전에 [개인 일지](https://app.notion.com/p/f1a66c572421830b8a4381ec1e68166c)에 역할, 접근 방법, 실제 수행 내용, 실행·검증 결과, 막힌 점과 다음 할 일, 커밋·실험 링크를 현재 상태에 맞게 적습니다. 팀 문서는 [Notion](https://app.notion.com/p/c8666c5724218381b3a501609274e325)에서 확인합니다.
