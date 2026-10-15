# KURE 검색 채택·서버 연결과 임시 작업 폴더 정리

사용자는 필수 근거 유지·전달량 감소를 우선해 KURE 채택을 결정하고, 기존 로컬 main에서 구현·검증·게시와 임시 폴더 정리를 요청했다. AI가 구현·독립 코드 검토·실제 로컬 검증·자료 보존·기록을 수행했다. 사용자 독립 구현이나 사람 검수로 표현하지 않는다.

## 작업 범위

시작점은 `/home/jake/workspace/projects/sanaebi`의 main `68b47f37d9ac12ad75bb832339fe842a577b184b`로 원격과 일치했다. 이 디렉터리에서 직접 작업했으며 새 worktree나 임시 저장소를 만들지 않았다. 다른 작업에서 새로 만든 label-minimal 작업 폴더는 정리 대상에서 제외했다.

모델·검색 계약, API/worker/복원 연결, 신규 배포 descriptor·준비 명령을 KURE로 맞췄다. 이전 Tiny/full 릴리스는 보존한다. 기존 확인 자료로 재튜닝하지 않았으며 생성 모델·프롬프트·분류 정책·공개 API·실제 환경 파일을 바꾸지 않았다.

수치·채택 판단의 기준은 [보고서](../../retrieval/reports/2026-10-16-kure-adoption/README.md), 원자료 보존·정리는 [경로 대응표](../../retrieval/reports/2026-10-16-kure-adoption/workspace-cleanup.md)다.

## 검증과 수정

- KURE 집중 테스트를 먼저 추가하고 미구현 import 실패를 확인한 뒤 계약을 구현했다. 독립 검토가 지적한 splitter 식별값 누락과 잘못된 pooling 형식·spec 혼용·동점 경계를 추가 검증했다.
- 초기 모델 준비에서 배포 파일 목록의 pooling 설정 누락을 실제 로딩으로 발견했다. 준비 descriptor에 고정 hash를 포함하고 재준비했다. 불완전 생성본은 임시 보존 후, 완성본과 모든 기존 파일의 해시가 같음을 확인하고 중복을 제거했다.
- 1차 Python 전체964개 통과(70.209초), 설치 CLI 보완 후 최종965개 통과(64.057초). KURE 집중11개·retrieval144개·관련 runtime30개, 배포/유지보수62개는 전체 검사와 중복되는 집중 검증이다.
- 독립 검토가 발견한 systemd 직접 실행 import 오류는 설치 레이아웃 subprocess 실패를 먼저 재현하고 수정했다. [독립 검토 기록](../../retrieval/reports/2026-10-16-kure-adoption/independent-review.md)을 따른다.
- 실제 KURE298벡터·108문항 점수/근거 동등, CPU2 동시1/2 p95 164.13/329.03ms·최대RSS2,539.60MiB, 실제 KURE+모의 생성 HTTP·복원/원본 보존 검증을 통과했다.
- 옛16개 작업 폴더 제거 후 모델 준비 검증·색인 status/once·restore-baseline·reset --check 다섯 명령이 모두 종료0으로 동작했다.

유료 API·실제 LLM·운영 접속·배포는 하지 않았다. 실제 운영2vCPU·host 원본 확인·사람 검수·답변 품질은 미완료다.

최종 Ruff check·format check(562파일), `git diff --check`를 통과했다. 상대 링크·앵커325개 실패0이며 [검증 요약](../../retrieval/reports/2026-10-16-kure-adoption/verification.json)에 기록했다. Markdown 링크·표 원문은 확인했으며 브라우저 렌더링을 새로 수행하지 않았다.

## 게시와 외부 반영

기능별 커밋, 같은 작업 폴더에서 원격 검증 브랜치 게시, PR CI, main `[skip ci]` 병합 후 결과를 기록한다. Notion 기술4페이지와 새 개인 일지는 원격 보고서 게시 후 반영하고 재조회한다. 과거 일지·다른 작업의 담당/기한/상태는 유지한다.
