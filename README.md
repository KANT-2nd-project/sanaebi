# Sanaebi

사내비는 회사 규정과 업무 절차에 관한 질문을 회사 문서에 근거해 안내하는 LinkUp 팀의 사내 지식 질의응답 프로젝트입니다. 구성원의 반복 문의를 줄이고 필요한 업무 정보를 쉽게 찾도록 돕는 것을 목표로 합니다.

## 개발 목표

- 질문의 뜻에 따라 문서 안내, 추가 질문, 지원 범위 안내로 연결합니다.
- 공통 회사 문서를 근거로 답변하고, 자료가 부족하거나 서로 충돌하면 그 한계를 알립니다.

## 빠른 시작

Python 3.12.14와 uv를 사용합니다. 저장소 루트에서 의존성을 설치하고 개발 서버를 실행합니다.

```bash
uv sync --locked
uv run --locked fastapi dev app/fastapi_main.py
```

서버 주소는 http://127.0.0.1:8000이며, 인터랙티브 API 문서는 http://127.0.0.1:8000/docs 에서 확인할 수 있습니다.

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
POST /ask   -> {"ok":true,"text":"휴가 신청 방법 알려줘","reason":""}
```

현재 `/ask`는 앞뒤 공백을 제거한 질문을 반환하는 echo 단계입니다.

질문 분류는 `POST /classify/koelectra-base`에 `{"question":"출장비 정산 절차 알려줘"}`를
전달하면 `{"category":"SEARCH_KNOWLEDGE"}` 형태로 반환합니다. 저장된 KoELECTRA Base
모델과 토크나이저, `training_summary.json`의 최대 토큰 수를 사용하며 재학습하지 않습니다.
첫 요청에서 모델을 로드해 재사용하고, 가중치 파일이 없으면 HTTP 503과
`분류 모델이 없습니다.` 안내를 반환합니다. 모델 생성 명령은
`uv run --locked sanaebi train koelectra_base`입니다. 모델은 `artifacts/models/`, 별도 `sanaebi eval 모델명`은 validation만 평가하고 `--split test`로 test를 명시합니다. 결과는 `artifacts/results/<모델명>/<분할>/`에 저장합니다. 동일 조건의 정상 모델은 재학습을 생략하며 서버의 기존 모델 경로에 자동 배치하지 않습니다. 실험 실행·저장 경로는 [분류 안내](classification/README.md)를 확인하세요.

질문만으로 분류와 답변 생성을 이어서 실행하려면 `POST /ask/langchain`에
`{"question":"출장비 정산 절차 알려줘"}`를 전달합니다. 분류된 카테고리와 질문을
`sanaebi_assistant.py`의 고정 입력 형식으로 넘기고, `ollama`·`openai`의 답변과
실행 기록을 그대로 반환합니다. Ollama 실행 환경과 `OPENAI_API_KEY`가 필요하며
OpenAI 호출 비용이 발생합니다. 모델별 실패는 반환된 `success`와 `error`에서 확인합니다.
이미 분류한 질문은 `POST /assistant`에 `response`와 `classification_label`을 전달합니다.

## 프로젝트 문서

- [이음웍스 회사 정책 데이터](data/README.md#답변용-회사-지식)
- [서비스 아키텍처](docs/service-architecture.md): 현재 API 동작과 목표 질문 처리 흐름
- [프런트엔드 설계](docs/frontend-architecture.md): Next.js 정적 내보내기·대화형 UI·개발 API 중계·SEO 기준. 로컬 echo 연결을 검증했으며 실제 모델·외부 배포는 후속 범위
- [서버 구성 규약](docs/server-conventions.md): 현재 모듈 구성, 책임 분리와 API 회귀 검증 기준
- [요청 처리 분류·라벨링 기준 v1.0](docs/label-taxonomy.md): 질문 처리 라벨의 정의와 경계 사례
- [분류 실험 코드 안내](classification/README.md): 코드 읽는 순서, 공통 학습·평가 구조와 실행 방법
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

문서 등록·관리는 `/admin/documents`에서 로컬 가상 자료로 시연합니다. 저장·게시·사용 중단을 지원하며 현재 echo 채팅에는 등록 문서를 사용하지 않습니다. [문서 관리 안내](docs/document-management.md)를 참고하세요.
