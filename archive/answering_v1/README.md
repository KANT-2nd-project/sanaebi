# 과거 답변기와 평가기

현재 서버에서 사용하지 않는 독립 답변기와 평가기를 보존한다. 운영 생성은 [현재 generation](../../generation/README.md)을 확인한다.

저장소 루트에서 다음 명령을 사용한다.

```bash
uv run --locked python -m archive.answering_v1.assistant --help
uv run --locked python -m archive.answering_v1.answer_pipeline.cli --help
uv run --locked python -m archive.answering_v1.answer_pipeline.cli run --help
uv run --locked python -m archive.answering_v1.answer_pipeline.cli judge --help
uv run --locked python -m archive.answering_v1.answer_pipeline.cli report --help
```

기존 CLI 옵션은 그대로다. 실제 run/judge 및 assistant 실행에는 모델 호출·인증 입력이 포함될 수 있다. 이번 이동 검증에서는 help와 모의 모델만 사용했다. 예제 설정은 [examples](answer_pipeline/examples/)에 있다.

이전 루트 `sanaebi_assistant.py`, `python -m answer_pipeline.cli`와 Python import 경로는 제거했고 호환 wrapper는 제공하지 않는다. 기존 `sanaebi`·`sanaebi-train` 분류 CLI는 변경하지 않았다. assistant의 result.json은 계속 저장소 루트에 저장된다. 평가기의 기본 문서·질문은 data/archive/company-knowledge-v0 아래이며 명시한 --run-dir 경로도 그대로 사용한다.

이동 전 실행의 정확한 재현은 **21af689aed9eb1941e70091cd8c68a5e4d74e362 또는 해당 보고서의 고정 커밋**에서 당시 경로로 수행한다. 현재 보관 도구는 새 모듈 경로와 코드 해시를 기록한다. 과거 원응답·판정·manifest를 새 코드 기준으로 수정하지 않는다. 날짜별 생성 실험은 이번 이동 대상이 아니다.

[핵심 정리 일지](../../docs/worklogs/2026-10-15-core-cleanup.md)에 변경·검증·남은 항목을 기록한다.

## 설치 범위와 선택 provider

서버·평가기는 소스 checkout에서 실행한다. 독립 wheel 배포는 지원 범위가 아니다. 기본 운영 의존성은 `uv sync --locked --no-dev`로 설치하며 분류 추론의 torch·transformers를 포함한다. Ollama와 과거 답변기 사용 시 `uv sync --locked --extra ollama`로 선택 의존성을 설치한다. 전체 테스트에도 이 extra가 필요하다. `sanaebi`·`sanaebi-train`은 기존 보관 분류 CLI를 유지한다.

## 과거 trace 단계 해석

[trace](trace.py)는 이 실행기의 `prepare_input`·`RunnableBranch`·`format_answer` 단계 이름을 해석하는 보관 콜백이다. 현재 서버의 일반 trace를 확장하지만 서버가 보관 코드를 역으로 import하지 않는다. 기존 단계 해석은 legacy 테스트에서 확인하며, 현재 요청·검색·생성 기록은 [서버 trace](../../app/diagnostics/trace.py)가 담당한다.
