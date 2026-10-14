# 사내비 프런트엔드

Next.js·TypeScript·Tailwind는 정적 소개(`/`)를 제공하고, 질문(`/chat/`)은 FastAPI에 마운트한 Gradio가 제공합니다. 현재 답변은 질문을 그대로 돌려주는 echo이며 실제 모델·이전 대화 문맥 처리는 연결하지 않았습니다. 상세 정책은 [프런트 설계](../docs/frontend-architecture.md)를 따릅니다.

## 개발 실행

저장소 루트에서 의존성을 설치합니다. Python 3.12와 Node 22 이상을 사용합니다.

```bash
uv sync --locked
npm ci --prefix web
```

터미널 하나에서 FastAPI와 Gradio를 시작합니다.

```bash
uv run --locked uvicorn app.fastapi_main:app --host 127.0.0.1 --port 8000
```

다른 터미널에서 소개 페이지 개발 서버를 시작합니다.

```bash
cd web
npm run dev -- --hostname 127.0.0.1 --port 3000
```

http://localhost:3000 에서 소개를, http://localhost:3000/chat/ 에서 채팅을 확인합니다. 개발 실행기는 `/chat/` 요청을 경로 그대로 FastAPI로 스트리밍 중계합니다. 기존 `/api/ask`는 Next rewrite를 통해 FastAPI `/ask`로 전달됩니다. `npx next dev`로 실행기를 우회하지 않습니다.

Gradio는 별도 7860 서버를 사용하지 않습니다. Python·Gradio CSS/JS 변경은 FastAPI를 재시작하고 브라우저를 새로고침합니다. Next 소개 화면은 HMR로 갱신하며 Next 설정·개발 실행기 변경은 개발 서버를 재시작합니다. 각 터미널에서 Ctrl+C로 종료합니다.

## 검증·빌드

`web`에서 실행합니다.

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

`out/`은 소개·404·정적 자산의 배포 산출물입니다. Gradio 채팅 HTML은 포함하지 않습니다. 소개 빌드는 FastAPI 없이 가능하지만 채팅에는 FastAPI가 필요합니다. 정적 배포는 [nginx 실행 안내](../deployment/README.md)의 8080번 경로를 사용합니다.

저장소 루트의 서버 검사는 다음과 같습니다.

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
```

## 입력·기록·오류

- 데스크톱 Enter 전송·Shift+Enter 줄바꿈, 모바일 터치 환경 Enter 줄바꿈·버튼 전송입니다. 예시는 입력만 바꿉니다.
- 진행 중 입력을 보존하고 성공하면 비웁니다. 실패하면 수정하거나 실패한 질문을 선택해 재시도할 수 있습니다. 자동 재시도는 없습니다.
- 제출부터 큐 대기·실행을 포함해 35초가 지나면 안내와 입력 복원을 수행합니다. `/chat/` 중계의 읽기 유휴 제한은 60초, 기존 `/api/`는 30초입니다.
- 기록은 브라우저별 서버 임시 세션이며 새로고침·새 대화·서버 재시작 시 초기화됩니다. 서버 세션은 30분 유휴 만료 대상입니다. localStorage·대화 DB에 저장하지 않습니다.
- 실제 신청·승인·개인 기록 조회는 지원하지 않습니다. 현재 소개와 채팅은 noindex이며 공개 운영용 인증은 후속 범위입니다.

## 장애 확인

`/chat/`의 502는 FastAPI 실행 상태를 확인합니다. 실행 중 통신이 끊기면 최대 35초 후 입력을 복원하며 서버 복구 후 수동으로 재시도합니다. 처음 페이지부터 열리지 않으면 서버 복구 뒤 새로고침합니다. 서버 재시작으로 이전 대화가 복구되지는 않습니다.

CSS 문제는 현재 실행 경로와 제공 CSS를 먼저 확인합니다. Tailwind 입력 해시 로더·개발 디스크 캐시 비활성화는 유지합니다. 필요 시 개발 서버를 종료하고 `.next/dev`를 `tmp`에 백업 이동한 뒤 재시작합니다. 실행 중 캐시를 지우지 않습니다. 폰트는 시스템 글꼴을 사용합니다.
