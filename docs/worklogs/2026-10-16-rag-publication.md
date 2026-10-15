# RAG 변경 게시·재시작·배포 기록

## 사용자 결정과 범위

2026-10-16 사용자가 커밋·푸시·서버 재시작·공개 배포·Notion 게시를 승인했다. 이어 문맥 보충도 이전 대비 관측 개선을 우선하여 적용하도록 요청했다. 초기 8회 판정은 빈 근거 처리 채택·문맥 보충 보류였으며 그 점수를 바꾸지 않는다. AI가 구현·검증·게시·운영 확인을 수행한다.

서버 RAG는 v5_rag_service_v1과 문맥 보충을 결합한다. full·독립 CLI v5와 직접 RetrievalService 생성자의 확장 False는 보존한다. 확장 원복은 SANAEBI_RAG_EXPAND_CONTEXT=0, 빈 근거 처리 원복은 SANAEBI_RAG_PROMPT_PROFILE=examples_answer_scope_v5 지정 후 재시작이다. 미지정은 둘 다 채택 구성이다.

## 검증·게시 상태

8회 원자료와 초기 판정은 [보고서](../../retrieval/reports/2026-10-16-rag-context-empty/README.md)에 보존한다. 신고 경로 OR/AND 차이와 결합 경로 실생성 미검증은 남는다. 추가 유료 호출 없이 mock·정적·준비상태 확인으로 연결을 검증한다. 배포 전후 실제 결과는 완료 시 아래에 기록한다.

로컬 준비 진단 통과 후 저장소 소유 개발 프로세스 그룹을 정상 종료하고 npm run dev를 재시작했다. API /health/ready 및 웹 프록시 /api/health/ready는 ready, /chat은 HTTP200이다. 실제 생성 요청이나 문서 변경은 하지 않았다.

## 최종 검증과 운영 반영

- 최종 전체 Python1047개(79.536초), Ruff check·format604파일 통과. 변경 관련 문서의 상대 파일 링크83개 확인. 독립 AI 검토는 결합·설정 테스트17개를 실행하고 추가 차단 사항 없음으로 판정했다.
- 기능 커밋: 463ab1a 문맥 보충·원문 범위, caf1475 근거 상태·trace, 08d9bd7 서버 채택·원복, 3902b60 평가·문서. main 푸시와 원격 SHA를 확인했다.
- 다른 세션의 일지 전용 d7f7ed1이 뒤이어 게시돼 최신 main 기준으로 배포했다. 중복된 이전 실행38812457975는 취소했고 [최종 Delivery 38812507761](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38812507761)은 Python·웹 테스트/lint/typecheck/build·ARM64 이미지·배포 모두 성공했다.
- 운영 current: d7f7ed16fca9296074f919eb3ab6acbf98898f6a-38812507761. previous: 75fe7efc78d7dc1000774837e573350f17b71ce3-38811256976. API와 검색 worker가 교체됐고 기존 복구 릴리스를 보존했다.
- 배포 컨테이너 유효 설정: advisory / rag / examples_answer_scope_v5_rag_service_v1 / expansion=true. 내부 health ready, 공개 /chat HTTP200, 비공개 /api/docs HTTP404 확인.
- [Notion 서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b)과 [개인 일지](https://www.notion.so/3f905a3cdadc8146a9bbedb690ab5ecf)에 결정·초기 판정·AI 수행 범위·검증·배포 결과를 반영하고 재조회했다. 기존 역사·개인 학습 기록은 보존했다.
- 이번 게시 단계 추가 유료 생성0회. 8회 비교 이후 실답변 재평가·사용자 DB 초기화는 하지 않았다. 신고 경로 원문 차이와 결합 구성 실생성 품질 미검증은 남는다.

이 완료 기록은 배포 후 문서 전용 커밋으로 게시하며 skip ci를 사용해 동일 코드의 불필요한 재배포를 막는다. 원격 main 문서 커밋과 운영 코드 SHA가 다르다는 점을 구분한다.
