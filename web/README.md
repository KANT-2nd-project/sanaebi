# 사내비 프런트엔드

Next.js App Router·TypeScript·Tailwind CSS 4를 사용합니다. 서비스 소개(`/`)와 질문 화면(`/chat`)을 정적 HTML로 생성합니다. 질문 입력·예시 선택·공백 검증을 제공하며, 제출하면 같은 출처의 `/api/ask`에 질문을 전송하고 대기·답변·오류를 표시합니다. 현재 서버는 질문을 그대로 반환하는 echo 단계입니다. 프로젝트 nginx를 통해 FastAPI에 연결합니다. 중계가 없는 Next 개발 서버에서는 제출이 실패 안내로 표시됩니다.

## 개발

이 디렉터리(`web/`)에서 npm을 사용합니다. 최초 설치 또는 잠금 파일 기준 재설치가 필요할 때 실행합니다.

```bash
npm ci
npm run dev
```

http://localhost:3000 에서 확인합니다. 화면과 정적 빌드는 FastAPI 없이 실행할 수 있지만 실제 질문 응답에는 `/api/ask` → FastAPI `/ask` 중계가 필요합니다. 폰트는 시스템 한국어 글꼴을 사용하며 Google 폰트를 다운로드하지 않습니다.

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

개발·시연 단계이므로 두 화면 모두 noindex를 유지합니다. noindex는 인증이나 접근 권한 검사를 대신하지 않습니다. 자세한 방향은 [프런트엔드 설계](../docs/frontend-architecture.md)를 참고하세요.

## 질문 요청과 테스트

입력 앞뒤 공백을 제거한 `{question}`만 POST로 전송합니다. 35초가 지나면 브라우저 요청을 중단하며 자동 재시도하지 않습니다. 처리 중에는 입력을 읽기 전용으로 두고 제출·예시 버튼을 비활성화합니다. 실패하면 입력을 수정하거나 질문하기를 눌러 수동 재시도할 수 있습니다. 브라우저 취소가 서버의 모델 실행 종료를 보장하지는 않습니다.

`npm test`는 기존 TypeScript 컴파일러로 API 경계 코드를 저장소의 `tmp/frontend-unit-tests/`에 컴파일한 뒤 Node 내장 테스트 러너를 실행합니다. 별도 패키지를 추가하지 않으며 Node 22 이상을 사용합니다. 테스트는 fetch를 대체하여 오류·timeout·취소 계약을 검증하므로 실제 nginx/FastAPI 통합 성공을 의미하지 않습니다.
