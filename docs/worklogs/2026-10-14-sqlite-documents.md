# SQLite 문서 통합·실제 이관

- 수행일: 2026-10-14, 한국 시간.
- 시작 기준: `eafaf6ebd7a80c2cd7670985c614143cb1d293dd`.
- 사용자 결정: JSONL·관리 DB 분리를 해소하고 기존 71건을 출처·AI 검수 상태 그대로 게시. 모델 교체·RAG·인증·분류 학습은 제외.
- AI 수행: schema v2·이관/export 도구·공통 snapshot·API/화면·회귀 검사·실제 이관·문서 동기화·게시. 사용자 직접 구현이나 사람 검수 승인으로 기록하지 않는다.

## 구현

기존 UUID·개정·이벤트·멱등성 저장 구조를 유지하고 원본 이관 추적과 개정 메타데이터를 별도 테이블로 추가했다. deterministic UUID5, dry-run, 백업, 전체 트랜잭션, 원본 변조 충돌, 반복 실행 시 사용자 수정·중단 보존을 적용했다. 게시 snapshot은 평가용 JSONL과 검증 manifest로 내보낸다.

관리 API·/ask·/assistant·디버그·독립 실행기가 공통 SQLite 경로를 사용한다. 검색 질문마다 snapshot을 한 번 읽고 모델 호출 전에 트랜잭션을 닫으며 두 provider도 동일 입력을 사용한다. 기본 JSONL 병합·fallback은 없다. 빈 게시 목록은 모델 미호출, DB 오류는 503, /ask 모델 오류는 502다. /assistant의 model_called는 실제 LLM callback으로 기록한다.

/regist-docs는 기존 입력·성공 응답을 유지해 SQLite 초안을 생성한다. 50,000자·512KiB 제한과 중복 409를 추가했다. 상세 UI에 원본·검수 메타데이터를 표시하고 capabilities를 connected로 바꿨다. 실제 runner의 answer 필드를 /ask 응답으로 변환하도록 연결도 바로잡았다.

## 실제 데이터 전환

3000·8000 서버가 없는 상태에서 dry-run 후 적용했다. 적용 직전 DB는 schema2·문서0건이었다. 개발 검증 과정의 초기화가 schema를 먼저 올렸으며 실제 v1 데이터 보존은 임시 DB에서 별도 확인했다.

- 원본: `data/company-knowledge/documents.jsonl`, SHA256 `84b44e6592e3a6bd883b7890239aada11382cbef9a369ebb0aca3b15defddfe4`.
- DB: `var/documents.sqlite3`, 신규71·게시71·충돌0.
- 백업: `var/backups/knowledge-a6c1c904387448808fc7bfcbda57d094/`의 원본·SQLite backup·manifest.
- 원본 ID·제목·본문·버전·분류·출처·정책 결정·검수 상태·순서 전수 일치. 정규화 문맥 101,994자이며 원본 JSONL과 완전히 동일.
- snapshot fingerprint: `7c259e655ed58b47e7af2fcc7ba312fc5febe316b2e716051c91dbda99b76940`.
- 실제 DB·백업·임시 증거·기존 집필 자료는 Git 제외 상태로 보존했다. 새 clone에는 명시적 이관이 필요하다.

## 검증

- Python 전체 299개 실행 성공, 기존 opt-in 실모델 검사1개 제외. 동시에 작성 중인 generation 테스트도 당시 실행에 포함됐지만 이번 게시 범위에서는 제외했다.
- 임시 DB: schema migration 반복·v1 보존·미래 schema 거부·원본 변조·중복·rollback·backup 복원·export 재현성·사용자 문서 충돌을 검증했다.
- 71건 전수 비교, 반복 이관71건 skip, 원본/export 프롬프트 일치를 별도 확인했다.
- 가짜 분류기·LLM: 초안→게시→질문→수정→재게시→중단, 두 provider 동일 snapshot, 비검색 DB 미조회, 빈 목록·DB 장애·legacy·멱등성·409·캐시 회귀 검사를 수행했다.
- 브라우저: 실제71건 목록, 4페이지 구성과 다음 페이지, 제목 검색(연차1건), 상세 원본 ieum-001·버전2.0.0·AI 검수·출처 H01/K01 표시. 실제 DB의 원문 수정 없이 확인했다.
- Next `/api/documents` 중계 HTTP200·Cache-Control: no-store와 connected 응답을 확인했다.
- 웹 lint·타입 검사·정적 빌드 성공. 웹 테스트51개도 통과했다.
- Ruff check·format 검사 성공. 검사 중 다른 작업의 generation/prompts.py에 일시적 F841이 있었으며 그 파일을 수정하지 않았다. 후속 전체 검사에서는 해소됐다.

## 실모델 검사와 제한

실제 `/ask` 요청은 분류 모델 파일 부재로 HTTP503(약0.002초)이다. 모델 학습·경로 교체는 하지 않았다.

준비된 로컬 `qwen3:4b-instruct-2507-q4_K_M`에 같은 SQLite 전체 snapshot과 “연차는 어떻게 신청하나요?” 질문을 독립 실행기로 전달했다. model_called=true, 약34.81초 후 입력66,652토큰이 설정40,960을 초과하여 Ollama400으로 실패했다. 본문 절단·자동 다운로드·유료 OpenAI 호출·모델 파라미터 변경은 없었다. 현재 실제 답변 생성 성공·품질은 검증하지 못했다. 모델 준비·전체 문맥 처리 방식은 후속 결정이 필요하다. Windows 실행·인증·운영 배포도 검증 범위 밖이다.

로컬 증거는 `tmp/sqlite-document-plan/evidence/`의 actual-import.json, check-71.json, python-final.log, web-*.log, browser-*.txt, actual-ask.json, ollama-smoke.json에 보관한다. 미추적 generation/와 관련 테스트는 다른 작업으로 보존한다.

## 게시·외부 문서 확인

구현은 [163feae](https://github.com/KANT-2nd-project/sanaebi/commit/163feae3aec4aa4b2d7481e60fa11313a28e4a76)로 main에 푸시했고 원격 커밋 일치를 확인했다.

다음 Notion 대상은 영향받는 현재 안내를 갱신하고 구현 링크·71건 이관·검사 결과·분류 모델 부재·문맥 한도 초과를 재조회했다. 과거 제작·검증 기록은 유지했다.

- [프로젝트 문서 안내](https://www.notion.so/3f805a3cdadc81e1a70bfe82c89cebe7)
- [서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b)
- [운영·개발 규칙](https://www.notion.so/3f805a3cdadc81aa9f48d8445d372b80)
- [데이터 작성·검수·실험 절차](https://www.notion.so/3f805a3cdadc81d59dc9fec6e4fcca1d)
- [최재선 개인 일지](https://www.notion.so/3f905a3cdadc81e4b662eb4ba4a8a56c): 중복 검색 후 생성, 총괄·통합·수행일·사용자 결정과 AI 수행·제한·커밋 링크를 재확인했다.

데이터 절차 페이지의 첫 수정은 mention을 포함한 일치 검색 오류로 실패했다. 재조회해 미저장을 확인하고 해당 부분을 짧은 일반 텍스트로 바꿔 재시도한 후 전체 반영을 확인했다.

최종 검증 시점 이후 동시에 추가된 README·classification/README·data/README·docs/documentation-guide의 분류 보고서 안내, classification/reports/, generation/와 관련 테스트는 다른 작업으로 보존했다. 이번 기록 커밋에도 포함하지 않는다. 개발 서버는 127.0.0.1:3000·8000에서 실제 이관 DB를 연결한 상태로 유지했다.
