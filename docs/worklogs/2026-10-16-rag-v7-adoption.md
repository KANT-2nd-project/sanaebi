# v7 RAG 사용자 채택·배포 기록

## 결정

2026-10-16 사용자가 알려진 안내 누락을 수용하고 `examples_answer_scope_v7_rag_readability`를 서버 RAG 기본값으로 선택했다. 사전 채택 조건은 미달했으며 [24회 비교의 원점수·보류 판정](../../generation_evaluation/reports/2026-10-16-rag-readability/README.md)은 그대로 보존한다. 기준점5/8·v6 5/8·v7 7/8 내용 통과이며, 사고 대응 후속 인계 누락과 조건부 대안의 번호 배치는 다음 개선 대상이다. 서비스 품질 승인이나 일반 정확도 입증이 아니다.

사용자는 선택·배포 범위를 결정했고 AI가 구현·검증·실행·기록을 수행했다. 사용자 독립 구현이나 사람 검수로 표현하지 않는다.

## 적용

서버 설정의 미설정 RAG 기본값만 v7로 바꾼다. 기존 v5 RAG 상수와 본문은 비교·원복용으로 보존한다. 독립 CLI/full v5, Luna xhigh/16384/180초/prompt_json, 검색·문맥 보충·advisory와 공개 JSON 계약은 유지한다. 기존 안전 생성 로그에 profile과 prompt_roles_sha256만 추가하며 원문·키·예외 내용은 추가하지 않는다.

로컬·운영 사전 확인에서 SANAEBI_RAG_PROMPT_PROFILE 재정의가 없었다. 이전 운영 릴리스는 b87d22eeffaea0b62cb9ae674c6265fcdd9ccb64-38818411112다. 운영 DB와 예약 설정은 보존한다.

## 검증·게시 상태

아래 실행 기록은 배포 후 실제 확인 결과다. 실모델 호출은 로컬/운영 도움 소개 각1회, 총최대2회로 제한한다. 기존24회 비교와 별도 연결 검증이며 자동 재시도하지 않는다. 실패도 사용한 호출로 기록한다.

## 원복

이전 RAG 동작은 `SANAEBI_RAG_PROMPT_PROFILE=examples_answer_scope_v5_rag_service_v1`로 명시하고 로컬은 서버 재시작, 운영은 기존 Delivery 재배포 절차로 반영한다. 준비상태/API/JSON 장애 발생 시 기존 배포 helper의 이전 릴리스 복구를 사용한다. DB를 이전 백업으로 덮어쓰지 않는다. `examples_answer_scope_v5`는 full용 동작이므로 이전 RAG 원복값과 구분한다.

### 로컬 실제 연결 확인

기존 개발 프로세스를 종료하고 npm run dev로 재시작했다. 게시71개·missing0·API ready를 확인했다. 실제 도움 소개1회는 HTTP200, v7 프로필, 입력9298/출력221토큰, 생성3.308초·브라우저3.815초였다. 보수적 비용 추정 $0.00249025다. 화면은2문단·불릿0·가로 넘침0·페이지 오류0으로, 연결은 성공했으나 도움 소개 목록화는 이번 응답에서 재현되지 않았다. 추가 호출·튜닝하지 않았다. 운영 검증은 아래 후속 기록으로 구분한다.

### 게시 전 검증

최종 전체 Python1076개 통과, Ruff check 및 format check(624파일) 통과. 최초 재실행은 안전 로그 필드 추가에 따른 기존 계약 테스트1건 실패였고 허용 필드/원문 비노출 검사를 갱신한 뒤 전체 재실행했다. 실험 입력 재조립에서 저장된 v7 system/user와 완전 일치함을 확인했다.

### 운영 배포·실제 연결 완료

[Delivery 38829379362](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38829379362)의 Python·웹·ARM64 이미지·배포가 모두 성공했다. 활성 릴리스는 `46d22d4ad1bf7d256da37ea3717ff930dae0e418-38829379362`, 실행 이미지 ID는 `sha256:cc4198da0e9102ec80fd4337be54e74a1ae802f0bbf5a4801847cce29d0ccbc5`다. API ready, 검색worker 실행 및71/71·missing0, 기존reset/backup timer active를 확인했다. 실제 설정은 v7 RAG·advisory이며 프로필 환경변수 재정의가 없다. 운영 DB 전체 초기화나 예약 설정 변경을 하지 않았다.

공개 /chat 도움 소개1회는 HTTP200, 입력9298/출력308토큰, 생성3.992초·브라우저4.567초,2문단·불릿5·가로 넘침0·페이지 오류0이었다. 로컬과 운영의 실제 프롬프트 해시는 동일하다. 총2회·자동재시도0회, 비용 추정 합계 **$0.00504575**이며 실제 청구액이 아니다. 로컬에서는 불릿이 없었으므로 반복 구조 준수를 보장하지 않는다. [응답·사용량·해시·화면 측정](../../generation_evaluation/reports/2026-10-16-rag-readability/adoption-smoke.json)을 보존했다. 원 스크린샷과 실행 로그는 `artifacts/experiments/rag-v7-adoption-20261016/`에 있다.

Git 기능 커밋: `75a4527` 보관 정리 → `36ae05f` 후보·실행기·테스트 → `46d22d4` 평가·사용자 채택·안전 로그. main 푸시 후 같은 SHA의 Delivery로 한 번 배포했다. 후속 기록 커밋은 `[skip ci]`로 게시하며 운영 코드 SHA와 기록용 main SHA가 다른 이유를 구분한다.

### Notion 동기화

[서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b)과 [기존 생성 개인 일지](https://www.notion.so/3f905a3cdadc8146a9bbedb690ab5ecf)에 사용자 채택·실험 보류·로컬 결과·배포 진행을 먼저 기록한 뒤, 실제 성공 후 같은 구역을 완료 상태로 갱신했다. 저장 후 두 페이지를 재조회해 릴리스·비용·Git 보고서/Delivery/실호출 근거 링크와 AI 수행 구분을 확인했다. 기존 내용은 보존했다.
