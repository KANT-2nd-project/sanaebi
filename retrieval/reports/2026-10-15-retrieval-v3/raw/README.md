# 압축 원자료 읽기

JSON 압축 파일은 `gzip -dc 파일명.json.gz`로 읽는다. 모델·벡터 배열·SQLite·환경 파일은 포함하지 않는다.

- `development-search`·`development-rerank-scores`·`development-manifest`: 실제 개발 실행. BGE raw 점수·입력 길이와 코사인은 별도다.
- `development-relevance-packet`: 설정·점수·순위를 제거한 공통 검수 입력.
- **`development-development-judgments.json.gz`**: 추가 검토와 수정까지 반영해 최종 집계에 사용한 3,684개 판정. `candidate-freeze.json`에 원본 SHA를 연결했다.
- `development-judgments-1/2/3/4`: 최종 분할본. `development-qa-corrections-*`는 추가 수정 전후와 이유다.
- 이름에 `before`, `pre-fix`, `pre-final`, `mapping-fix`가 있는 파일과 `development-judgments-3b`는 보존된 초안/중간 단계다. 최종 판정으로 사용하지 않는다. `review-*`는 해당 단계 작성자의 검토 기록이다.
- `confirmation-search`·`confirmation-relevance-packet`·`confirmation-manifest`: 개발 후보 동결 뒤 한 번 실행한 신규 확인. 판정·집계와 별도로 보존한다.
- `benchmark-*`·`bge-resource-rejection`: 로컬 CPU2 요청별 측정과 조기 탈락 하한. BGE의 일부 관측을 전체 p95로 해석하지 않는다.
- `c-server-parity`·`actual-tiny-http`: 실제 Tiny 검색·모의 생성 HTTP 연결 확인. 실제 LLM 품질 검증은 아니다.

원자료의 생성 시각·코드 SHA는 당시 실행을 가리킨다. 이후 집계·검증 코드 수정은 최종 검증 기록과 Git 이력에서 구분한다. 압축 전 해시는 `archive-manifest.json`, 전체 게시 파일의 해시는 최종 산출물 manifest에서 확인한다.

`confirmation-confirmation-judgments.json.gz`는 최종5,034개 판정이다. `confirmation-judgments-*.before-qa`와 `confirmation-qa-corrections-*`는 최초 판정과 독립 QA 수정 내역이며 최종본과 구분한다.
