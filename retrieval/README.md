# 문서 검색·임베딩 기록

후속 RAG의 검색 모델 선정과 실험 근거를 관리한다. 현재는 기록 공간이며 서버 검색 모듈이 아니다. 분류 학습은 [classification](../classification/README.md), 답변 생성은 [generation](../generation/README.md)에서 관리한다.

- **선정:** KoEn-E5-Tiny. [16종 CPU 비교·채택 보고서](reports/2026-10-15-cpu-embedding-comparison/README.md)와 [모델 계약·후속 작업](reports/2026-10-15-cpu-embedding-comparison/selection.md).
- **연결 상태:** 모델 선정 완료. 벡터 DB·서버 RAG 연결과 배포 품질 검증은 후속이다.
- **기록 기준:** 결론·작은 비교표·검토 가능한 증거는 reports, 큰 벡터·가중치·가상환경은 로컬 원자료에 둔다. 실험 당시 관측과 이후 사용자 결정을 구분하며 기존 기록을 덮어쓰지 않는다.

전체 연결 정책은 [서비스 설계](../docs/service-architecture.md), 문서 게시·개정은 [문서 관리](../docs/document-management.md)를 따른다.
