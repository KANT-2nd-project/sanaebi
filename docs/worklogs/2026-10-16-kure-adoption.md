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

모델·검색 연결 `8f73a99`, 복원·배포 준비 `c1f3bfb`, 문서·정리 기록 `8cba784`를 같은 로컬 main에서 커밋했다. 새 작업 공간 없이 원격 `feat/kure-adoption-20261016`에 게시해 [PR #15](https://github.com/KANT-2nd-project/sanaebi/pull/15)의 [CI](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38801247423)를 확인했다. Python2분2초·웹52초·ARM64 이미지2분51초가 통과했고 PR deploy는 건너뛰었다.

`[skip ci]` 제목으로 병합 명령을 실행하기 직전에 원격 main이 이미 PR 끝 커밋 `8cba784585accbb30cc3c377a3456cd0cc9c8cfc`로 갱신돼 PR이 병합 완료로 표시됐다. 이 직접 갱신에는 skip ci가 없어 [main push 실행](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38802074710)이 시작됐다. 운영 미배포 조건을 유지하기 위해 cancel과 force-cancel을 요청하고 `completed/cancelled`를 확인했다. Python·웹 job만 생성됐고 이미지·deploy job은 생성되지 않았다. 원격 ref 갱신의 실행 주체를 별도로 확인하지 않았으므로 특정 작성자의 행동으로 단정하지 않는다. 따라서 계획한 skip-ci 병합이 실행됐다고 기록하지 않는다. 이번 후속 기록 커밋에는 `[skip ci]`를 사용한다.

원격 main과 로컬 main의 코드 SHA, 게시 보고서 blob SHA를 대조했다. 변경49파일에 모델·DB·tmp·실제 환경 파일이 없고, 해당 변경 파일의 일반 credential 패턴 일치는0이었다. 저장소 전체·모든 비밀값 부재 보증은 아니다.

Notion [프로젝트 문서 안내](https://www.notion.so/3f805a3cdadc81e1a70bfe82c89cebe7), [서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b), [데이터·실험 절차](https://www.notion.so/3f805a3cdadc81d59dc9fec6e4fcca1d), [운영·개발 규칙](https://www.notion.so/3f805a3cdadc81aa9f48d8445d372b80)의 현재 계약을 KURE로 갱신하고 이전 보류·Tiny C 구역을 과거 기록으로 구분했다. 수정 직전 재조회하고 저장 후 현재KURE·과거기록·고정 Git 링크를 재확인했다.

동일 제목·담당자 중복0을 확인한 뒤 [새 개인 일지](https://www.notion.so/3fa05a3cdadc81b4b2ddf316a7be4ccb)를 생성했다. 최재선·검색/생성·2026-10-16·사용자 결정/AI 수행·본문·링크·게시 경위를 재조회하고 완료로 변경한 뒤 다시 확인했다. 과거 일지·다른 업무의 담당/기한/상태는 변경하지 않았다.

아카이브 사후 검증은 source+diff를 합친1,880개 고유 object(3,443,130,417바이트)와 재현 사본45개(170,805,091바이트) 모두 통과했다. 정리 최종 manifest SHA는 `d592c1e9f7f428091dd5a87113cf73f27f8b97c0a9c57d84cc83b7b1e28def64`다. 독립 최종 문서 검수에서도 수치·기여·운영 미검증 구분의 중대한 오류는 없었다.
