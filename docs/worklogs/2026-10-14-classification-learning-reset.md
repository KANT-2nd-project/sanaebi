# 분류 기존 구현 보관과 직접 구현 시작

## 범위와 보존

사용자가 직접 다시 구현할 수 있도록 기존 `classification/` 구현·실험 진입점·보고서·과거 결과를 `archive/classification_v1/`로 이동했다. 기준 커밋은 `af69c046f6a2e37baad98af53b455386c21e82ea`다. Python 패키지 경로, 저장소 기준 데이터·산출물 경로와 문서 링크를 조정했다. 실행 알고리즘·평가 수치 변경은 없다.

`data/`의 CSV, `artifacts/`의 가중치·평가·MLflow DB, `.env`, 서버의 기존 모델 경로는 이동·재생성하지 않았다. 이동된 결과 JSON·CSV·HTML 38개의 바이트 동일성을 이관 전후 확인했다. 기존 회귀 테스트는 `tests/`에서 아카이브를 검사한다. 다른 작업의 웹·생성 코드·문서 변경은 보존한다.

기존 `sanaebi`, `sanaebi-train` 명령은 아카이브로 연결한다. 새 학습 공간과 혼동하지 않도록 루트 README·데이터 안내·서버 규약·문서 관리 가이드에 구분을 추가했다. 과거 작업 기록은 링크만 조정하고 당시 서술은 유지했다.

## 학습 출발점

[classification/README](../../classification/README.md)에 순서와 첫 실습 기준을 두었다. `load_rows()`는 의도적으로 `NotImplementedError` 상태다. 사용자가 직접 CSV 읽기를 구현한다. 확인용 테스트 2개는 분리된 `classification.exercises.check_dataset`으로 실행하며 현재 둘 다 해당 미구현 오류로 실패함을 확인했다. 이는 회귀 실패나 학습 완료를 뜻하지 않는다.

AI가 수행한 것은 보관·경로 정리·학습 틀 준비·회귀 검증이다. 사용자 독립 구현이나 학습 완료로 기록하지 않는다. 신규 모델 학습·외부 API 평가는 실행하지 않았다. 기존 회귀 검증의 임시 TF-IDF 실행은 실제 실험 산출물과 분리되어 있다.

## 검증

- `uv sync --locked`: 변경된 패키지/기존 CLI 설치 성공.
- `uv run --locked python -m unittest discover -s tests`: 331개 실행, 통과(1개 skip). 첫 실행에서 패키지 깊이에 의존한 계층 검사 5개가 실패했으며 새 패키지 접두사를 제거한 뒤 소유 모델 이름을 검사하도록 수정한 후 전체 재검증했다.
- `uv run --locked ruff check .`, `uv run --locked ruff format --check .`: 최초 전체 검사 통과. 최종 재확인에서는 다른 작업에서 추가·수정 중인 `generation_evaluation/runner.py:12`의 문법 오류로 전체 검사가 실패했다. 해당 파일은 수정하지 않았다. 이번 변경 파일만 대상으로 한 check·format 검사는 통과했다.
- `uv run --locked python scripts/validate_dataset.py`: 900행, 라벨별 300행, 그룹 392개 통과.
- 이동 결과 38개 동일성 및 현재 안내·이동된 Markdown의 로컬 링크 검사 통과.
- `git diff --check`: 통과.

이번 작업은 로컬 설정 단계다. 커밋·푸시·Notion 갱신은 수행하지 않았다. 새 원격 링크는 게시하지 않았으며 외부 문서는 아직 게시된 기존 버전을 가리킨다. 원격 게시 시 문서 관리 가이드의 대응 페이지에서 아카이브 경로와 새 학습 공간을 구분해 반영해야 한다.
