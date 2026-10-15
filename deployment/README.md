# 공개 시연 배포와 CI/CD

`sanaebi.29232923.xyz`의 기존 nginx·HTTPS에서 정적 웹과 `/api/`를 함께 제공한다. API는 ARM64 CPU Docker 컨테이너, Uvicorn 1 worker이며 `127.0.0.1:18000`만 수신한다. 웹에 필요한 질문·문서 API만 공개한다. 기존 로컬 실행은 [로컬 nginx](local-nginx.md)를 따른다.

구성 파일과 실제 운영 검증 상태는 구분한다. 실행 결과는 [작업 기록](../docs/worklogs/2026-10-15-deployment-cicd.md)을 따른다.

## 모델과 영속 데이터

모델은 Hugging Face private `js2923/sanaebi-koelectra-base`에서 배포할 때만 내려받는다. revision `4a1d0c7964072535a52a66efe29389a6470dd6f4`와 다섯 파일의 크기·SHA-256은 [모델 manifest](model-release.json)에 고정한다. 임시 다운로드를 검증한 뒤 원자적으로 게시하고 검증된 캐시만 재사용한다. 운영 API에는 모델을 읽기 전용으로 연결하며 HF 토큰을 전달하지 않는다. 학습 환경·분류 정책·생성 프롬프트는 유지한다.

| 경로 | 용도 |
|---|---|
| `/srv/sanaebi/releases/<sha>-<run>/` | release manifest·웹·모델 manifest |
| `/srv/sanaebi/current`, `previous` | 활성·이전 release 포인터 |
| `/srv/sanaebi/models/` | 검증 모델·활성 포인터 |
| `/srv/sanaebi/assets/_next/static/` | 이전 페이지에서도 사용할 해시 자산 |
| `/var/lib/sanaebi/runtime/documents.sqlite3` | 공개 시연 문서 |
| `/var/lib/sanaebi/runtime/generation-budget.sqlite3` | 문서 초기화와 독립된 일일 생성 카운터 |
| `/var/lib/sanaebi/backups/` | 일별·배포 전 SQLite 백업 |
| `/etc/sanaebi/` | root 전용 런타임 설정·토큰 |

## 공개 시연 제한

질문·문서 편집·게시를 익명 공개한다. 실제 사내 자료나 개인정보는 입력하지 않는다. 문서는 KST 자정에 기준 가상 문서로 복원된다.

- 질문: IP별 분당 6회, burst 3회. 진행 중 질문 2개 초과 시 대기열 없이 429. `SANAEBI_MAX_INFLIGHT_ASKS=1`로 줄일 수 있다.
- 문서 쓰기: IP별 분당 12회, burst 5회와 기존 본문 크기 제한.
- 실제 생성 시도: 전체 KST 하루 1,000회. provider 호출 직전 SQLite로 원자 예약하며 실패·timeout도 포함한다. 고정 안내·빈 문서 응답은 제외한다.
- 초과 응답: 기존 `{ok,text,reason}`와 `Retry-After`를 포함한 429. 웹은 입력·안내를 보존하고 자동 재호출하지 않는다.
- 호출 수 상한은 금액 상한이 아니다. 원문 trace는 운영에서 끄고 생성 상태·사용량·지연만 관측한다.

## 최초 호스트 준비

Docker·nginx·TLS와 배포 전용 `deploy` 계정이 필요하다. 검토한 checkout에서 root로 `bash scripts/install_production_host.sh`를 실행해 helper·Compose·sudo 범위·timer 정의를 설치한다. 기존 비밀 파일을 보존하고 nginx 활성 설정과 timer 실행은 변경하지 않는다.

운영자가 서버에서 직접 입력한다. 값은 Git·채팅·artifact에 넣지 않는다.

```bash
ssh -t sanaebi 'sudoedit /etc/sanaebi/api.env'
# OPENAI_API_KEY=<생성 API 키>
ssh -t sanaebi 'sudoedit /etc/sanaebi/hf-download.env'
# HF_TOKEN=<해당 private 모델 전용 읽기 토큰>
```

로컬 HF OAuth는 서버로 복사하지 않는다. GHCR은 배포 job의 짧은 수명 `GITHUB_TOKEN`을 SSH 표준입력으로 전달해 로그인하고 종료 시 로그아웃한다. API에는 registry 자격 증명을 주지 않는다. `deploy`는 Docker 그룹에 속하지 않으며 검증된 helper만 sudo로 실행한다.

GitHub `production` environment는 main만 허용한다. 환경 secret은 `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`다. host key는 신뢰된 기존 SSH 연결에서 가져와 고정한다. repository variable `ENABLE_AUTO_DEPLOY`는 첫 수동 배포 검증 후 `true`로 설정한다.

## CI와 교체

[Delivery workflow](../.github/workflows/delivery.yml)는 Python 검사·테스트, 웹 테스트·lint·typecheck·정적 빌드, ARM64 CPU 이미지 실행을 검증한다. main의 같은 SHA에서 웹 artifact와 GHCR digest를 release manifest에 묶는다. 수동 실행의 `deploy=true`로 최초 배포한다.

배포 helper는 공통 flock 아래 이미지·모델·격리 후보 readiness를 먼저 준비한다. 준비 실패 시 기존 서비스를 유지한다. 실제 교체는 점검 응답, 요청 종료 대기, SQLite 백업, API·웹 교체, readiness 확인 순서다. 실패하면 이전 이미지·웹·모델을 복원하며 사용자 변경이 생긴 DB를 자동 덮어쓰지 않는다. 강제 종료로 점검 표식이 남으면 다음 배포를 거부한다. 운영자가 journal·활성 포인터·컨테이너를 확인한 뒤 root 전용 `sudo /usr/bin/python3 /usr/local/libexec/sanaebi/scripts/deploy_release.py recover`를 실행한다. journal에 저장된 이전 포인터·이미지를 검증해 복원하고 readiness 성공 후 점검을 해제한다. DB는 덮어쓰지 않으며 CI 계정에는 recover 권한을 부여하지 않는다.

첫 정상 release 후 workflow가 root 소유 `sanaebi-activate-nginx`를 호출한다. 이 helper는 readiness와 정적 파일을 확인하고 기존 vhost를 백업한 뒤 준비된 설정을 설치한다. `nginx -t`·reload 실패 시 기존 설정으로 복구하며 이후 임의 vhost 변경은 덮어쓰지 않는다. 성공하면 `sanaebi-production-reset.timer`·`sanaebi-production-backup.timer`를 활성화한다. 이후 같은 vhost에서 release 포인터를 교체한다.

## 운영 확인과 복구

```bash
sudo docker ps --filter name=sanaebi-api
curl --fail http://127.0.0.1:18000/health/ready
systemctl list-timers 'sanaebi-production-*'
sudo python3 /usr/local/libexec/sanaebi/scripts/production_maintenance.py backup
sudo docker logs --tail 30 sanaebi-api
```

health·Swagger·분류 진단·레거시 API는 외부에서 허용하지 않는다. API는 비-root·읽기 전용 파일 시스템을 사용한다. SQLite와 모델은 이미지 외부에 남으며 Docker 재기동 시 API가 자동 복구된다.

수동 DB 복원은 점검 전환·요청 종료·현재 DB 별도 백업 후 검증된 백업을 복사하는 운영자 작업이다. 생성 카운터를 문서 백업으로 덮어쓰지 않는다. 자동 롤백은 코드·모델·웹만 복원한다. 백업 manifest와 SQLite integrity_check를 확인하고 별도 임시 경로에서 복원 검증한다.
