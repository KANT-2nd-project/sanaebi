# 작업 지침

저장소 목적과 환경 설정은 [README.md](README.md)를 따릅니다.

- 요청된 범위만 작업하고, 요청 없이 서비스 기능을 구현하거나 범위를 넓히지 않습니다.
- Python은 공백 4칸을 사용합니다. Ruff 확인은 `uv run --locked ruff check .` 및 `uv run --locked ruff format --check .`로 합니다.
- 의존성은 `uv add` 또는 `uv add --dev`로 추가하고 `pyproject.toml`과 `uv.lock`을 함께 갱신합니다.
- `main` 최신 상태를 확인하고 같은 파일 변경은 조율합니다. 충돌을 기존 변경 덮어쓰기로 해결하지 말고 팀 리더와 함께 처리합니다.
- 비밀키, 인증 정보, 실제 환경 파일을 커밋하지 않습니다.
