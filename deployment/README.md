# 로컬 nginx 실행

WSL/Linux에서 `web/out/`과 FastAPI를 같은 출처로 제공합니다. 공개 가능한 예시 질문을 사용하는 로컬 시연용이며 HTTPS·인증·외부 공개 설정은 포함하지 않습니다.

## 최초 설치

WSL 터미널에서 시스템 nginx를 설치합니다. sudo 인증은 터미널에서 입력하며 프로젝트에 저장하지 않습니다.

```bash
sudo apt-get update
sudo apt-get install nginx
```

실행 도구는 nginx 실행 파일과 `/etc/nginx/mime.types`를 사용합니다. `/etc/nginx/nginx.conf`와 시스템 서비스는 변경하지 않습니다. 이후 프로젝트 명령에는 sudo를 사용하지 않습니다.

## 빌드·실행

아래는 저장소 루트 기준입니다. 최초 프런트 의존성 설치는 `npm ci --prefix web`으로 합니다.

```bash
npm run build --prefix web
uv run --locked python scripts/local_nginx.py check
```

터미널 하나에서 FastAPI를 실행합니다. 패키지가 설치되지 않았다면 먼저 `uv sync --locked`를 실행합니다.

```bash
uv run --locked uvicorn app.fastapi_main:app --host 127.0.0.1 --port 8000
```

다른 터미널에서 프로젝트 nginx를 시작합니다.

```bash
uv run --locked python scripts/local_nginx.py start
```

브라우저로 http://127.0.0.1:8080 에 접속합니다. Next dev/start 프로세스는 필요하지 않습니다. 현재 `/api/ask`는 FastAPI `/ask`로 중계하고 서버는 질문을 분류한 뒤 선택한 LangChain 모델의 답변을 반환합니다. 분류 모델과 답변 모델을 별도로 준비해야 하며, 새 모델 경로의 브라우저 종단 검증과 답변 품질 검증은 별도입니다.

```bash
uv run --locked python scripts/local_nginx.py stop
```

nginx 종료 후 FastAPI를 실행한 터미널에서 Ctrl+C로 해당 프로세스를 종료합니다. 도구는 FastAPI나 시스템 nginx를 종료하지 않습니다. nginx의 정상 종료는 진행 중 연결 정리를 위해 최대 수 초 걸릴 수 있습니다.

## 설정·프로세스 관리

`nginx.conf`는 경로·포트 자리표시자를 포함한 템플릿이므로 직접 nginx -c에 넘기지 않습니다. 실행 도구가 저장소 위치를 계산해 `tmp/nginx/nginx.conf`를 생성합니다. 어느 디렉터리에서 호출하더라도 스크립트 위치 기준으로 동작합니다.

- 기본 주소는 `127.0.0.1:8080`, upstream은 `127.0.0.1:8000`입니다.
- 검사나 시작 시 `--port 18080 --upstream-port 18000`으로 로컬 포트를 바꿀 수 있습니다. 저장소당 관리 인스턴스는 하나이며 실행 중 재시작은 거부합니다.
- `check`는 별도 check.conf로 문법과 빌드 파일을 검사합니다. upstream 실행 여부·포트 점유는 보장하지 않으며 `start`가 listen 포트 점유를 검사합니다.
- PID·시작 시각·사용자·프로젝트 설정 경로가 일치할 때만 stop을 수행합니다. 불일치하면 종료를 거부하므로 임의 PID 파일을 수정해 재시도하지 않습니다.
- PID·제어 잠금·생성 설정·로그·임시 파일은 기존 Git 제외 경로인 `tmp/nginx/`에 저장합니다. 저장소 경로에 `$`나 개행은 사용할 수 없습니다.
- 정적 파일 갱신은 `stop → build → check → start` 순서로 합니다. 실행 중 out을 부분 교체하면 HTML·자산 버전이 섞일 수 있습니다.

## 경로·캐시·오류

`/chat`은 chat.html로, `/chat/`은 `/chat`으로 연결합니다. Next의 `/chat/...txt` 데이터도 그대로 제공합니다. 없는 UI/자산 경로는 404이며 홈으로 대체하지 않습니다. `/api/` 요청에는 정적 fallback을 적용하지 않습니다.

HTML·라우트 데이터에는 no-cache, 존재하는 `/_next/static/` 해시 자산에는 1년 immutable, 정상·오류 API에는 no-store를 적용합니다. upstream의 Cache-Control/Expires를 API 캐시 정책으로 교체합니다. FastAPI의 오류 상태·본문은 유지하고 nginx 자체 502/504는 HTML일 수 있습니다. 프런트가 이를 안전한 안내로 표시합니다.

연결 제한은 5초, upstream 읽기 사이의 대기 제한은 30초입니다. 브라우저의 총 요청 제한은 35초이며 자동 재호출하지 않습니다. 읽기 제한은 요청 전체의 절대 실행시간 제한이 아닙니다. 실제 모델 연결 시 예산을 다시 측정해야 합니다.

## 문제 확인

- 포트 사용 중: `ss -ltn '( sport = :8080 or sport = :8000 )'`으로 확인하고 기존 프로세스를 임의 종료하지 않습니다.
- 502: FastAPI 실행 상태와 `tmp/nginx/error.log`를 확인합니다.
- 504: upstream이 읽기 제한 내에 응답했는지 확인합니다.
- 정적 파일 누락: web에서 빌드한 뒤 check를 다시 실행합니다.
- 시작 실패: `tmp/nginx/launcher.log`와 `error.log`를 확인합니다.
- access.log에는 메서드·경로·상태·시간을 기록하며 질문 본문·쿼리·인증 정보는 기록하지 않습니다. 질문은 URL이 아닌 JSON 본문으로만 전송합니다.

```bash
curl -i http://127.0.0.1:8080/chat
curl -i http://127.0.0.1:8080/api/ask \
  -H 'Content-Type: application/json' \
  --data '{"question":"휴가 신청 절차를 알려주세요."}'
```

이 nginx는 개발 서버/HMR을 중계하지 않습니다. 기능 수정 중에는 저장소 루트에서 `npm run dev`로 Next와 FastAPI(8000)를 함께 띄우면 3000번에서 화면·HMR·실제 API 중계를 사용할 수 있습니다. 정적 배포 통합은 위 빌드·nginx(8080) 경로에서 별도로 확인합니다. 개발 실행기와 캐시 정책은 [프런트 안내](../web/README.md)를 따릅니다.

## 문서 관리 배포

빌드에 `out/admin/documents.html`이 필요합니다. `/admin/documents/`는 query를 유지해 `/admin/documents`로 이동합니다. 새 `/api/documents`도 기존 API 중계를 사용하며 FastAPI가 해당 문서 요청에512KiB 제한을 적용합니다. 기존 nginx 본문 제한은 유지하며 HTML 형태의 nginx 오류는 프런트가 안전한 안내로 처리합니다.

기본 SQLite는 `var/documents.sqlite3`, 경로 변경은 `SANAEBI_DOCUMENT_DB`를 사용합니다. [문서 관리·백업·이관 안내](../docs/document-management.md)를 따르세요. 인증 없는 로컬 가상 자료 범위이며 실제 사내 공유 배포는 지원하지 않습니다.
