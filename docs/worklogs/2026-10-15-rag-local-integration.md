# RAG 검색·자정 복원 로컬 구현 — 2026-10-15

## 범위와 보존

사용자가 승인한 검색·서버·자정 초기화·배포 지원 계획을 구현했다. 사용자 결정은 KoEn-E5-Tiny 채택과 구현 범위이며, 코드 작성·테스트·검색 비교·문서 작성은 AI가 수행했다. 독립 코드 검토도 AI 검토이며 사람 검수로 기록하지 않는다.

시작 HEAD `a4fa0577713c76c3af8321333b5eb68bd23ed463`에서 별도 worktree `/tmp/sanaebi-rag-implementation-20261015`, 브랜치 `feat/rag-local-20261015`를 만들었다. 원래 작업 공간의 웹·문서 관리·reset 관련 병행 변경을 가져오거나 덮어쓰지 않았다. 향후 통합 시 이 변경들과 충돌·계약을 다시 확인해야 한다.

실제 LLM 호출, 운영 배포·설정 전환, Notion, 커밋·푸시는 요청대로 제외했다. Luna·examples_answer_scope_v5·16,384 출력 한도를 유지했다. 기본 retrieval mode는 full이다.

## 구현과 검증 경계

- `app/retrieval/`: 로컬 고정 revision CPU 임베딩, 문단·표·원문 위치 분할, 별도 SQLite 현재 개정 검색, 단일 writer 갱신, 기본 벡터 묶음.
- 서버: 요청 snapshot1회, 선택 근거를 기존 답변 어댑터로 전달, shadow/gate·예약 위치·응답 필드 유지, 초과422·미준비/장애503·자동 full fallback 없음.
- CLI: 색인 once/watch/status, 기본 묶음 준비, 모델 없는 reset/mapping 복구.
- 배포 지원: 릴리스 descriptor·host 기본 원본·schema별 파생 경로, candidate 임시 DB, worker 정지/복귀, 기존 릴리스 rollback 지원.

실제 Tiny 검색·복원·모의 생성 HTTP 결과는 [별도 보고서](../../retrieval/reports/2026-10-15-rag-local-validation/README.md)에 둔다. 기존18문항 근거 적중이17→15건으로 감소했으므로 운영 품질 통과로 판단하지 않는다.

## 독립 검토

검토자가 다중 중첩 병합의 tuple/list 오류, 공통 표 머리글만으로 떨어진 행을 병합하는 문제, 최종 문자 예산에서 점수·출처가 실제 전달 문맥과 어긋나는 문제를 지적했다. 배포 첫 원본 준비 순서, candidate 실패 정리, schema A→B→A 경로와 실패 rollback의 mode 보존도 점검했다. 각 수정은 재현 테스트와 재검토 대상으로 관리했다.

## 남은 운영 검증

현재 WSL에서 Docker 엔진을 사용할 수 없어 실제 컨테이너 시작·이미지 rollback·운영 자정 실행은 검증하지 못했다. 임시 SQLite와 모의 프로세스 테스트는 실제 컨테이너 검증을 대신하지 않는다. 로컬 CPU affinity2개는2vCPU 배포 환경의 부하 측정이 아니다. 실제 LLM 근거 충실도, 새 사람 검수 질문, 운영 전환은 후속이다.

## 최종 독립 재검토

지적된 병합·예산·배포 준비·정리·rollback 문제를 수정했고, 독립 검토자가 core25개와 배포 관련40개 테스트를 직접 실행해 통과를 확인했다. 추가 필수 결함은 발견하지 못했다. schema A→B→A 검사는 host binding·경로 선택·자료 보존 범위이며, 실제 다른 schema 컨테이너 부팅이나 DB 읽기 검증은 아니다.

## 최종 실행 결과

- `uv run --locked python -m unittest discover -s tests -t .`: **749개 통과**, 87.362초. 로그 `tmp/full-tests-final.log`.
- `uv run --locked ruff check .`: 통과. `uv run --locked ruff format --check .`:403파일 통과. `git diff --check`: 통과.
- 변경 Markdown12개 상대 링크의 대상 파일 존재 확인: 누락0개. 브라우저 렌더링은 별도로 실행하지 않았다.
- 실제 Tiny 재검증: 원문 위치 기준 기존top5 17/18, 새top5 15/18, 최종근거15/18. 기본 복원71/71 새개정, 실제Tiny+모의생성 HTTP200. 실제LLM 요청0회.
- generation 설정·모델·데이터·기존 결과의 tracked diff 없음. 기존 작업 공간의 다른 수정은 별도 유지. 커밋·푸시·외부 반영 없음.
