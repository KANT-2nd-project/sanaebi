# 핵심 코드 정리 구현·인수인계

2026-10-15 사용자가 tmp/cleanup-audit-20261015의 핵심 정리(S0·S1·S2·S3·해당 S7)를 구현하도록 요청했다. 후속 요청에 따라 완료/부분 완료/미착수/범위 제외를 표시한다. 최초 조사 원자료는 유지하며 이 일지는 게시 가능한 실행 근거와 남은 작업의 기준이다. project-doc-sync를 적용했다.

## 변경

main 21af689에서 별도 worktree /tmp/sanaebi-core-cleanup-20261015와 refactor/core-cleanup-20261015를 만들었다. 사용자 classifier 브랜치의 프런트 수정과 routing-shadow의 서비스 변경 파일을 보존했다.

- 구형 extract_answer_text와 전용 테스트3개를 제거했다. LLMResponseError·LLM_RESPONSE_ERROR·HTTP 오류 처리는 유지했다.
- build_profile_prompt의 profile을 필수화했다. 생략은 TypeError, 미등록 이름은 기존 ValueError다. baseline 테스트는 baseline을 명시한다. CLI·서버·평가의 v3 기본값과 execute_strategy의 과거 baseline 기본값은 그대로다.
- 루트 sanaebi_assistant.py와 answer_pipeline을 archive/answering_v1로 옮겼다. 새 명령은 `python -m archive.answering_v1.assistant`, `python -m archive.answering_v1.answer_pipeline.cli`다. 옛 import/명령 wrapper는 제공하지 않는다. 기존 sanaebi·sanaebi-train과 설치 의존성은 유지한다.
- assistant 결과는 계속 저장소 루트 result.json, 평가기 기본 자료는 data/archive/company-knowledge-v0를 사용한다. 상대 fixture·patch 경로와 실행 결과 ignore 경로를 갱신했다.
- 현재 HTTP 테스트를 유지하고 과거 체인2개를 test_legacy_answering으로 분리했다. 현재 회사 문서 검사는 원본71행에 테스트용 개정1을 붙인 임시 snapshot을 현행 loader로 검증한다. 원본 corpus를 수정하지 않고 legacy loader의71행 호환 검사는 별도로 보존했다.

프로필9개의 system/user 메시지 hash가 변경 전과 같다. 과거 날짜별 실험·보고서·manifest·데이터·모델/프리셋·의존성 파일도 변경하지 않았다. 재현은 해당 고정 커밋에서 수행하며 이전 결과를 새 파일 hash로 바꾸지 않는다. 모델 호출·학습·실제 DB 접근·공개 배포·재시작은 하지 않았다.

## 단계별 상태

| 단계 | 상태 | 완료 내용·남은 작업 |
|---|---|---|
| S0 기준선·보호 | 완료 | main21af689·별도 worktree·사용자 파일 hash·테스트 ID·프로필 hash 확보 |
| S1 미사용 함수 | 완료 | 함수·전용3개 삭제, 운영 오류 계약 유지 |
| S2 프로필 계약 | 완료 | 필수 인자·baseline 명시·오류와 v3 일치 검사 |
| S3 legacy 분리 | 완료 | 새 패키지·CLI·경로 보존·현재/과거 테스트 분리 |
| S4 실험 경계 | 미착수 | evidence_first 이동·새 실험 공통화·registry 분리는 다음 작업 |
| S5 의존성·CLI·패키징 | 미착수 | Ollama 선택 설치·직접 의존성·설치 배포 범위 정리는 다음 작업. 이번 legacy 명령 이동과 구분 |
| S6 테스트·큰 파일 | 미착수 | 전체 테스트 재배치·평가기/repository 분할은 하지 않음. S3의 필요한 테스트 분리만 완료 |
| S7 문서·검증·게시 | 이번 범위 완료 | 전용 브랜치·main 게시, Notion3곳 저장·재조회 완료. 후속 단계 구현 때 해당 범위의 S7 재수행 |
| S8 용량 정리 | 범위 제외 | tmp·가중치·DB·캐시 삭제 없음 |

후보 단위로 C01·C02·C03은 완료, C04는 프로필 선택 설명만 완료하고 registry 구조 분리는 미착수다. C08은 혼합 테스트/현재 loader 분리만 완료하고 전체 배치는 미착수다. C13은 이번 핵심 변경 안내만 반영하며 전체 문서 재구성은 미착수다. C15 사용자 변경 보호는 확인했다. C05·C06·C07·C09·C10·C11·C12는 후속 작업이며 C14는 별도 용량 요청 전 보류한다.

## 검증과 기여

변경 전 전체586개 통과(48.771초). 삭제 후 오류·생성 관련22개, 프로필30개, 이동 후 CLI help·모의 run/judge/report·trace·현재 HTTP 포함124개를 통과했다. 테스트 ID 기준 제거3개·이동2개·추가5개이며 예상하지 않은 누락은0이다. 새 수집 수는588개다. 자세한 최종 검사는 아래에 기록한다.

사용자가 범위·게시·완료 표시를 요청했고 AI가 구현·실행·비블라인드 검토·문서화를 담당했다. 코드 구조 정리이며 모델 품질 향상이나 독립 사람 승인을 주장하지 않는다. 최초 조사 tmp 자료와 새 실행 tmp/core-cleanup-20261015는 커밋하지 않는다.

### 최종 로컬 검증

전체588개 통과(50.381초), Ruff 검사·형식319파일, 변경 문서 로컬 링크124개·앵커6개와 역참조 점검을 통과했다. 형식 검사에서 길어진 테스트 호출 줄2개를 정리한 뒤 재확인했다. CLI help는 별도 프로세스에서 인증 입력·모델 호출 없이 종료하며 assistant.main의 결과 저장은 임시 경로·모의 호출로 검증했다. 현재 HTTP 경로의 보관 모듈 비의존도 별도 프로세스에서 검증한다.

[테스트 이동·추가·삭제 대응과 프로필 hash](evidence/2026-10-15-core-cleanup.json)를 보존한다. 사용자 원래 작업 공간의 추적/미추적 대상 파일 hash와 Git 상태가 시작과 동일함을 확인했다. 이 근거에는 인증정보·실제 문서 원문·모델 가중치를 포함하지 않았다.

## 게시·외부 저장·완료 체크 확인

f4569ef·8f889ce·9c2fbcd·4255686을 전용 브랜치에 게시했다. main21af689 이후 원격 변경이 없음을 확인하고005241195de010828deaad9d73f58ddffb8b9856으로 병합·푸시해 원격 일치를 확인했다. 통합 후26개 검사를 통과했다.

Notion [프로젝트 문서 안내](https://www.notion.so/3f805a3cdadc81e1a70bfe82c89cebe7), [서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b), [생성 개인 일지](https://www.notion.so/3f905a3cdadc8146a9bbedb690ab5ecf)에 핵심 변경·현재 완료 범위·미착수 단계를 추가했다. 쓰기 직전 재조회하고 기존 기록·속성을 보존했다. 저장 후 구역 전체·Git 링크3개씩을 확인했고 파일명의 자동 외부 링크를 코드 표기로 교정한 뒤 재확인했다. 현재 상태 링크는 main의 이 일지를 가리키며 코드·검증 근거는 고정 커밋을 가리킨다.

사용자의 완료 표시 요청에 따라 원래 tmp/cleanup-audit-20261015의 README·구현계획·상세조사에 최신 상태 링크를 추가하고 구현계획에 단계별 체크박스를 넣었다. implementation-status.md/json에 단계·후보별 완료/부분/미착수/범위 제외를 기록했다. 원조사 evidence·inventory·candidates·validation-result는 덮어쓰지 않았다. 최초 검증기는 구현 전 snapshot 기준이므로 이후 코드에 그대로 적용해 현재 구현 검증으로 주장하지 않는다.

이번 요청 범위는 완료했다. 남은 S4–S6 및 부분 후보의 다음 작업은 최신 main을 기준으로 새 기준선을 잡는다. S8 데이터·모델·캐시 정리는 여전히 제외다.
