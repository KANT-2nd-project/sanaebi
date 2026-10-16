# 프롬프트 프로필 정리와 출력 계약 확인

사용자 요청에 따라 AI가 현재 프롬프트 코드와 호출 경로를 확인하고 정리했다. 실험 후보를 새로 채택하거나 프롬프트를 튜닝한 작업은 아니다.

- 활성 프로필: `examples_answer_scope_v5`(독립 CLI/full), `examples_answer_scope_v5_rag_service_v1`(RAG 서버).
- 이전 기준점·대체 후보·미채택 v6/v7 총 14개는 `generation/archive/prompt_profiles.json`으로 이동했다. 과거 평가에서 이름을 명시하는 실행은 지연 로드로 호환한다. 원응답·평가 판정은 보존했다.
- 활성 본문에서 사용하지 않는 후보 전용 상수와 조립 코드를 제거했다. v5에 필요한 이전 규칙 조각은 유지했다. 16개 프로필의 정리 전후 suffix SHA-256 동일성을 테스트했다.
- 서버와 평가 실행기는 `generate_from_documents`를 사용하고, 공통 `build_profile_prompt`는 `prompts.build_prompt`의 시스템 JSON 지침을 포함한다. 두 활성 프로필에서 이 지침과 모델 메시지 전달을 검증했다.
- 현재 `models.json`은 `prompt_json`이다. `build_openai_model`의 이 분기는 `response_format`을 전달하지 않는다. 따라서 공통 JSON 지침은 있지만 API 강제 형식은 아니다. `strict_json_schema`는 유효한 선택 옵션이므로 삭제하지 않았다.
- 본문 예시의 JSON 통일이나 strict 기본값 전환은 하지 않았다. 이는 별도 동작 변경이며 이번 정리만으로 파싱 오류가 해결됐다고 주장하지 않는다.
- 서버 재시작·배포·LLM 호출·Git 게시·Notion 게시는 수행하지 않았다. 사용자 발표 자료도 보존했다.

검증: 생성 테스트 153개 통과, Ruff check 및 format check 통과(612 Python 파일). 전체 Python 테스트 결과는 아래에 기록한다.

전체 검증 명령: `uv run --locked python -m unittest discover -s tests -t . -q`

```text
Ran 1065 tests in 76.041s

OK
```

첫 시도의 `-s tests` 단독 실행은 tests/generation과 실제 generation 패키지의 이름 충돌로 import 오류가 났다. 저장소 루트를 `-t .`로 지정하여 해결했다.
