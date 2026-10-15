# 문서 검색·임베딩 기록

RAG의 검색 모델 선정과 실험 근거를 관리한다. 서버 검색 코드는 `app/retrieval/`에서 관리한다. 분류 학습은 [classification](../classification/README.md), 답변 생성은 [generation](../generation/README.md)에서 관리한다.

- **선정:** KoEn-E5-Tiny. [16종 CPU 비교·채택 보고서](reports/2026-10-15-cpu-embedding-comparison/README.md)와 [모델 계약·후속 작업](reports/2026-10-15-cpu-embedding-comparison/selection.md).
- **연결 상태:** 선택적 서버 RAG와 자정 복원을 구현했다. 기본값은 full이며 실제 LLM·운영 배포 품질 검증은 후속이다.
- **기록 기준:** 결론·작은 비교표·검토 가능한 증거는 reports, 큰 벡터·가중치·가상환경은 로컬 원자료에 둔다. 실험 당시 관측과 이후 사용자 결정을 구분하며 기존 기록을 덮어쓰지 않는다.

전체 연결 정책은 [서비스 설계](../docs/service-architecture.md), 문서 게시·개정은 [문서 관리](../docs/document-management.md)를 따른다.

## 서버 검색 구현

[선택적 RAG 실행](../docs/rag-runtime.md)은 기존 full 기본값을 보존하면서 로컬 Tiny·SQLite exact 검색과 자정 기본 벡터 복원을 연결한다. 모델 선정 결과와 실제 운영 품질은 구분한다. 런타임 코드는 app/retrieval, 과거 실험 기록은 이 폴더의 reports에 둔다.

[로컬 RAG 검증](reports/2026-10-15-rag-local-validation/README.md)은 검색 순위·최종 근거와 자정 복원을 구분해 기록한다.

[단계별 검색 개선 비교](reports/2026-10-15-rag-quality-improvement/README.md): 세 후보 구현·평가, 인접 확장 회귀 개선과 사전 채택 기준 미충족에 따른 기존 검색 유지.
