# S5·S6 남은 코드 정리 — 2026-10-15

## 결과와 단계 상태

S4 후속 요청으로 Ollama 선택 설치, 직접 의존성 명시, 평가 검증 분리, 테스트 배치를 구현했다. 설치 지원은 소스 checkout이며 독립 wheel 배포는 포함하지 않는다.

- [x] S5 선택 의존성·실행 계약 정리
- [x] S6 테스트 배치·평가 검증 책임 분리
- [x] S7 이번 변경의 문서·검증·main·Notion 게시 — 저장 후 재조회 완료
- [ ] S8 파일·캐시·모델 용량 정리 — 범위 제외

C06·C08·C09·C10·C11을 요청 범위로 완료했다. C09는 기존 CLI·checkout 지원 유지 결정이며 wheel 지원 완료가 아니다. C12 repository는 검토 후 유지: helper의 주 소비자가 같은 모듈이고 SQL·상태 조합과 가까워 분리 이득이 작다. C13은 현재 안내의 정합성을 갱신했으며 과거 보고서·일지·실험 경로는 해당 커밋의 기록으로 보존한다. C14는 제외한다.

## 구현과 보존 계약

`langchain-ollama`는 ollama extra이며 실제 provider 선택 시 공통 내부 로더가 import한다. 관련 패키지 자체의 부재에는 `uv sync --locked --extra ollama`를 안내하고 다른 import 오류는 그대로 전달한다. 기본 환경에는 torch·transformers와 기존 운영 의존성을 유지했고 openai·httpx·numpy를 직접 의존성으로 명시했다. lock의 패키지 버전은 모두 동일하다.

현재 provider와 평가기의 다른 Ollama 옵션, OpenAI 구조화 출력·오류·재시도·종료 lifecycle을 유지한다. `sanaebi`와 `sanaebi-train`의 보관 분류 CLI 연결·패키지 포함 범위는 변경하지 않았다. 실제 서비스 모델 설정·프롬프트9개·HTTP 계약·DB schema는 동일하다.

selection의 문항·rubric 입력 검증과 selection_report의 스키마·파생값 함수를 각각 독립 모듈로 옮겼다. 실행·예산·resume·기록 및 summarize 진입점·집계는 유지한다. 새 코드 파일은 manifest 해시에 포함한다. 과거 manifest를 수정하거나 코드가 다른 결과의 resume를 허용하지 않는다.

테스트는 runtime·generation·evaluation·classification·legacy로 나눴다. 운영 trace와 보관 체인, 프롬프트와 실험 전략의 혼합 검사를 분리하고 공통 준비물·루트 계산은 support로 모았다. discovery의 최상위는 `-t .`로 지정한다. fixtures 위치는 유지한다. [테스트 안내](../../tests/README.md)에 실제 명령을 기록했다.

## 검증과 한계

| 검사 | 확인 결과 |
|---|---|
| 기준선 | 593개 통과, 47.655초 |
| 재배치 후 전체 | 595개 통과, 49.425초 |
| 최종 전체 | 595개 통과, 62.846초 |
| 기본 환경 독립 discovery | runtime145·generation113·evaluation147개 통과 |
| 테스트 대응 | 기존593개 모두 대응, 누락0·중복0; 선택 provider 오류 검사2개 추가 |
| 함수·보고서 비교 | 이동 함수13개 AST 동일; 보고서20회 출력·예외 동일 |
| 기본 설치 | Ollama 미설치 상태에서 서버 import·OpenAI 모의 호출·미설치 오류 확인 |
| extra 설치 | Ollama import·보관 답변기 import·분류 CLI2개 help 확인 |
| 불변성 | 프로필9개·보존 실험/보고서/설정/repository140파일 동일, 패키지 버전 동일 |
| Ruff·lock | check·format338파일·uv lock --check 통과 |
| 문서 | 상대 링크239개·앵커17개·diff 공백 검사 통과 |

[기계 판독 근거와 테스트 ID 대응표](evidence/2026-10-15-remaining-cleanup.json)에 전후 대응·프로필 해시·환경별 결과를 기록했다. 원자료는 로컬 `tmp/remaining-cleanup-20261015`에 보존하고 커밋하지 않는다.

처음 /tmp에 설치한 두 임시 환경은 공간 부족으로 실패했다. 이번 실행이 만든 불완전한 환경만 제거하고 uv 캐시와 같은 파일시스템의 새 환경에 하드링크로 설치해 성공했다. 기존 .venv·캐시·모델·사용자 파일은 삭제하거나 변경하지 않았다.

빈 임시 SQLite와 모의 provider를 사용했다. 전체 회귀의 작은 합성 모델 fixture 학습은 포함하지만 실제 서비스 모델 학습·유료 LLM 호출·운영 DB 접근·공개 배포·서버 재시작은 하지 않았다. 모델 품질 향상이나 독립 사람 승인을 주장하지 않는다.

## 작업·기여·게시

최신 main94eca80에서 별도 worktree와 refactor/remaining-cleanup-20261015 브랜치를 생성했다. 사용자 프런트 변경의 해시와 Git 상태를 확인했다. 병행 배포 작업의 PyTorch aarch64 설정은 해당 브랜치에 보존했으며 이번 정리에 임의로 가져오지 않았다. 병합 직전 최신 main을 다시 대조한다.

사용자가 범위·설치 지원·완료 표시를 결정했고 AI가 구현·검증·문서화를 수행했다. 커밋은 Ollama 경계 ec72dd9, 의존성3fb1b0b, 검증 분리30e5737, 테스트 재배치77c0a81로 나눴다. 게시·외부 저장 확인은 완료 후 아래에 기록한다.

## 게시·Notion·완료 표시 확인

전용 브랜치 게시 후 최신 main94eca80과 재대조했고 main `0df58f67aa7c5bf3be573d4a30e382f1c8169ae3`에 병합·푸시해 원격 일치를 확인했다. 통합 후 기본 환경의 runtime145·generation113·evaluation147개 및 Ruff·lock 검사를 통과했다. 병행 배포 브랜치3e604d4의 aarch64 PyTorch 설정은 해당 브랜치에 그대로 보존했다.

Notion [프로젝트 문서 안내](https://www.notion.so/3f805a3cdadc81e1a70bfe82c89cebe7), [서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b), [기존 생성 일지](https://www.notion.so/3f905a3cdadc8146a9bbedb690ab5ecf)에 이번 완료 구역을 추가했다. 저장 직전 읽기·저장 후 핵심 내용과 Git 링크3개 재조회를 완료했다. 그 사이 추가된 routing-shadow 기록을 포함해 기존 본문·속성을 보존했다.

원래 tmp 조사 폴더의 구현 계획·상태표에 S5·S6·이번 S7 완료를 체크했다. 최초 조사 자료는 유지했고 C04·C12는 검토 후 유지, C14/S8은 제외로 구분했다. 이번 요청 범위의 미완료 항목은 없다.
