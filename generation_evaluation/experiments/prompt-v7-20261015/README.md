# GPT-6 Luna prompt-v7 fixed evaluation fixtures

These files freeze the question sets and candidate-neutral judging criteria for the readability/completeness comparison. They are AI-authored fixtures for this experiment, not human-approved policy examples or evidence of general operating quality.

## Frozen source

- Snapshot: `/home/jake/workspace/projects/sanaebi/tmp/readability-v6-20261015/snapshot.json`
- Snapshot fingerprint: `9d02a7ba77a340bea017e89ab43e25db62a8cdeef83b2a40c5bbfb203a8eddf7`
- Snapshot contains 72 documents. The raw snapshot remains outside the repository; each published-document evidence quote in these fixtures was checked as an exact substring of its referenced document body.
- `runtime_contract` evidence points to the current generation prompt/profile and is used only for assistant behavior or service scope, never as company policy evidence.

## Development set

`development.json` contains 12 cases: the prior eight fixed development cases (`R01`–`R08`) plus four new development cases (`D09`–`D12`). The earlier cases retain their question, required/forbidden criteria, and existing evidence; `R07` previously had no evidence, so an exact runtime clarification instruction is now recorded. New cases cover meeting decision records, shared-drive recovery, customer bug handoff, and safe generative-AI use.

These prior cases have been observed in earlier work and are not an unseen evaluation set.

## Final selection set

`selection.json` contains 12 AI-authored cases with the approved allocation:

| Category | Cases |
|---|---:|
| Capability introduction | 2 |
| Short single fact | 1 |
| Ordered multi-step procedure | 2 |
| Conditional alternatives | 2 |
| Partial answer and unknown detail | 1 |
| Out-of-scope general knowledge | 1 |
| Ambiguous work context | 1 |
| Composite incident response | 2 |

The two capability cases use distinct audiences and tasks, but the broad capability-introduction intent is also present in development case `R01` and in a synthetic prompt example. They are therefore explicitly marked as exposed and must not be described as wholly unseen capability intents. Other selection case intent-group IDs are disjoint from development case IDs and task groups; the fixtures do not imply independent human authorship.

## Judging

Each case separates required claims, critical claims, optional context, forbidden claims, exact evidence, common readability, and a case-specific structure rubric. Optional context is not a pass requirement. Content, common readability, and structure adherence are scored independently. A short answer can pass without Markdown; ordered steps and conditional alternatives are judged differently. Missing/uncertain/API-failure cases remain in the denominator and are not promoted to pass.

The selection rubric and thresholds are also recorded in [acceptance.md](acceptance.md); the response judgment format is in [judge-contract.md](judge-contract.md). The pricing metadata and source link are in [pricing.json](pricing.json), checked against the [OpenAI API pricing page](https://developers.openai.com/api/docs/pricing). The fixture itself is not sent to the generation model as a rubric.

## Planned use and limits

The [run.py](run.py) runner uses these fixed files with the frozen snapshot. The approved plan allows 36 development calls, an optional 12-call combined candidate only if both independent candidates merit it, and a 72-call final comparison after candidate freeze, for a shared maximum of 120 generation attempts. Failures count toward that cap. No API call or model judgment is represented by the fixture authoring step.

The selection set is a small AI-authored comparison set. It cannot establish broad accuracy, production readiness, or human policy approval.

## 재현 명령과 실행 순서

모든 명령은 저장소 루트(이번 실행은 `/tmp/sanaebi-prompt-v7-20261015`)에서 실행한다. API 키는 로컬 환경에서 준비하며 명령·저장소에 값을 넣지 않는다. 파이썬이 generation 패키지를 찾도록 PYTHONPATH=.를 유지한다. 실행기는 질문·루브릭·snapshot·가격표·실험 코드·프롬프트 해시를 global manifest에 고정한다.

### 1. API 호출 없는 사전 점검

다음은 실험 호출 전에 snapshot·문항·설정·가격·근거 인용·요청 슬롯을 검증한다. preflight-only도 manifest와 stage preflight 파일을 output 경로에 기록하지만 모델/API는 호출하지 않는다. 이미 다른 manifest가 있는 output 경로를 재사용하지 말고, 새 고유 경로를 선택한다.

    PYTHONPATH=. uv run --locked python generation_evaluation/experiments/prompt-v7-20261015/run.py --snapshot tmp/prompt-v7-20261015/snapshot.json --output tmp/prompt-v7-20261015/preflight-review-readme --stage development --preflight-only

### 2. 개발 단계 36회

개발 단계는 12개 문항 각각에 대해 v5, 가독성 후보, 완전성 후보를 한 번씩 순차 실행한다. 모든 단계가 같은 output root를 사용한다.

    PYTHONPATH=. uv run --locked python generation_evaluation/experiments/prompt-v7-20261015/run.py --snapshot tmp/prompt-v7-20261015/snapshot.json --output tmp/prompt-v7-20261015/run-001 --stage development

개발 실행은 각 요청 슬롯을 호출 직전에 하나씩 예약한다. 오류로 멈춘 뒤 이어갈 때도 위와 같은 snapshot·문항·코드·설정·가격과 같은 output 경로를 사용한다. 같은 output root의 global manifest가 snapshot·문항·루브릭·가격·모델 설정·소스 코드 fingerprint를 고정하므로, 이 항목들이 달라지면 기존 실행 재개를 거부한다. 결정 파일을 바꾸면 stage manifest 해시도 달라져 기존 단계 등록과 충돌하므로 새 실험 root를 사용한다. 새 output 경로를 만들면 기존 ledger와 이어지지 않는다.

### 3. 개발 결과 검토 후 선택

combination 또는 final을 시작하기 전에 run-001/reviews/final-decision.json 같은 결정 JSON을 준비한다. 결정은 development 단계가 완료된 뒤 생성된 stage-manifest.json의 SHA-256에 연결되어야 한다. 필요한 필드는 decision_id, development_manifest_sha256, rationale이다.

- 결합 비교는 가독성·완전성 후보를 모두 유지하고 결합도 승인할 때만 수행한다. 결정 JSON에 readability_approved, completeness_approved, combination_approved가 모두 true여야 한다.
- 최종 비교는 final_approved=true, selected_profile, 해당 후보의 승인 필드가 필요하다. 선택 후보가 가독성이면 readability_approved, 완전성이면 completeness_approved, 결합이면 combination_approved를 true로 둔다.
- 결합 후보를 최종 선택할 때는 먼저 combination 단계를 12회 완료해야 한다. 결합이 승인되지 않으면 이 단계는 건너뛴다.

선택적으로 결합을 승인한 경우:

    PYTHONPATH=. uv run --locked python generation_evaluation/experiments/prompt-v7-20261015/run.py --snapshot tmp/prompt-v7-20261015/snapshot.json --output tmp/prompt-v7-20261015/run-001 --stage combination --decision tmp/prompt-v7-20261015/run-001/reviews/combination-decision.json

현재 저장된 결정은 readability 후보와 결합을 승인하지 않고, 완전성 후보를 최종 반복 비교 대상으로 선택한다. 이 결정에 따른 최종 72회 실행 및 같은 원장으로의 재개 명령은 다음과 같다.

    PYTHONPATH=. uv run --locked python generation_evaluation/experiments/prompt-v7-20261015/run.py --snapshot tmp/prompt-v7-20261015/snapshot.json --output tmp/prompt-v7-20261015/run-001 --stage final --decision tmp/prompt-v7-20261015/run-001/reviews/final-decision.json

final은 12개 선정 문항 × v5/선정 후보 × 3회다. 같은 명령으로 재개하면 완료된 성공·실패 슬롯은 건너뛴다. 원장에 started만 있고 finished가 없는 슬롯은 결과가 불확실하므로 자동 재호출하지 않는다. 이 슬롯을 지우거나 원장을 초기화해 같은 실행을 반복하지 않는다. 실행 중인 프로세스가 있을 때는 두 번째 실행기를 동시에 시작하지 않는다. 중단·실패 후 기존 프로세스가 끝난 것을 확인한 다음 같은 명령으로 이어간다.

### 실행 한도, 예약 및 비용 해석

전체 원장은 모든 단계를 합쳐 최대 120개 요청 슬롯을 원자적으로 예약한다. 구성은 개발 36회, 조건부 결합 12회, 최종 72회다. 결합을 생략하면 실제 최대는 108회다. 슬롯을 호출하기 전에 SQLite 원장에 예약하므로, 실패한 호출이나 결과가 불확실한 시작 슬롯도 전체 상한을 차지한다. 재시도는 없다.

가격 파일은 2026-10-15에 확인한 OpenAI GPT-6 Luna 가격을 기준으로 입력 100만 토큰당 0.25달러, 출력 100만 토큰당 0.75달러를 사용한다. 입력 예약은 직렬화된 프롬프트의 UTF-8 byte 수에 512를 더한 값을 토큰의 계획용 근사치로 보고, 출력은 최대 16,384토큰으로 예약한다. 이는 tokenizer 기준의 보장이나 청구서가 아니며 전체 비용의 수학적 상한도 아니다. 출처와 한계는 [pricing.json](pricing.json)에 기록되어 있다.

응답에 input_tokens와 output_tokens가 모두 유효하게 기록되면 해당 사용량으로 비용을 추정한다. 둘 중 하나라도 없으면 비용을 0으로 간주하지 않고 호출 전 예약액을 유지한다. 이 금액 역시 가격표 기준 추정치이지 실제 청구액이 아니다. 각 단계의 summary.json에서 완료·불확실·미시작 슬롯, 전체 누적 예약 시도 수, 추정 비용을 확인한다.

### 실제 실행과 판정

[최종 보고서](../../reports/2026-10-15-prompt-v7/README.md)에 실제 호출 수, 단계 선택, 독립 판정과 기본값 결정을 기록한다. 진행 도중 저장된 summary는 중간 상태이므로 최종 보고서의 완료 근거와 구분한다. 판정 집계 전에는 [별도 자료 완결성 감사](../../reports/2026-10-15-prompt-v7/validate_evidence.py)로 응답·익명 매핑·판정의 일대일 대응과 문항별 필수 항목 수를 확인한다.

## 원 실행의 복구 상태

재부팅 뒤 기존 `/tmp/.../run-001` 원장이 소실됐다. 이미108회를 사용했으므로 위 명령에 새 빈 원장을 만들어 원 실행을 재호출하면 안 된다. 답변·판정의 복구 결과와 누락된 측정 자료는 [최종 보고서](../../reports/2026-10-15-prompt-v7/README.md)를 따른다. 새 실제 실험은 별도 승인과 한도·ID가 필요하다. 영구 저장 경로에 원자료를 두고 종료 전 검증·백업해야 한다.
