# 공개 시연 배포·CI/CD 구현 기록

시작 시점 main `55a060c06d8577f65c0a0b4615927f92892d8e82`에서 별도 `feat/deployment-cicd-20261015` worktree를 구성했다. 기존 기능 브랜치 전체를 병합하지 않고 사용자 미커밋 웹 변경을 복사해 검증 대상으로 포함했다. 원래 worktree·학습 결과는 보존한다.

## 검증 진행 상태

- 서버 전용 HF 토큰으로 pinned private 모델 config 접근 HTTP 200 확인.
- API 제한·KST 영속 생성 예산·health probe 구현. 클라이언트 취소 후에도 실제 작업 종료까지 동시 요청 슬롯 유지.
- ARM64 CPU 의존성·nginx allowlist·배포/백업/reset helper·Delivery workflow 준비.
- 웹 테스트 71개(429 안내·입력 보존 포함), lint·typecheck·빌드 통과. production npm audit 취약점 0개.
- 서버 Docker 설치, deploy SSH 접속, 고정 host key, production main 환경 정책 확인. 자동 배포는 첫 검증 전까지 비활성화.
- archive 테스트의 로컬 DB 의존성·HF 테스트 runner 불일치를 수정한 뒤 전체 Python 630개 통과.
- 실제 서버에서 aarch64, PyTorch 2.14.1+cpu, CUDA 미포함을 확인했다. HF 5개 파일 다운로드·해시 검증과 네트워크/토큰 없는 캐시 재사용을 확인했다.
- 새 nginx 설정을 별도 설정 파일로 nginx -t 검증했고, 설치한 root 배포 wrapper --help와 잘못된 release ID 거부를 확인했다.

아래 기록은 준비 과정의 시점별 결과이며, 실제 운영 검증은 마지막 구역을 기준으로 확인한다.

- [ARM64 측정 원자료](evidence/2026-10-15-arm64-runtime.json): 저장 예측 133/133 일치, cold 571.9ms, warm 평균 105.237ms, peak RSS 912601088 bytes. mock 동시 요청 1·2 모두 초과 429 즉시 반환. 실제 유료 생성 부하를 의미하지 않는다.
- 독립 검토로 최초 배포 rollback, ContextVar, 운영 로그, DB mount 격리, 강제 종료 복구, nginx activation 재시도 문제를 발견하고 보완했다. 배포·reset 관련 34개 테스트 통과.

- 사용자 확인에 따라 main `2070dc6`까지 통합했다. `shadow` 기본값과 Luna 출력 한도 16,384를 포함하며 shadow의 CLARIFY·UNSUPPORTED 생성에도 실제 호출 예산이 적용됨을 회귀 검증했다. 관련 39개 테스트와 Ruff 검사 통과.

## main 통합과 Actions

- 사용자 승인된 shadow·출력 설정과 기존 웹 변경을 포함한 전체 Python 688개 테스트 통과. PR [#8](https://github.com/KANT-2nd-project/sanaebi/pull/8)의 [최종 CI](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38697002812)는 Python·웹·ARM64 이미지 실행 모두 통과했다. main 병합 SHA는 `6ef40a71043cf9f0d40a490bab9dc901a39bef9e`다.
- 첫 수동 배포 실행 중 main에 개발 실행 명령 수정 `4d4c0f4`가 게시되어, 오래된 SHA 배포 차단 검사가 배포를 중단했다. 이때 서버 교체는 시작되지 않았다. 새 main으로 수동 배포를 다시 실행한다.
- GHCR 익명 pull 토큰 요청은 HTTP 401로 거부되었다. 서버는 Actions의 임시 registry 인증을 사용한다.

## 첫 운영 배포와 복구 검증

[수동 Delivery](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38698120187)가 `4d4c0f4`에서 전체 성공했다. HTTPS 질문·문서 관리가 공개되었고, GitHub environment·고정 SSH host key·GHCR 임시 인증을 통한 배포와 종료 후 registry 로그아웃을 확인했다.

- 최종 이미지의 ARM64 CPU 분류 회귀 133/133 일치. cold 550.701ms, warm 평균 105.799ms, p95 155.111ms, peak RSS 912433152 bytes. mock 동시 질문 1·2개에서 초과 429 즉시 반환.
- 실제 HTTPS 브라우저에서 질문 1건 생성 성공, 문서 생성→수정 v2→게시→새로고침 유지 확인. 429 화면은 브라우저에서 응답을 모의해 입력 보존을 확인했고, 실제 서버에서도 빈 입력 4회에 422·422·422·429와 Retry-After 10을 확인했다. 추가 유료 검증은 하지 않았으며 공개 이후 다른 요청도 카운터에 집계됐다.
- 공개 화면·문서 API 200, Swagger·진단·레거시 API 404. 외부 8000·18000·18001 접속 실패, 실제 API listen은 127.0.0.1:18000.
- backup·reset systemd service를 실제 실행했다. 문서는 기준 71개로 복원되고 카운터는 13→13으로 유지됐다. 일별 문서·카운터, 배포 전·reset 전 백업 4개 모두 SHA-256 확인 후 별도 임시 파일로 복원하여 SQLite integrity_check 통과.
- 점검 전환·요청 종료 후 실제 서버 재기동을 수행했다. boot ID 변경과 Docker·nginx·API readiness·timer 자동 복구 확인. 재기동 후 카운터 14회로 유지되었고 점검을 해제했다.
- 자정 timer의 다음 실행은 2026-10-15 15:00 UTC(KST 자정)로 확인했다. 실제 자정 도달을 기다린 검증은 아니며 동일 service의 수동 실행 결과다. 배포 중 강제 종료·rollback은 자동화된 실패 주입 테스트로 검증했으며 운영 서비스를 고의로 중간 종료하지 않았다.

상세 수치는 [운영 검증 자료](evidence/2026-10-15-production-verification.json)를 따른다. 첫 수동 검증 후 자동 배포를 활성화하고 이 기록의 main push로 자동 배포를 검증한다.
