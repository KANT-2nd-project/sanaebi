# Sanaebi

사내비는 회사 규정과 업무 절차에 관한 질문을 회사 문서에 근거해 안내하는 LinkUp 팀의 사내 지식 질의응답 프로젝트입니다. 구성원의 반복 문의를 줄이고 필요한 업무 정보를 쉽게 찾도록 돕는 것을 목표로 합니다.

## 개발 목표

- 질문의 뜻에 따라 문서 안내, 추가 질문, 지원 범위 안내로 연결합니다.
- 공통 회사 문서를 근거로 답변하고, 자료가 부족하거나 서로 충돌하면 그 한계를 알립니다.

## 빠른 시작

Python 3.12.14·uv와 Node.js 22 이상·npm을 사용합니다. 저장소 루트에서 최초 설치합니다.

```bash
uv sync --locked
npm ci
npm --prefix web ci
```

새 환경에서 기존 회사 지식 71건을 사용하려면 [문서 이관 안내](docs/document-management.md#회사-지식-이관내보내기)의 dry-run 후 `--apply --publish-imported`를 실행합니다. 이후 문서는 관리 화면에서 편집·게시하며 재시작 시 자동 이관하지 않습니다. 선정한 로컬 분류 모델 연결은 검증했으며 실제 생성 모델의 입력 한도·문서 준비는 별도 확인이 필요합니다. 과거 전환 당시 상태는 [전환 기록](docs/worklogs/2026-10-14-sqlite-documents.md)을 참고하세요.

이후 다음 명령 하나로 API와 웹 개발 서버를 함께 실행합니다.

```bash
npm run dev
```

웹은 http://127.0.0.1:3000/chat, API는 http://127.0.0.1:8000, API 문서는 http://127.0.0.1:8000/docs 입니다. Ctrl+C로 둘 다 종료하며 한쪽이 종료되면 다른 쪽도 종료합니다. 실제 답변에는 아래의 분류 모델과 Ollama 또는 OpenAI 준비가 별도로 필요합니다. 이 명령은 모델을 학습하거나 Ollama를 시작하지 않습니다.

API만 실행하려면 `npm run dev:api`, 웹만 실행하려면 `npm run dev:web`을 사용합니다. 상세 실행·문제 해결은 [웹 개발 안내](web/README.md#개발), 정적 빌드·nginx 시연은 [배포 안내](deployment/README.md)를 따릅니다.

## 요청 예시

```bash
curl http://127.0.0.1:8000/
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"휴가 신청 방법 알려줘"}'
```

현재 응답 예시는 다음과 같습니다.

```text
GET /       -> {"message":"FastAPI 서버가 실행 중입니다."}
POST /ask   -> {"ok":true,"text":"생성된 답변","reason":""}
```

`/ask`는 질문 서비스의 분류 정책에 따라 안내하거나 답변을 생성합니다.
`SANAEBI_ANSWER_PROVIDER=ollama` 또는 `openai`로 답변 모델을 선택합니다. 입력은 question 하나이며 선택한 모델의 답변을 ok·text·reason으로 반환합니다.
Ollama 선택 시 해당 서버와 모델이 필요하고, OpenAI 선택 시 `OPENAI_API_KEY`가 필요하며
API 호출 비용이 발생합니다. 답변 생성 실패는 HTTP 502와 오류 안내로 반환합니다.

질문 분류는 `POST /classify/koelectra-base`에 `{"question":"출장비 정산 절차 알려줘"}`를 전달해 확인합니다. `/ask`는 같은 분류기를 사용하며 CLARIFY·UNSUPPORTED에는 고정 안내를 반환합니다. SEARCH_KNOWLEDGE만 유효 게시 문서를 읽고, 문서가 있을 때 답변을 생성합니다.

서버는 선정한 KoELECTRA base의 새 저장본을 사용합니다. 기본 경로는 `artifacts/experiments/learning-comparison-2026-10-15/koelectra_base/model/`이며 가중치는 Git에 포함되지 않습니다. 다른 환경에서는 가중치·config·토크나이저·metadata.json을 함께 준비하고 경로를 지정하세요.

```bash
SANAEBI_CLASSIFIER_PATH=/absolute/path/to/model uv run --locked uvicorn app.fastapi_main:app --reload
```

상대 경로는 저장소 루트 기준입니다. 첫 분류 요청에서 CPU로 로딩하고 재사용하므로 모델 변경 후 서버를 재시작합니다. 최대 길이와 라벨은 저장본에서 읽으며 파일 부재·잘못된 저장본·추론 실패는 503과 `분류 모델을 사용할 수 없습니다.`를 반환합니다. 자동 다운로드·학습은 하지 않습니다.

`SANAEBI_ANSWER_PROVIDER=ollama`(기본) 또는 `openai`로 답변 제공자를 선택합니다. 상세 책임·설정·오류 계약은 [서버 규약](docs/server-conventions.md), 선정 근거는 [7종 보고서](classification/reports/2026-10-15-seven-model-comparison/README.md)를 따릅니다. [새 학습 명령](classification/README.md)과 [아카이브 CLI](archive/classification_v1/README.md)는 저장 형식이 다르며 아카이브 모델을 새 서버 경로에 그대로 지정하지 않습니다.

## 프로젝트 문서

- [새 생성 모듈 안내](generation/README.md): 기본 계약·프롬프트·파싱 구현, 실제 모델·API·평가기 연결 전 단계
- [이음웍스 회사 정책 데이터](data/README.md#답변용-회사-지식)
- [서비스 아키텍처](docs/service-architecture.md): 현재 API 동작과 목표 질문 처리 흐름
- [프런트엔드 설계](docs/frontend-architecture.md): Next.js 정적 내보내기·대화형 UI·개발 API 중계·SEO 기준. 기존 로컬 echo 연결을 검증했으며 새 실제 모델 답변의 브라우저 종단 검증·외부 배포는 후속 범위
- [서버 구성 규약](docs/server-conventions.md): 현재 모듈 구성, 책임 분리와 API 회귀 검증 기준
- [요청 처리 분류·라벨링 기준 v1.0](docs/label-taxonomy.md): 질문 처리 라벨의 정의와 경계 사례
- [분류 학습 코드](classification/README.md): CSV·그룹 분할·TF-IDF·Transformer 학습·명시적 평가; 직접 작성과 AI 위임 범위 구분
- [기존 분류 실험 코드 안내](archive/classification_v1/README.md): 코드 읽는 순서, 공통 학습·평가 구조와 실행 방법
- [분류 실험 보고서](classification/reports/README.md): 새 코드의 7종 비교·오분류·선정 판단과 실행 근거. [과거 보고서](archive/classification_v1/reports/README.md)는 당시 조건으로 보존
- [요청 처리 데이터 안내](data/README.md): 데이터 구조, 작성·검수 기록, 분할과 검증 범위
- [문서 주제 분류 아카이브 v0.2](data/archive/document-topics-v0.2/README.md): 이전 문서 분류 실험 데이터
- [질문 주제 분류 아카이브](data/archive/question-topics/README.md): 이전 질문 분류 실험 데이터
- [문서 관리 가이드](docs/documentation-guide.md): 문서별 기준 위치와 Notion 갱신 절차
- [팀 문서](https://www.notion.so/2bb05a3cdadc82bb813381e3fab45047): 결정·작업·회의 기록

## 개발 확인

저장소의 주요 형식·데이터·테스트 확인 명령은 다음과 같습니다.

```bash
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/validate_dataset.py
uv run --locked python -m unittest discover -s tests -v
```

데이터 검증 명령은 현재 요청 처리 데이터와 검수 기록을 확인합니다. 모델 성능이나 실제 서비스의 답변 품질을 측정하지는 않습니다.

문서 등록·관리는 `/admin/documents`에서 로컬 가상 자료로 시연합니다. 저장·게시·사용 중단을 지원하며 현재 유효한 SQLite 게시본을 LangChain 답변에 전달합니다. [문서 관리 안내](docs/document-management.md)를 참고하세요.
