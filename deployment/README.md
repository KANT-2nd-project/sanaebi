# 공개 데모 운영과 CI/CD

로컬 통합 준비는 `npm run setup:local -- --init-documents`, 실행은 `npm run dev`를 사용한다. 기존 DB·전체 삭제 상태는 보존하며 검색 색인과 기본 복원 묶음을 함께 준비한다. [준비·진단 상세](../docs/rag-runtime.md#준비와-실행).

**[사내비 바로 사용하기](https://sanaebi.29232923.xyz/chat)**

상시 운영하는 공개 데모입니다. 공용 가상 문서를 사용하며 누구나 익명으로 문서를 편집·게시할 수 있습니다. 문서는 매일 한국시간 자정에 기준 가상 문서로 초기화됩니다. 실제 사내 자료나 개인정보는 입력하지 마세요.

공개 도메인의 nginx·HTTPS에서 정적 웹과 `/api/`를 함께 제공한다. API는 ARM64 CPU Docker 컨테이너, Uvicorn 1 worker이며 `127.0.0.1:18000`만 수신한다. 웹에 필요한 질문·문서 API만 공개한다. 기존 로컬 실행은 [로컬 nginx](local-nginx.md)를 따른다.

구성 파일과 실제 운영 검증 상태는 구분한다. 최초 배포는 [초기 기록](../docs/worklogs/2026-10-15-deployment-cicd.md), 후속 배포와 실제 shadow + full 설정 확인은 [main 배포 기록](../docs/worklogs/2026-10-15-main-deploy-doc-sync.md)을 따른다. 배포 성공은 전체 답변 품질 승인이나 무중단 운영 보장을 뜻하지 않는다.

## 모델과 영속 데이터

모델은 Hugging Face private `js2923/sanaebi-koelectra-base`에서 배포할 때만 내려받는다. revision `4a1d0c7964072535a52a66efe29389a6470dd6f4`와 다섯 파일의 크기·SHA-256은 [모델 manifest](model-release.json)에 고정한다. 임시 다운로드를 검증한 뒤 원자적으로 게시하고 검증된 캐시만 재사용한다. 운영 API에는 모델을 읽기 전용으로 연결하며 HF 토큰을 전달하지 않는다. 학습 환경·생성 프롬프트는 유지한다. 현재 코드의 미설정 기본값은 `advisory`이며 정상 서버 라벨을 생성 참고 정보로 전달한다. 명시적 `shadow`·`gate` 환경 설정은 우선한다. 이번 변경에서 운영 설정 변경·배포·재시작은 하지 않았다. Luna 출력 한도 16,384와 모든 실제 호출의 동일 일일 한도를 유지한다. [채택·원복 경계](../docs/worklogs/2026-10-16-adopt-advisory.md)를 따른다.

| 경로 | 용도 |
|---|---|
| `/srv/sanaebi/releases/<sha>-<run>/` | release manifest·웹·모델 manifest |
| `/srv/sanaebi/current`, `previous` | 활성·이전 release 포인터 |
| `/srv/sanaebi/models/` | 검증 모델·활성 포인터 |
| `/srv/sanaebi/embeddings/` | 고정 revision으로 검증한 모델별 저장본과 KURE 분할 tokenizer |
| `/srv/sanaebi/retrieval-baselines/schema-vN/` | 릴리스별 schema와 host 기준 문서에서 만든 읽기 전용 기본 벡터 묶음 |
| `/srv/sanaebi/retrieval-bindings/` | release ID와 모델·schema·기준 원본을 연결하는 descriptor |
| `/srv/sanaebi/assets/_next/static/` | 이전 페이지에서도 사용할 해시 자산 |
| `/var/lib/sanaebi/runtime/documents.sqlite3` | 공개 시연 문서 |
| `/var/lib/sanaebi/runtime/retrieval/` | 게시 문서 revision에 연결된 가변 검색 인덱스 |
| `/var/lib/sanaebi/runtime/generation-budget.sqlite3` | 문서 초기화와 독립된 일일 생성 카운터 |
| `/var/lib/sanaebi/backups/` | 일별·배포 전 SQLite 백업 |
| `/etc/sanaebi/` | root 전용 런타임 설정·토큰 |

## 공개 시연 제한

질문·문서 편집·게시를 익명 공개한다. 실제 사내 자료나 개인정보는 입력하지 않는다. 문서는 KST 자정에 기준 가상 문서로 복원된다.

- 질문: IP별 분당 6회, burst 3회. 진행 중 질문 2개 초과 시 대기열 없이 429. `SANAEBI_MAX_INFLIGHT_ASKS=1`로 줄일 수 있다.
- 문서 쓰기: IP별 분당 12회, burst 5회와 기존 본문 크기 제한.
- 실제 생성 시도: 전체 KST 하루 1,000회. provider 호출 직전 SQLite로 원자 예약하며 실패·timeout도 포함한다. `gate` 모드의 고정 안내·빈 문서 응답은 제외한다.
- 초과 응답: 기존 `{ok,text,reason}`와 `Retry-After`를 포함한 429. 웹은 입력·안내를 보존하고 자동 재호출하지 않는다.
- 호출 수 상한은 금액 상한이 아니다. 원문 trace는 운영에서 끄고 생성 상태·사용량·지연만 관측한다.

## Host 도구 갱신과 배포 검증

Delivery는 이미지·웹·릴리스 manifest를 게시하며 root 소유 host helper와 Compose를 자동 교체하지 않는다. 관련 코드가 바뀌면 병합 전에 기존 도구·Compose·timer 설정을 백업하고 검토한 checkout의 `scripts/install_production_host.sh`로 갱신한다. 실제 `api.env`, 자격증명, host 기본 원본과 운영 DB는 덮어쓰지 않는다. 설치 후 helper의 `--help`를 저장소 밖에서 확인한다.

자동 배포가 켜져 있으면 main 병합으로 한 번 배포하며 별도 dispatch를 중복 실행하지 않는다. candidate 준비·readiness 후 활성 SHA, API/indexer, 복원 preview, HTTPS를 확인한다. 문서 전체 삭제·복원 시험은 격리 DB에서만 수행한다. rag readiness는 색인뿐 아니라 기본 복원 묶음도 검증하므로 기존 full readiness 성공만으로 RAG 준비를 판단하지 않는다.

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

릴리스는 기존 schema v1을 계속 지원하며, 검색 descriptor가 포함된 schema v2도 만들 수 있다. v1은 항상 기존 `full` 문서 흐름을 사용한다. 신규 v2 descriptor 기본값은 `rag`이며 검색 worker와 KURE 검색 경로를 준비한다. `/etc/sanaebi/api.env`의 명시적 `SANAEBI_RETRIEVAL_MODE`가 우선하며, 과거 descriptor의 `full` 기본값과 descriptor 없는 v1의 full 동작은 유지한다. 실제 배포 모드·확인 결과는 [로컬 준비·배포 기록](../docs/worklogs/2026-10-16-local-rag-startup.md)에서 관리한다. 설정을 바꾼 뒤에는 해당 릴리스를 다시 배포해야 API와 worker가 같은 모드로 시작한다. 배포 helper는 실제 실행 중인 API의 이전 모드를 기록해 실패·중단 복구에서 그 모드를 다시 적용한다.

[v3 검색 비교](../retrieval/reports/2026-10-15-retrieval-v3/README.md)는 C를 유지했다. 이번 비교로 새 재정렬 모델이나 새 벡터 묶음을 배포 준비에 추가하지 않는다. 로컬 CPU2 검증은 실제 운영 2vCPU 승인과 다르며 운영 전환은 별도다.

RAG 릴리스 준비 때 배포 helper는 공개 KURE-v1과 분할용 Tiny tokenizer의 고정 revision·파일 SHA를 검증해 `/srv/sanaebi/embeddings/`에 준비한다. API와 indexer에는 Hugging Face 자격 증명을 전달하지 않는다. 최초 host baseline은 컨테이너 이미지에서 한 번 복사하고 이후에는 이 host 파일을 기준 원본으로 보존한다. 각 RAG 릴리스는 그 원본과 릴리스가 선언한 schema를 사용해 기본 벡터 묶음을 만들고, 임시 DB에서 후보 검색 색인이 준비되는지 확인한다. 검색 번들과 활성 문서 DB의 연결값은 release별 binding에 보관하므로 schema가 바뀌어도 이전 묶음을 삭제하거나 새 묶음으로 덮어쓰지 않는다.

RAG의 문서 변경 API도 색인 준비까지 기다리므로 API와 indexer에 같은 기본 원본·벡터 묶음을 읽기 전용으로 연결한다. 원본은 `SANAEBI_RETRIEVAL_SOURCE`, 묶음은 `SANAEBI_RETRIEVAL_BASELINE`을 사용한다. 기본 복원 요청 전에 묶음의 원본·spec 일치를 확인하며 이미지의 원본으로 host 자료를 덮어쓰지 않는다. API·worker·복원 CLI의 색인 잠금은 작업 단위다. 부분 실패의 동일 요청 재시도는 [RAG 실행 계약](../docs/rag-runtime.md#문서-변경-응답과-검색-반영)을 따른다. 이 변경의 코드 게시와 운영 배포는 별개다.

RAG 모드의 자정 초기화는 사전 점검 후 indexer를 멈추고 문서 DB를 백업한 다음 기준 문서와 벡터 묶음을 함께 복원한다. 준비 상태를 확인한 뒤 worker를 다시 시작한다. 벡터 연결만 깨졌다면 다음 mapping-only 복구 명령을 사용한다. 이 명령은 기준 문서와 현재 문서 DB를 재초기화하지 않는다.

```bash
sudo python3 /usr/local/libexec/sanaebi/scripts/production_maintenance.py restore-retrieval
```

전체 자정 초기화는 기존 systemd timer가 실행하는 `production_maintenance.py reset` 경로를 따른다. 일반·RAG 전용 CLI의 공통 처리와 QA 판정 정정, 후속 배포 검증은 [초기화 통합 기록](../docs/worklogs/2026-10-16-reset-unification.md)을 따른다. 릴리스 준비·복구 절차는 해당 helper가 담당하며, 실제 운영 전환은 배포 검증 후 별도로 진행한다.

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

## KURE 채택 이후 준비 상태

[KURE 채택·연결](../retrieval/reports/2026-10-16-kure-adoption/README.md)에 따라 신규 descriptor·Compose·모델 준비의 기본값은 KURE다. 모델 디렉터리의 `splitter/`에 고정 Tiny tokenizer만 포함하며 Tiny 가중치는 요구하지 않는다. 새 spec의 색인·기본 벡터를 준비하고 기존 Tiny/full 릴리스 복구 자료는 보존한다. 코드 게시와 로컬 검증은 운영 host 원본 확인·실제 배포를 뜻하지 않는다.

## v7 RAG 사용자 채택

서버 RAG의 미설정 프로필은 `examples_answer_scope_v7_rag_readability`이며 명시적 환경변수가 우선한다. 독립 CLI/full은 v5다. 실험 게이트는 미달했지만 사용자가 알려진 누락을 수용해 선택했다. [릴리스·실제 호출·원복 기록](../docs/worklogs/2026-10-16-rag-v7-adoption.md)에서 코드 기본값과 운영 적용 여부를 구분한다.
