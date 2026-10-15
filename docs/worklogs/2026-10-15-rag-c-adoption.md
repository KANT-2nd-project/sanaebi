# RAG 검색 인자·문맥 제한 비교와 C 설정 확정

사용자가 검색 근거 누락 최소화를 우선해 C와 rag 기본값을 결정하고 기록·게시를 위임했다. AI가 구현·실험 결과 검증·독립 AI 검토·문서·게시를 수행한다. 사람 검수나 사용자 독립 구현 성취로 기록하지 않는다.

## 보존과 작업 범위

최신 원격 main `120c469`를 기준으로 별도 `feat/rag-c-publication-20261015` 작업 공간을 만들었다. 기존 실험 작업 공간·원자료·모델·DB·사용자 main 작업 트리는 유지한다. 미게시 실험 실행기·회귀·결과를 먼저 독립 커밋으로 보존했다. 과거 CSV 바이트와 manifest 검증값이 checkout 후 달라지지 않도록 보고서 CSV에 Git text 변환 제외를 적용한다.

운영 접속·배포·추가 유료 LLM 요청은 이번 작업에 포함하지 않는다. 생성 모델·프롬프트·출력 계약은 그대로 유지한다. 기능별 검증과 게시 결과는 완료 후 아래에 기록한다.

## 변경

- 서버 C 고정: 점수0.35 이상 전체 후보, 겹친 근거 병합, 개수·문자·별도 문맥 토큰 제한 제거.
- 과거 검색 선택 분기는 실험 전용으로 격리하고 원자료·재현 코드는 보존.
- 앱·신규 descriptor·Compose·배포 helper rag 기본값, 명시적 full과 과거 릴리스 복구 호환.
- [최종 선택 보고서](../../retrieval/reports/2026-10-15-c-adoption/README.md), 실험 목록과 준비 안내 갱신.

## 검증·게시

- C threshold 통합 테스트의 RED(0.34 후보 포함)를 확인한 뒤 구현했다. 13청크 중12개 적합 후보, 개수·문자·4k 초과 무절단과 순위를 고정했다.
- 빈 검색 결과가 답변기로 넘어가는 실패를 재현하고, /ask·/assistant에서 고정 안내·생성/예약0으로 수정했다. 질문/유지보수 관련14개 통과.
- 실제Tiny48문항의 [서버 C 동등성](../../retrieval/reports/2026-10-15-c-adoption/runtime-equivalence.json): 본문·범위·ID·순위48/48 일치, 점수 오차1e-6 이내. 기존 DB·색인 SHA 보존, 유료LLM0회.
- 기본 rag 변경으로 full 계약 fixture가 모델 없는 상태에서 실패해 의도한 full을 명시했고, RAG fixture는 .35 이상인 결정적 벡터로 변경했다. 경로 전달용 object fixture도 evidence 계약에 맞췄다. 제품 기본값을 테스트 편의로 되돌리지 않았다.
- 최종 전체Python882개 통과(54.216초). Ruff check·format504파일·diff 검사 통과. 변경 문서 상대 링크349개 존재 확인. 브라우저 Mermaid 시각 렌더링은 재검증하지 않았다.
- 독립 검토68개 및 보강 후22개 통과. [검토 기록](../../retrieval/reports/2026-10-15-c-adoption/evidence/independent-review.md).
- 기존 untracked 실험의 Git ignore된 로그19개를 보고서 원자료로 함께 보존했다. 키 패턴 검사 통과. 가중치·DB·환경파일·.venv는 staging하지 않는다.

## Git·외부 반영

[PR #11](https://github.com/KANT-2nd-project/sanaebi/pull/11)의 [Delivery 실행](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38751813453)에서 Python·웹·ARM64 이미지가 모두 통과했고 deploy는 skipped였다. main 병합 `3c3a8a10ab3b8072ff813348d039a6741a672eed`와 원격 보고서 링크를 확인했다. 병합 제목에 `[skip ci]`를 적용해 운영 자동 배포를 제외했다. 이번 최종 기록 후속 커밋에도 같은 표시를 적용한다.

- 기능별 커밋: `7becf4f` 과거 실험·증거, `f240a97` C 검색, `76e4548` rag 기본값·배포 호환, `1073235` 회귀 보강, `d51e582` 문서·원자료 게시.
- Notion [프로젝트 문서 안내](https://www.notion.so/3f805a3cdadc81e1a70bfe82c89cebe7), [서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b), [데이터 작성·검수·실험 절차](https://www.notion.so/3f805a3cdadc81d59dc9fec6e4fcca1d), [운영·개발 규칙](https://www.notion.so/3f805a3cdadc81aa9f48d8445d372b80)의 현재 구역을 수정하고 본문·게시 링크를 재조회했다. 기존 운영 shadow+full 기록은 당시 사실로 보존했다.
- 제목 중복 조회 후 [새 개인 일지](https://www.notion.so/3fa05a3cdadc81a6b493f48a5f3d2d84)를 생성했다. 최재선·검색/생성·2026-10-15·완료 속성과 사용자 결정/AI 수행·검증/운영 미전환 본문을 재조회했다. 기존 일지는 수정하지 않았다.
- OpenAPI12개 경로·스키마 전체 digest가 기준 main과 동일하다: `543553427fad74fa5d98e3b0ab01d32b8e9d83d74070cda0ee770f5bcb7dd015`. 앱 import로 확인했으며 실제 LLM을 호출하지 않았다.
- 상대 링크349개·앵커41개, Git에 저장된 context-limits manifest55항목의 바이트 일치, 변경220파일의 키 패턴 검사 통과. 기존 가중치·DB·환경파일과 .venv는 커밋에 포함하지 않았다.

실제2vCPU·운영 candidate/rollback·사람 검수·운영 RAG 활성화는 미완료다. CI 이미지 검증을 운영 배포나 전체 답변 품질 승인으로 표현하지 않는다.
