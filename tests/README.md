# 테스트 실행과 책임

저장소 루트에서 Ollama extra를 포함한 개발 환경을 준비한다. 현재와 보관 도구의 검사를 모두 실행하므로 전체 회귀에는 extra가 필요하다.

```bash
uv sync --locked --extra ollama
uv run --locked python -m unittest discover -s tests -t . -v
uv run --locked python -m unittest discover -s tests/runtime -t . -v
uv run --locked python -m unittest discover -s tests/generation -t . -v
uv run --locked python -m unittest discover -s tests/evaluation -t . -v
```

`-t .`는 테스트 패키지의 최상위를 저장소 루트로 고정한다. 생략하면 tests/generation과 실제 generation 패키지의 이름이 충돌할 수 있다. 기존 최상위 test 모듈 import는 새 `tests.<책임>.test_*` 경로로 바뀌었다.

| 위치 | 검증 책임 |
|---|---|
| runtime | HTTP·문서·분류 추론·운영 설정·어댑터 |
| generation | 프롬프트·provider·생성 계약·단일 CLI |
| evaluation | 평가·예산·보고서·실험 전략 |
| classification | 현재 학습 코드와 데이터 검증 |
| legacy | archive의 과거 분류·답변 도구 |
| support | 공통 fixture 준비·저장소 루트 계산 |

fixtures는 기존 위치를 유지한다. 운영 테스트의 import가 보관 답변기를 요구하지 않도록 trace 검사를 분리했다. 전체 회귀에 포함된 작은 합성 모델 학습은 서비스 모델 학습이나 품질 평가가 아니다. 환경변수 `SANAEBI_DOCUMENT_DB`에는 초기화한 임시 SQLite를 지정하며 실제 서비스 DB는 사용하지 않는다.
