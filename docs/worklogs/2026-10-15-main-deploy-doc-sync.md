# 문서 정합성 main 병합과 배포 복구

2026-10-15. 사용자 요청으로 문서 브랜치를 main `e1a4e468ac72637f12ba03e79a9f3dad5bd735e4`에 병합·푸시했다. 원래 작업 폴더의 서버 미커밋 변경은 보존했다.

첫 Delivery 실행 `38731815056`에서 Python·웹·ARM64 이미지 검증은 통과했으나 배포 사전검사의 candidate retrieval index가 실패했다. 운영 포인터는 기존 `389e936...-38700734863`을 유지했고 API readiness는 정상이다. 최신 릴리스 schema v2를 지원하도록 호스트 설치 스크립트로 배포 helper·Compose를 갱신했으며 비밀 설정·DB는 보존했다. 기존 helper·Compose 백업은 호스트 `/var/backups/sanaebi-host-tools-e1a4e46/`에 있다.

## 원인과 최소 수정

운영 DB를 읽기 전용 백업한 격리 복사본에서 검색을 재현하자 `DocumentStorageError`의 원인이 `Unsupported document schema`였다. API 시작은 기존 `DocumentRepository.initialize()`로 이전 스키마를 갱신하지만, 새 검색 사전검사는 API 시작보다 먼저 읽기 전용 reader를 호출했다.

배포 helper가 후보 DB 복사본에만 기존 초기화 절차를 실행한 뒤 검색 준비를 검사하도록 수정했다. 운영 DB를 사전검사에서 변경하거나 schema 검사를 우회하지 않는다. 실제 교체 단계의 DB 백업·앱 시작·복구 정책은 유지한다. 기본 full과 shadow도 유지한다.

## 검증

기존 스키마 v2 DB를 복사해 실제 reader가 거부하는 회귀 테스트를 추가했고 수정 전에 같은 오류로 실패함을 확인했다. 수정 후 후보만 최신 스키마로 갱신되고 원본 DB 바이트는 동일함을 검증한다. 배포·운영 관리·RAG 준비 회귀 42개, 수정 파일 Ruff 검사·형식·diff 검사를 통과했다. 유료 LLM 호출·운영 문서 초기화는 수행하지 않았다.

최종 배포 결과는 Delivery 실행 및 별도 로컬 배포 결과 기록으로 확인한다. 이 기록의 첫 실패를 배포 완료로 해석하지 않는다.
