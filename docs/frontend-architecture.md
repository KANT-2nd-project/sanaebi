# 프런트엔드 설계

- 기준일: 2026-10-14
- 현재 구성: Next.js 정적 소개 + FastAPI에 마운트한 Gradio 대화 화면 + nginx.
- 답변 범위: 기존 echo 함수. 실제 모델·이전 대화 문맥 처리·인증·외부 공개는 후속 단계다.
- 실행: [프런트 안내](../web/README.md), [nginx 안내](../deployment/README.md).
- 서비스 정책: [서비스 아키텍처](service-architecture.md). 서버 책임: [서버 구성 규약](server-conventions.md).

## 화면과 실행 경로

| 경로 | 개발 | 로컬 배포 |
|---|---|---|
| `/` | Next 3000 | nginx 8080 → `web/out/index.html` |
| `/chat` | 308 `/chat/` | 308 `/chat/` |
| `/chat/` 및 하위 요청 | 개발 실행기 → FastAPI 8000 | nginx → FastAPI 8000 |
| `/api/*` | 기존 Next rewrite → 접두사 제거 | nginx → 접두사 제거 |

소개 페이지는 정적 HTML이고 채팅은 Python 런타임이 필요하다. 별도 Gradio 7860 서버와 운영용 Next 서버, 채팅용 Node SSR은 실행하지 않는다. FastAPI의 `/`는 서버 확인 API이며 사이트 홈과 구분한다. 화면 사이 이동은 일반 링크를 사용해 Next RSC prefetch와 Gradio HTML을 섞지 않는다.

Gradio Blocks + Chatbot + Textbox + State로 구성한다. ChatInterface는 제출 직후 입력을 비우므로, 입력 보존·실패 턴 갱신·취소를 명시적으로 제어하는 Blocks 이벤트를 사용한다. 기존 React 채팅과 브라우저 fetch 클라이언트는 제거했다. Gradio 내부 private 메서드는 수정하지 않는다.

## 책임과 답변 경계

- `app/ui/gradio_chat.py`: 화면·Gradio 이벤트·실행 동시성 조립.
- `app/ui/chat_state.py`: 세션별 턴·draft·busy·generation·요청 ID와 상태 전이.
- `app/ui/question_adapter.py`: QuestionRequest 검증 → 기존 generate_answer → extract_answer_text.
- `app/ui/gradio_chat.js`·CSS: 키보드, 포커스, 입력 높이, 35초 UI 마감, 스크롤·최소 스타일.
- `app/ui/headers.py`: 스트림을 버퍼링하지 않는 no-store·noindex 헤더.

Gradio 브라우저 요청은 `/chat/gradio_api/...` 이벤트 경로를 사용한다. `/api/ask`를 다시 호출하지 않으며, 기존 REST API와 echo 함수를 공유한다. Gradio 이벤트 오류와 REST의 422/502 상태·JSON은 별도 계약이다. 기존 `/ask`, `/assistant`, `/ask/langchain`, 분류·문서 API를 변경하지 않는다. UI 전환은 실제 LangChain·모델 연결의 완료를 의미하지 않는다.

## 대화와 입력 정책

현재 질문 하나만 답변 함수에 전달한다. 화면의 대화 목록을 모델 문맥으로 사용하지 않는다. 사용자 질문은 오른쪽, 답변은 왼쪽에 누적한다. 첫 화면에는 인사말·입력·예시 질문을 제공하고 전송 후에는 대화와 하단 입력을 유지한다.

- 데스크톱 Enter 전송·Shift+Enter 줄바꿈. 주 입력 장치가 hover:none AND pointer:coarse이면 Enter 줄바꿈·버튼 전송.
- IME 조합·키 반복·요청 중 중복 전송을 차단한다. 예시는 입력과 포커스만 바꾸며 자동 제출하지 않는다.
- 입력은 2행부터 최대 200px까지 증가한다. label·도움말·오류를 연결하고 바깥 입력 그룹에 포커스를 표시한다.
- 요청 중 입력을 readOnly로 보존하고 성공 시 비운다. 실패 시 수정 가능하게 보존한다.
- 같은 실패 질문을 다시 전송하면 기존 턴을 갱신한다. 수정한 질문은 새 턴이다. 실패 질문 선택·재시도는 원래 질문을 사용하며 다른 draft를 보존한다.
- 새 대화는 취소와 generation 무효화를 수행한다. 늦은 응답은 새 대화에 붙이지 않는다.
- 새 질문을 보이게 이동한다. 최신 위치에서 80px 이내일 때만 응답을 따라가고 긴 답변은 시작 부분을 보여준다. 위쪽을 읽으면 위치를 유지하며 최신 메시지 이동을 제공한다.
- 시스템 한국어 글꼴·밝은 테마·긴 URL 줄바꿈·모바일 안전 영역·reduced-motion을 지원한다.

## 임시 기록·실행 제한

브라우저별 Gradio State에 기록을 분리한다. localStorage·대화 DB·flagging 파일에 질문을 저장하지 않는다. 새로고침·새 대화·서버 재시작 시 초기화하며 서버 세션은 30분 유휴 만료 대상이다. 활성 화면은 분 단위 만료 검사도 수행한다. 서버 재시작 뒤 이전 화면의 대화가 복구된다고 보장하지 않는다.

세션별 요청은 하나만 진행한다. 서버의 답변 함수 동시 실행은 1, Gradio 대기열 상한은 16이다. 취소된 동기 작업이 계속 실행되는 경우 실제 작업이 끝날 때까지 실행 슬롯을 유지한다. 취소가 모델 실행 자체를 종료한다는 뜻은 아니다.

브라우저는 제출부터 큐 대기·실행을 포함해 35초 뒤 입력 복원·오류 안내·취소를 수행한다. 서버도 수락 시점부터 35초 실행 예산을 적용한다. 자동 재시도는 하지 않는다. 네트워크가 끊기면 서버 취소 통지가 전달되지 않을 수 있으며 재연결 후 수동 재시도가 필요하다.

`/chat/` 프록시는 연결 5초·읽기 유휴 60초이며 SSE 버퍼링을 하지 않는다. SSE heartbeat 때문에 읽기 제한은 총 실행시간 제한이 아니므로 UI 마감과 구분한다. 기존 `/api/` 읽기 제한은 30초로 유지한다.

## 개발·캐시·정적 산출물

개발 실행기가 Next handler 전에 `/chat/`을 처리해 prefix를 유지한 채 Node http 스트림으로 전달한다. `/api/`는 기존 Next rewrite와 no-store 래퍼를 사용한다. Next HMR과 Tailwind 입력 해시 캐시 수정·개발 파일시스템 캐시 비활성화는 유지한다.

정적 export에는 소개·404·Next 자산만 생성한다. 이전 `chat.html`·chat 라우트 데이터는 배포하지 않는다. HTML은 no-cache, 해시 Next 자산은 1년 immutable, Gradio와 API의 정상·오류 응답은 no-store다. nginx는 없는 정적 페이지를 홈으로 대체하지 않는다.

## SEO와 공개 경계

로컬 소개와 채팅은 noindex다. 소개의 한국어 제목·본문·링크·메타데이터는 초기 HTML에 제공한다. Gradio 채팅에는 robots 메타와 X-Robots-Tag를 적용한다. noindex는 인증을 대신하지 않는다.

외부 공개 단계에서 공개 가능한 소개·`/guide` 콘텐츠, 페이지별 title/description/canonical/OG, 실제 도메인의 sitemap과 robots를 추가하고 공개 소개의 noindex만 해제한다. 채팅·사내 질문·문서·개인 기록은 검색용 콘텐츠에 넣지 않는다. 정적 HTML이나 Next 사용 자체가 검색 순위를 보장하지 않는다.

## 검증 기준

Python 상태·마운트·컨트롤러 테스트, 기존 REST 회귀 검사, Node 중계·캐시·설정 테스트와 프런트 lint/typecheck/build를 실행한다. 실제 3000·8080 echo, 오류·복구·수동 재시도, timeout·취소·세션 격리, 키보드·반응형·스크롤은 브라우저에서 검증한다. 테스트용 지연·오류·긴 응답은 제품에 넣지 않는다.

한국어 실제 IME와 실기기 가상 키보드는 별도 확인 대상이다. 이벤트 주입과 터치 에뮬레이션만으로 실제 기기 검증 완료라고 기록하지 않는다. 세션별 결과와 미검증 사항은 구현 작업 기록에서 관리한다.
