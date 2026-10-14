# 사내비 프런트엔드

Next.js App Router·TypeScript·Tailwind CSS 4를 사용합니다. 서비스 소개(`/`)와 질문 화면(`/chat`)을 정적 HTML로 생성합니다. 첫 화면은 인사말·입력창·예시 질문이며, 전송 후 질문과 답변을 대화 목록에 누적하고 입력창을 하단에 유지합니다. 같은 출처의 `/api/ask`에 현재 질문 하나를 전송합니다. 현재 서버는 질문을 분류한 뒤 LangChain의 선택된 모델 답변을 반환합니다. 로컬 분류 모델·답변 모델 준비가 필요하며 새 경로의 브라우저 종단 검증은 별도입니다. 개발에서는 Next 개발 서버, 정적 배포에서는 프로젝트 nginx를 통해 FastAPI에 연결합니다.

## 개발

이 디렉터리(`web/`)에서 npm을 사용합니다. 최초 설치 또는 잠금 파일 기준 재설치가 필요할 때 실행합니다.

```bash
npm ci
npm run dev
```

질문 응답을 사용하려면 저장소 루트의 별도 터미널에서 FastAPI를 시작합니다.

```bash
uv run --locked uvicorn app.fastapi_main:app --host 127.0.0.1 --port 8000
```

http://localhost:3000/chat 에서 확인합니다. 개발 서버가 `/api/ask`를 FastAPI `/ask`로 중계하므로 nginx 없이 화면 수정과 실제 응답을 함께 확인할 수 있습니다. 화면과 정적 빌드는 FastAPI 없이 실행할 수 있습니다. 폰트는 시스템 한국어 글꼴을 사용하며 Google 폰트를 다운로드하지 않습니다.

## 검증과 빌드

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

타입 검사는 `next typegen`으로 라우트 타입을 생성한 뒤 `tsc --noEmit`을 실행합니다. 빌드는 `output: "export"` 설정으로 `out/`에 정적 파일을 생성합니다.

- `out/index.html`: 소개 화면
- `out/chat.html`: 질문 화면
- `out/404.html`: 없는 페이지 안내
- `out/_next/`: CSS·JavaScript 등 정적 자산

`out/` 전체를 정적 웹 서버에 전달합니다. 운영에 `next dev`나 `next start`를 사용하지 않으며 start 스크립트는 제공하지 않습니다. 프로젝트 nginx 설정은 `/chat`을 `chat.html`에 연결하고 존재하지 않는 경로는 404로 처리합니다. 설치·실행·종료·장애 확인은 [로컬 nginx 안내](../deployment/README.md)를 따릅니다.

개발·시연 단계이므로 소개·채팅·문서 관리 화면 모두 noindex를 유지합니다. noindex는 인증이나 접근 권한 검사를 대신하지 않습니다. 자세한 방향은 [프런트엔드 설계](../docs/frontend-architecture.md)를 참고하세요.

## 질문 요청과 테스트

대화는 현재 화면의 메모리에서만 유지됩니다. 새로고침·새 대화 시 초기화되며 서버는 이전 메시지를 참조하지 않습니다. 실제 신청·승인·개인 기록 조회는 지원하지 않습니다.

- 데스크톱: Enter 전송, Shift+Enter 줄바꿈. IME 조합 중 Enter·키 반복은 전송하지 않습니다.
- 모바일 주 입력 장치(`hover:none`과 `pointer:coarse`): Enter 줄바꿈, 버튼 전송.
- 예시 선택은 입력과 포커스만 옮깁니다. 입력창은 2행부터 200px까지 늘어납니다.
- 요청 중 입력을 읽기 전용으로 보존합니다. 성공 시 제출 입력을 비우고, 실패 시 보존합니다. 수정하지 않은 실패 질문은 같은 턴에서 재시도하고 수정한 질문은 새 턴으로 추가합니다. 메시지 재시도 버튼은 다른 작성 중 입력을 지우지 않습니다.
- 새 대화는 요청을 취소하며 늦은 응답을 무시합니다. 위쪽 기록을 읽고 있으면 응답 도착 시 스크롤을 강제로 옮기지 않습니다.

입력 앞뒤 공백을 제거한 `{question}`만 POST로 전송합니다. 브라우저 총 제한은 35초이며 자동 재시도하지 않습니다. 개발 프록시 제한은 30초입니다. 정적 배포의 nginx 연결 제한은 5초, 읽기 제한은 30초입니다. 개발 프록시 자체 연결 실패·시간 초과는 500, nginx는 502/504일 수 있으며 화면은 안전한 오류 안내와 입력 보존으로 처리합니다. 브라우저 취소가 서버의 모델 실행 종료를 보장하지는 않습니다.

`npm test`는 기존 TypeScript 컴파일러로 API 경계와 대화 상태 코드를 저장소의 `tmp/frontend-unit-tests/`에 컴파일한 뒤 Node 내장 테스트 러너를 실행합니다. 별도 패키지를 추가하지 않으며 Node 22 이상을 사용합니다. 테스트는 fetch/전송 함수를 대체하여 오류·timeout·취소·메시지 누적·재시도·늦은 응답 무시를 검증합니다. 실제 통합은 빌드 후 nginx→FastAPI에서 별도로 확인합니다.

`npm run dev`는 개발 전용 실행기 `scripts/dev.mjs`를 사용합니다. Next의 외부 rewrite에서는 설정의 headers가 누락되는 설치 버전 동작 때문에 실행기가 `/api/` 응답의 `Cache-Control: no-store`를 보장합니다. FastAPI의 상태·본문을 유지하고 upstream 캐시 헤더는 덮어씁니다. 운영용 Node 서버로 사용하지 않습니다. `npm run dev -- --hostname 127.0.0.1 --port 3000`으로 바인딩을 지정할 수 있습니다. 기본값은 기존 Next dev와 같은 전체 인터페이스·3000번입니다.

개발 시 오래된 CSS 복원을 막기 위해 Turbopack 개발 파일시스템 캐시를 비활성화합니다. HMR과 정적 빌드 캐시는 유지합니다. Tailwind 로더 앞의 `scripts/tailwind-loader.cjs`는 실제 CSS 입력의 해시를 컴파일 캐시 키에 포함해, 같은 파일에서 수정한 CSS를 이전 결과로 바꾸는 문제를 방지합니다. 설치된 Tailwind 로더와 버전은 그대로 사용합니다. CSS가 갱신되지 않으면 실행 경로와 제공 CSS를 먼저 확인하고, 서버 종료 후 `.next/dev`를 `tmp`로 백업 이동해 재시작합니다. 설정이나 실행기 파일 변경은 개발 서버를 재시작하고, 화면·CSS 변경은 HMR로 확인합니다. `npx next dev`로 실행기를 우회하면 API 응답 캐시 정책이 보장되지 않으므로 `npm run dev`를 사용하세요.

각 실행 터미널에서 Ctrl+C로 개발 서버와 FastAPI를 종료합니다. 정적 nginx 화면은 `npm run build`로 갱신합니다. 8080번 배포 절차는 기존 nginx 안내를 따르며 nginx의 개발 서버/HMR 중계는 추가하지 않습니다.

## 문서 관리

`/admin/documents`에서 문서 초안·개정·게시·사용 중단을 관리합니다. 채팅의 ‘문서로 등록’은 작성 중 질문을 복사한 편집기를 열며 대화 기록을 보존합니다. 등록 문서는 아직 실제 채팅 답변에 사용하지 않습니다. [계약과 제한](../docs/document-management.md)을 확인하세요.

이 기능은 로컬 시연용입니다. 개발 서버는 `npm run dev -- --hostname 127.0.0.1`로 실행하고 FastAPI도 loopback에 바인딩합니다. 정적 빌드에는 `out/admin/documents.html`이 포함되지만 실제 본문은 포함하지 않습니다. 문서 API는 `/api/documents`이며 정상·오류 응답은 no-store입니다. 미저장 내용은 새로고침 시 사라집니다.
