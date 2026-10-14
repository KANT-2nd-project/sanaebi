# 생성 연결부·평가 기록·집계 학습

- 날짜: 2026-10-14
- 시작 기준: `588ab2f` (게시 준비 시 origin/main과 동일)
- 이전 학습 게시: [기초 계약·프롬프트](2026-10-14-generation-foundation.md)

## 구현과 기여

사용자가 AI 설명·힌트·모범 답안을 참고해 GenerationConfig·제공자 enum, LangChain 메시지 변환, 문자열 응답 추출, 호출 클로저, Ollama/OpenAI 클라이언트 생성·분기, 시간 초과 예외 변환을 직접 작성했다. AI는 테스트·검증·문서화·게시를 담당했다. 실제 Ollama 실행 예제는 사용자 결정으로 건너뛰었다.

평가 코드에는 GenerationRun, perf_counter 기반 run_case, 상태별 집계, 완료 비율, 전체/완료 평균 시간, 설정별 그룹화를 추가했다. run_case는 generate를 재사용하며 일반 예외를 오류 종류와 경과 시간으로 기록하고 사용자 중단은 전파한다. 설정별 요약 조립과 평가 데이터·snapshot·프롬프트 식별·품질 판정·기록 저장은 아직 구현하지 않았다.

## 학습 중 수정한 부분

- 클래스 이름과 전달받은 인스턴스의 차이를 확인해 prompt.system/user로 값을 읽었다.
- 키워드 인자 뒤에 위치 인자를 쓴 문법 오류를 수정했다.
- 표준 dataclasses와 attr, 프로젝트 GenerationConfig와 transformers 동명 클래스의 import를 구분했다.
- 허용 모델 이름 목록 대신 제공자·비어 있지 않은 이름·유한한 양수 timeout을 검증했다.
- HTTPX와 OpenAI의 서로 다른 시간 초과 타입을 원인을 보존한 TimeoutError로 변환했다.
- 실험의 실행 상태·정답 품질, 빈 집계와 0, 전체 시도 평균과 완료 평균을 구분했다.
- 그룹의 리스트를 설정 객체로 덮어쓰던 부분을 append(run)으로 수정했다. 같은 값의 설정은 합치고 제공자·모델·시간 제한이 다르면 분리한다.

## 검증

- `uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -q`: 58개 통과.
- `uv run --locked ruff check .`: 통과.
- `uv run --locked ruff format --check .`: 173개 파일 확인, 통과.

위 검사는 가짜 모델·클라이언트·시계 기반이다. 실제 모델 요청·키 접근·다운로드·품질 평가를 수행하지 않았다. API·웹은 이번 코드에 연결하지 않았고 전체 서비스 회귀 검사를 재실행하지 않았다. 다른 작업의 분류 아카이브 전환·README·설정 변경은 이번 커밋에서 제외한다.

## 현재 한계와 다음 단계

HTTP timeout 설정은 전체 작업의 절대 마감 시간을 보장하지 않는다. 문자열 이외의 응답 content는 거부한다. 실행 기록은 config와 실제 호출 함수의 일치, 모든 모순 상태, 외부 입력의 시간값 등을 아직 강제하지 않는다. 모델 품질·인용·데이터 동등성·비용은 이 집계로 판정하지 않는다. 직접 사용하는 httpx/openai 의존성 선언과 패키지 배포 설정은 후속으로 남긴다.

다음 학습은 설정별 요약 타입과 집계 함수 조립이다. 실제 서비스 연결과 기존 생성 코드의 아카이브 이동은 후속이다. 기준은 [생성 모듈](../../generation/README.md)·[평가 실행 안내](../../generation_evaluation/README.md)에 두고, Notion 문서 안내·서비스 처리 기준·기존 개인 일지에 이번 진행 내용을 연결한다.
