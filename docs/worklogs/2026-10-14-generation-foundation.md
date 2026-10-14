# 생성 모듈 기초 구현·학습 기록

- 날짜: 2026-10-14
- 시작 기준: `f794db9` (확인 시 origin/main과 동일)
- 범위: 새 generation 모듈의 기본 계약·파싱·호출·프롬프트, 관련 테스트·문서·Notion 일지

## 문제와 결정

기존 LangChain과 생성 평가의 결합을 검토한 뒤, 기존 구현을 보존하면서 새 생성 계약부터 단계적으로 구현하기로 했다. 서비스와 평가기가 같은 생성 경로를 사용하고 실행 실패와 답변 품질을 분리한다. 기존 실행기와 평가기의 실제 아카이브 이동은 아직 수행하지 않았다.

이전 상세 조사와 비교 근거는 Git 제외 로컬 `tmp/langchain-generation-review-2026-10-14/`에 보관한다. 당시 스냅샷의 조사 결과이며 이후 SQLite 전환 등 현재 코드의 동작을 대신하지 않는다. 이번 게시에 임시 자료 전체를 포함하지 않는다.

## 수행과 기여

사용자는 AI 설명·힌트·모범 답안을 참고해 `GenerationStatus`, `GenerationResult`, `GenerationPrompt`, `parse_generation`, `generate`, `build_prompt`를 직접 작성했다. AI는 파일을 읽어 리뷰하고 사용자 요청에 따라 테스트 작성·실행·문서화·게시를 담당했다. 독립 구현 숙련도나 실모델 품질을 확인한 것은 아니다.

- 불리언 상태 나열 대신 COMPLETED·TIMEOUT·PARSE_ERROR·EMPTY_ANSWER를 정의했다.
- JSON 구문·객체 구조·answer 문자열 검사를 구분하고 실패를 결과 객체로 반환했다.
- `.strip()`은 원본을 변경하지 않는다는 점을 확인해 정리된 답변을 저장하고 빈 답변은 None으로 반환했다.
- 모델 호출 함수를 주입하고 TimeoutError만 TIMEOUT으로 변환했다. 실제 timeout 설정과 공급자 오류 정규화는 남았다.
- 사내비 배경·말투·근거 원칙·JSON 규칙과 이번 문서·질문을 system/user로 분리했다.
- `generate`와 모델 함수 입력 타입을 GenerationPrompt로 연결했다.

## 검증 결과

- `uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -v`: 11개 성공. 프롬프트 객체 전달·역할 분리·빈 문서·JSON 경계·빈 답변·시간 초과·예상 밖 예외 전파를 확인했다.
- `uv run --locked ruff check .`: 성공.
- `uv run --locked ruff format --check .`: 154개 파일 확인, 성공.
- `git diff --check`: 성공.

가짜 모델 함수로만 확인했다. 이번 변경은 활성 API에 연결하지 않았으므로 전체 API·웹 회귀 검사는 재실행하지 않았다. 실제 모델 호출·답변 품질·운영 배포를 검증하지 않았다.

## 남은 작업

다음 학습은 GenerationPrompt를 LangChain SystemMessage/HumanMessage로 변환하는 어댑터다. 이후 모델 설정·응답 문자열 경계·공급자 오류·입력 예산·문서 snapshot 메타데이터를 연결한다. 현재 모듈은 패키지 배포 설정에 포함되지 않았다. 서버·평가기 공통 경로와 회귀 검증을 확보한 뒤 기존 구현을 아카이브로 이동한다.

현재 사용법과 계약은 [생성 모듈 안내](../../generation/README.md), 모델 평가 기준은 [생성 평가](../generation-evaluation.md)를 따른다. Notion에는 프로젝트 문서 안내·서비스 처리 기준의 요약과 기존 개인 일지 DB의 새 기록을 연결한다.
