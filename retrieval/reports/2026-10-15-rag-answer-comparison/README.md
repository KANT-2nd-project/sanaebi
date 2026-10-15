# Full·RAG 실제 답변 비교와 문서 초기화 연동 — 2026-10-15

## 목적과 조건

동일 질문·게시 snapshot에서 전체 문서를 주는 full과 기존 Tiny 검색 근거만 주는 rag의 답변을 비교한다. 기존 검색 실패 문항을 포함한 답변 가능16·불가4를 [고정 문항](cases.json)과 [판정 기준](rubric.md)으로 독립 AI 검토 후 동결했다. 합성 사내 문서·AI 작성/검토 자료이며 사람 검수나 운영 품질 승인이 아니다.

기준 코드 `da5e01e`, 문서71개, 원문 SHA `84b44e6592e3a6bd883b7890239aada11382cbef9a369ebb0aca3b15defddfe4`. 두 방식 모두 Luna·examples_answer_scope_v5·xhigh·출력16,384·180초·prompt_json이다. 본문360토큰/중첩60·최대근거5개·합계8,000자·근거당2,000자의 기존 검색 구성을 유지했다. 미채택 검색 후보와 새 프롬프트는 적용하지 않았다.

새 미열람 평가가 아니라 이미 공개된 검색 개발 질문의 답변 비교다. 질문마다 각 방식1회, 최대40호출·보수적 비용$5, 자동재시도0회다. 실행 전 두 응답 비용을 함께 예약하며 오류·비용 불명확 상태에서는 중단한다. [공식 가격](https://developers.openai.com/api/docs/pricing)을 재조회한 [가격 근거](pricing.json)를 사용하며 청구액과 구분한다.

## 답변 결과와 판단

**5번째 호출에서 JSON 응답 계약 위반으로 중단했다. 20문항 비교를 완료하지 못했으며 운영 승격은 보류한다.** R08의 rag 응답은 finish_reason=stop으로 도착했지만 JSON 대신 일반 문장이라 기존 서버 어댑터가 LLMResponseError를 반환했다. 원응답·사용량·비용을 먼저 저장하고 중단했으며 프롬프트 수정·응답 보정·재시도는 하지 않았다.

| 항목 | 관측 |
|---|---|
| 계획 / 실제 호출 | 40 / 5 |
| 완성된 비교 쌍 | 2/20 |
| 정상 응답 / 형식 오류 | 4 / 1 |
| 미호출 | 오류 상대 조건1개 + 시작하지 않은17문항34개 |
| 답변 불가 문항 실행 | 0/4 |
| 전체 보수적 추정 비용 | USD0.0332125 |
| 정상 완료 두 쌍의 필수 정보 완전 포함 | full1/2, rag1/2 |

두 독립 AI 평가자가 모드·실행 순서·사용량을 가린 답변을 채점한 뒤 매핑을 공개했다. R04 근태 정정은 두 방식 모두 People팀의 원본 근태·승인 이력 대조가 충분하지 않았고, R06 해외근무는 두 방식 모두 필수 조건을 포함했다. 2쌍으로 우열·일반 정확도·속도 개선을 주장하지 않는다. 실패한 R08의 원문에 지급일이 있어도 정상 답변 성공으로 세지 않는다.

R04 full의 두 번째 기준은 1차 평가자가 부분 포함, 2차는 누락으로 보았다. R08 실패 원문의 개인 지급 상태 확인 불가 표현도 1차는 corpus 미지원, 2차는 조회를 단정하지 않은 것으로 보았다. 두 의견은 덮어쓰지 않았으며 첫 차이는 완전 포함 집계에 영향이 없고 두 번째는 실패 원문의 진단에만 해당한다.

[집계·중단 사유](summary.json) · [40슬롯 비교표](comparison.csv) · [응답 원문·실패·미실행](responses.json) · [실행 기록](execution.json) · [비용 원장](ledger.json) · [준비 manifest](manifest.json) · [선택된 검색 근거](retrieved-contexts.json) · [익명 판정 입력](blind-review-packet.json) · [1차 AI 판정](blind-review-primary.json) · [2차 독립 AI 판정](blind-review-secondary.json) · [판정 후 모드 공개](mode-disclosure.json).

정상 답변 품질 비교와 JSON 전달 계약을 분리해 기록한다. 답변 불가 성능은 미평가이며 다음 단계는 형식 실패의 별도 원인 조사·개선 검토와 재평가 계획이다. 이번에는 생성 프롬프트·서버 정책을 바꾸지 않는다. 서비스 기본값은 full 그대로다.

## 문서 관리·배포 준비 검증

[실제 Tiny 검증](readiness-actual-tiny.json)에서 격리DB의71문서에 대해 모든 문서 삭제→빈 snapshot 안내, 기본 복원→새revision 준비전503→worker 연결후200을 확인했다. 삭제 직후 검색·생성·예약0회, 준비전 생성예약0회, 일치하는 baseline 복원 문서인코딩0회, 현재revision 근거만 포함했다. 생성은 모의이며 실제LLM과 구분한다.

[통합 검증 기록](readiness-checks.json)의 집중4개·관련95개가 통과했다. API기본 원본과 자정host원본이 다르면 변경된 입력을 계산하며 이전벡터를 잘못 재사용하지 않는다. 동시1/2/4 모의요청은 공개제한을 끈 상태의 겹침 검사다. 공개2슬롯 초과거부·취소후슬롯 유지·자정복원·mapping복구·worker복귀는 별도 기존 테스트로 확인했다.

Docker Desktop의 WSL 연동을 사용할 수 없어 실제 컨테이너 candidate·schema복구는 미검증이다. 운영서버에 대신 접속하지 않았다. 실제2vCPU·16GB 성능·사람검수·운영RAG전환은 후속이다.

## 재현과 원자료

```bash
uv run --locked python -m retrieval.experiments.answers --prepare \
  --cases retrieval/reports/2026-10-15-rag-answer-comparison/cases.json \
  --model /absolute/path/to/pinned-tiny --artifact-root tmp/answer-reproduction
uv run --locked python -m retrieval.experiments.answers --execute \
  --cases retrieval/reports/2026-10-15-rag-answer-comparison/cases.json \
  --model /absolute/path/to/pinned-tiny --artifact-root tmp/answer-reproduction \
  --env-file /absolute/path/to/local.env
```

prepare는 로컬 Tiny 색인과 입력만 준비한다. execute는 유료 API를 호출한다. 동일 artifact-root 재실행은 거부하며 실행 실패 후 새 root로 자동 재요청하지 않는다. 가격·모델·문항·설정·입력의 변경은 확인 후 별도 실험으로 다룬다.

실제 원자료는 별도 작업 공간의 `tmp/answer-evaluation/`에 있다. 이는 `/tmp` 메모리 파일시스템이 아닌 프로젝트 작업 공간 아래이며 공개 다운로드 경로가 아니다. 모델·색인·DB·중복 전체 prompt는 Git에 넣지 않는다. 게시한 결과의 근거와 미복제 원자료 범위를 구분한다.

[실행·복원 안내](../../../docs/rag-runtime.md) · [작업 기록](../../../docs/worklogs/2026-10-15-rag-answer-comparison.md)

## 개발 PC CPU 제한 측정

CPU affinity 2개·torch thread 1에서 R04를 warmup 1회 후10회 검색했다. p50 44.067ms·p95 46.348ms, peak RSS 1,017,672KiB였다. 질의 임베딩과 검색·근거 조립만 포함하며 모델 로딩·HTTP·생성은 제외한다. 한 질문의 개발 PC 측정으로 실제2vCPU 운영 성능을 입증하지 않는다. [설정·개별 측정값](readiness-local-cpu.json).
