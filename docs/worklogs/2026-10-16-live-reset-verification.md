# 실제 운영 초기화·LLM 호출·로컬 예약 활성화

사용자가 이전 검증에서 제외했던 실제 운영 전체 초기화, LLM 호출, 로컬 타이머 활성화와 자정 검증을 추가 요청했다. AI가 아래 작업을 수행했다. 기준 운영 코드는 `b87d22e`이며 프롬프트·모델·출력 계약은 변경하지 않았다.

## 실제 완료와 실패

| 항목 | 확인 결과 |
|---|---|
| 운영 백업 | 문서·생성 예산 daily 백업 성공. 초기화 직전 문서 pre-reset 백업 추가 생성 |
| 실제 운영 초기화 | 2026-10-16 07:54:02–07:54:05 KST, 기존 systemd service 수동 시작, Result=success/exit0 |
| 초기화 후 준비 | API ready, 검색71개·missing0, worker 재개 |
| 연차 질문 | 공개 `/api/ask` 200·ok=true, 16.50초, 입력7769/출력1473토큰 |
| 개인정보 메일 오발송 질문 | 공개 `/api/ask` 502, 22.57초, 입력7436/출력2086토큰, generation_result=parse_error |
| 로컬 예약 | 사용자 systemd timer enabled/active, 매일00:00 Asia/Seoul, Persistent=false |
| 로그아웃 후 로컬 유지 | jake Linger=no→yes. PC 종료·절전에서의 실행을 보장하지 않음 |

실제 생성은 총2회, 자동 재시도0회다. 사고 질문 실패는 생성 응답의 JSON/answer 계약 검증 실패다. `generation/validation.py`는 JSON 구문 오류, 객체 아닌 루트, answer 외 키, answer 비문자열을 모두 parse_error로 묶는다. 원응답을 저장하지 않는 운영 로그만으로 이 중 무엇인지 확정할 수 없다. timeout·잘림·검색 실패로 보고하지 않는다. 정상 연차 답변도 이번 연결 점검만으로 문항별 품질 승인을 내리지 않았다.

운영 pre-reset 백업은 `/var/lib/sanaebi/backups/pre-reset/pre-reset-20261016T075403+0900-b7b922c4.sqlite3`, daily 문서 백업은 `/var/lib/sanaebi/backups/daily/daily-20261016T075350+0900-a8160b1f.sqlite3`다. 운영 문서는 사용자 요청대로 기준71문서로 실제 교체됐고 이전 이력은 백업에 남는다. 생성 예산은 초기화하지 않았다.

로컬 root 비대화형 sudo는 사용할 수 없어 `~/.config/systemd/user/sanaebi-demo-reset.service|timer`에 기존 템플릿을 사용자 서비스로 설치했다. User 지시어만 생략하고 절대 uv·프로젝트·공유 .env 경로와 no-sync 실행을 유지한다. 실제 source/DB/root/bundle 사전 검증을 통과했으며 로컬 DB를 지금 수동 초기화하지는 않았다. 예약에 따라 이후 기준 자료로 초기화된다.

## 자정 검증: 과거 실제 실행과 다음 실행을 구분

운영 journal에서 **2026-10-16 00:00:00 KST 시작, 00:00:02 성공**을 확인했다. 타이머의 LastTrigger도 해당 자정이다. 이는 실제 예약 실행이지만 새 릴리스 배포 전 기록이므로 새 코드의 자정 실행 증거로 사용하지 않는다.

새 코드의 다음 실제 자정은 **2026-10-17 00:00 KST**다. 현재 미래이므로 검증 완료로 처리하지 않는다. 운영·로컬에 각각 읽기 전용 일회성 `sanaebi-reset-verify-20261017.timer`를 **00:06 KST**로 활성화했다. 초기화 서비스의 최대5분 이후 아래를 수집한다.

- 서비스 Result/exit code와 실제 시작 시각이 예정 자정 구간에 들어가는지.
- 원래 reset timer의 LastTrigger가 같은 자정 구간인지. 이전 수동 성공을 재사용하지 않는다.
- 현재 색인 ready=true/missing0, 해당 시간대의 journal.

검증기는 문서 쓰기·초기화·생성 호출·자동 재시도를 하지 않는다. 사전 probe는 이전/빈 시각을 보고 verified=false를 기록했다. 이를 미래 검증 성공으로 해석하지 않는다. observer만 Persistent=true이므로 늦게 기동하면 기록을 점검하되 놓친 reset을 대신 실행하지 않는다.

결과 위치:

- 로컬: `tmp/live-reset-verification-2026-10-16/local-midnight-result.json`
- 운영: `/var/lib/sanaebi/verification/2026-10-17/result.json`

다음 확인 명령:

```bash
cat tmp/live-reset-verification-2026-10-16/local-midnight-result.json
ssh sanaebi 'sudo -n cat /var/lib/sanaebi/verification/2026-10-17/result.json'
```

결과가 없거나 verified=false면 미완료/실패다. 이 채팅에서 나중에 자동으로 보고한다는 보장은 하지 않는다. 결과 확인 후 일회성 observer timer는 비활성화할 수 있으며 원래 매일 초기화 timer와 구분한다. 로컬 예약 중지는 `systemctl --user disable --now sanaebi-demo-reset.timer`다.

## 기록과 남은 범위

실행·응답·시간·안전한 토큰 로그·설정 경로·probe는 저장소 내부 `tmp/live-reset-verification-2026-10-16/`에 보존한다. 비밀키와 실제 환경 파일은 기록/커밋하지 않는다. 발표 PDF/PPTX는 무관한 사용자 파일로 보존했다.

현재 남은 항목은 새 릴리스/로컬의 실제 자정 결과 재조회와 사고 질문 parse_error의 세부 원인이다. 후속 원인 분석은 제한된 비공개 원응답 수집 또는 격리된 출력 형식 비교가 필요하며 이번에 프롬프트/strict 모드를 바꾸지 않았다. 전원 손실·고부하는 사용자 요청대로 제외하지만 Oracle Cloud 관리만으로 애플리케이션 복구·과부하 처리가 보장된다는 뜻은 아니다.

Notion 서비스 처리 기준·운영 규칙·기존 개인 일지에 실제 초기화, 생성2회 중1회 parse_error, 로컬 활성화, 과거 자정 성공과 미래 자정 미검증을 구분해 추가하고 세 페이지의 핵심 내용·보고서 링크를 재조회했다. Git은 문서만 `[skip ci]`로 게시하며 추가 배포는 하지 않는다.
