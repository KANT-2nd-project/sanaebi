# RAG 변경 게시·재시작·배포 기록

## 사용자 결정과 범위

2026-10-16 사용자가 커밋·푸시·서버 재시작·공개 배포·Notion 게시를 승인했다. 이어 문맥 보충도 이전 대비 관측 개선을 우선하여 적용하도록 요청했다. 초기 8회 판정은 빈 근거 처리 채택·문맥 보충 보류였으며 그 점수를 바꾸지 않는다. AI가 구현·검증·게시·운영 확인을 수행한다.

서버 RAG는 v5_rag_service_v1과 문맥 보충을 결합한다. full·독립 CLI v5와 직접 RetrievalService 생성자의 확장 False는 보존한다. 확장 원복은 SANAEBI_RAG_EXPAND_CONTEXT=0, 빈 근거 처리 원복은 SANAEBI_RAG_PROMPT_PROFILE=examples_answer_scope_v5 지정 후 재시작이다. 미지정은 둘 다 채택 구성이다.

## 검증·게시 상태

8회 원자료와 초기 판정은 [보고서](../../retrieval/reports/2026-10-16-rag-context-empty/README.md)에 보존한다. 신고 경로 OR/AND 차이와 결합 경로 실생성 미검증은 남는다. 추가 유료 호출 없이 mock·정적·준비상태 확인으로 연결을 검증한다. 배포 전후 실제 결과는 완료 시 아래에 기록한다.

로컬 준비 진단 통과 후 저장소 소유 개발 프로세스 그룹을 정상 종료하고 npm run dev를 재시작했다. API /health/ready 및 웹 프록시 /api/health/ready는 ready, /chat은 HTTP200이다. 실제 생성 요청이나 문서 변경은 하지 않았다.
