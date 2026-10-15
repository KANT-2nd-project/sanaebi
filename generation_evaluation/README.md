# 생성 실행 기록과 기초 집계

사용자가 AI 튜터의 설명·힌트·모범 답안을 참고해 직접 구현 중인 평가 모듈이다. 테스트 작성·검증과 요청한 기록 검증·복원 구현은 AI에 위임했다. 보관된 `archive/answering_v1/answer_pipeline/`와 활성 API에는 연결하지 않았다. 기초 단계에서는 사용자의 문서 한 건 smoke 결과를 확인했고, 이후 별도 selection 실행기로 고정 문항 비교를 수행했다. 현재 모델 선택·후속 실험과 과거 기초 단계 기록을 구분한다.

## 코드와 계약

| 파일 | 책임 |
|---|---|
| [types.py](types.py) | GenerationRun: case_id, config, result, elapsed_seconds, error_type |
| [runner.py](runner.py) | 공통 generate_from_documents를 호출하고 perf_counter로 경과 시간 측정 |
| [metrics.py](metrics.py) | 상태별 개수·완료 비율·평균 시간·설정별 그룹화·GenerationSummary 조립 |
| [reporting.py](reporting.py) | 기록 사전 변환·JSONL 저장/읽기·타입 복원 |

run_case에는 질문·문서 문자열 목록·미리 만든 호출 함수를 전달한다. 공통 진입점 generate_from_documents를 사용하며, 경과 시간은 프롬프트 구성·모델 호출·파싱을 포함한다. 문서 읽기와 클라이언트 초기화는 제외한다. 이전의 호출·파싱만 측정한 기록과 측정 범위가 다르므로 구분한다. config는 기록용으로 전달되므로 호출 함수가 실제로 그 설정에서 생성됐는지는 아직 강제하지 않는다.

정상·파싱 실패·빈 답변·시간 초과·출력 잘림·명시적 거절은 GenerationResult와 error_type=None으로 기록한다. 그 밖에 generate가 전파한 Exception은 result=None과 예외 클래스 이름으로 기록하며 시간도 남긴다. 평가 경계의 광범위한 예외 처리는 구현 버그도 포착할 수 있으므로 실행 오류를 숨기거나 성공으로 집계하지 않는다. KeyboardInterrupt는 전파한다. 전체 traceback과 상세 오류 메시지는 아직 보존하지 않는다.

## 집계 의미

| 함수 | 의미 | 빈 입력 |
|---|---|---|
| count_outcomes | total, completed, parse_error, empty_answer, timeout, truncated, refusal, execution_error 개수 | 모든 값 0 |
| completion_rate | completed / 전체 시도 수, 실패도 분모에 포함 | None |
| mean_attempt_seconds | 실패 포함 전체 기록의 평균 시간 | None |
| mean_completed_seconds | 오류 없고 결과가 COMPLETED인 기록만의 평균 시간 | None |
| group_by_config | 제공자·모델 이름·제한 시간·문맥/출력 한도가 같은 기록을 리스트로 묶음 | 빈 사전 |

COMPLETED는 기본 형식의 답변을 얻었다는 뜻이며 정답률·근거 충실성 판정이 아니다. 완료 비율과 실패 개수를 평균 시간과 함께 봐야 빠른 연결 실패를 모델 응답 속도로 오해하지 않는다. 예를 들어 정상 2초·4초, 시간 초과 30초, 연결 실패 0.2초면 전체 평균은 9.05초, 완료 평균은 3초다. 이는 설명용 숫자이지 실모델 측정 결과가 아니다.

현재 count_outcomes는 결과와 오류가 모두 없으면 ValueError를 발생시킨다. GenerationRun 생성 시 결과와 오류 중 정확히 하나가 있는지, 경과 시간이 유한한 0 이상인지, 오류 이름이 공백이 아닌지 검사한다. 복원 함수는 추가로 필수 키와 필드 타입을 검사한다. 그룹 키에는 데이터·문서 snapshot·프롬프트 버전·실행 회차가 아직 없으므로 실험 동등성의 근거로 사용하지 않는다.

## CLI 기록과 메타데이터

독립 생성 CLI도 run_case를 사용한다. ModelResponse의 입력/출력 토큰과 종료 사유를 GenerationResult에 보존하며, length는 TRUNCATED로 기록한다. 잘린 출력은 전체 시도·전체 평균에는 포함하고 완료 비율의 분자·완료 평균에서는 제외한다. JSON 형식 성공은 정답률이 아니다.

config에는 context_window·max_output_tokens가 포함된다. CLI가 추가하는 experiment·model_alias·question은 현재 GenerationRun 필드가 아니므로 run_from_dict로 복원하면 보존되지 않는다. CLI의 들여쓴 JSON 한 건은 JSONL이 아니므로 json.loads로 읽어 run_from_dict에 전달한다. 여러 행 JSONL 저장은 save_runs_jsonl을 사용한다.

## 저장과 복원

`summarize_runs`는 모델 설정·prompt_profile별 GenerationSummary 목록을 반환한다. 빈 입력은 빈 목록이며, 이것은 품질 판정이나 실험 동등성 검증이 아니다.

`save_runs_jsonl(path, runs)`는 원문을 포함한 실행 기록을 UTF-8 JSONL로 저장한다. 직렬화를 먼저 끝내고 상위 디렉터리를 만든 뒤 배타적 생성으로 기존 파일 덮어쓰기를 막는다. NaN·무한대 JSON 직렬화를 거부한다. 디스크 쓰기 실패·프로세스 중단까지 원자적으로 복구하는 방식은 아니다.

`read_runs_jsonl(path)`는 순서를 유지한 객체 목록을 읽고 문법 오류·빈 줄·비객체 행을 줄 번호와 함께 거부한다. `run_from_dict`가 설정·생성 결과를 복원하고 타입·도메인 검증을 적용한다. `None` 결과는 실행 오류 기록이며 timeout 결과와 구별한다. 새 설정·사용량·종료 사유를 복원하고 구형 기록의 누락 필드는 None으로 읽는다. 토큰 수는 bool이 아닌 0 이상의 정수 또는 None으로 검사한다. 별칭/실험만으로 동일 실행 조건을 보장하지 않는다.

```python
runs = [run_from_dict(row) for row in read_runs_jsonl(path)]
summaries = summarize_runs(runs)
```

파일 전체 객체 복원 오류에 줄 번호를 붙이는 별도 loader는 아직 없다. 저장 형식에는 문서/프롬프트 해시가 있지만 schema_version·측정 범위 버전은 아직 없다. 서로 다른 실행 조건의 파일을 임의로 혼합하지 않는다.

## 검증과 다음 단계

저장소 루트에서 실행한다. 가짜 클라이언트·응답·시계만 사용한다.

```bash
uv run --locked python -m unittest discover -s tests -p 'test_generation_*.py' -v
```

문서/프롬프트 식별과 전체 문서 배치 실행을 연결했고, 소수 문항의 속도·근거 품질을 검토했다. 별도 selection 실행기에 답변 가능성·필수 근거 평가셋, 예산·재개, 근거 추출/답변 분리 및 두 모델 비교를 구현했다. 아래 독립 비교 절과 [선정 실험 기록](../docs/worklogs/2026-10-15-generation-selection.md)을 따른다. 기존 CLI와 서버 연결 상태는 별개다. 새 모듈은 아직 설치 패키지 목록에 포함하지 않았다. [생성 모듈](../generation/README.md), [품질 평가 기준](../docs/generation-evaluation.md), [이번 작업 기록](../docs/worklogs/2026-10-15-generation-presets-usage-policy.md)을 함께 따른다.

## 실행 입력 식별

run_case는 로드된 문서 문자열 목록을 순서대로 JSON 직렬화하여 documents_sha256과 document_count를 기록한다. 실제 모델 연결부에 전달하는 system/user 메시지 객체의 해시를 prompt_sha256으로 남긴다. 두 해시는 UTF-8, ensure_ascii=False, separators=(",", ":")로 직렬화한 SHA-256이다. 문서 해시는 원본 JSONL 파일 해시가 아니며, 프롬프트 해시는 질문까지 포함하므로 질문마다 달라진다. 제공자 내부 채팅 템플릿이나 tokenizer를 식별하지는 않는다.

세 필드는 GenerationRun과 JSONL 저장·복원에 유지된다. 구형 기록의 누락 값은 None으로 복원하며 현재 파일에서 추정해 채우지 않는다. 문서 수는 bool이 아닌 0 이상의 정수, 해시는 소문자 16진수 64자리 또는 None을 요구한다. 프롬프트 구성 실패 시 prompt_sha256은 None이고, 모델 호출 중 실패·timeout은 이미 계산한 프롬프트 해시를 보존한다.

문서 해시는 시간 측정 전에 계산하고 프롬프트 해시는 호출 직전에 측정 구간 안에서 계산한다. 해시 기록 전후 시간에는 이 작은 부가 작업의 차이가 있다. 기초 summarize_runs 집계는 모델 설정·prompt_profile별이며 입력 조건을 검사하지 않는다. 공통조건 비교에는 아래 summarize_comparable_runs를 사용한다. experiment·model_alias·question의 별도 필드는 CLI에만 존재한다.

## 공통조건 비교 집계

```python
from generation_evaluation.metrics import summarize_comparable_runs
from generation_evaluation.reporting import read_runs_jsonl, run_from_dict

runs = [run_from_dict(row) for row in read_runs_jsonl(path)]
summaries = summarize_comparable_runs(runs)
```

이 함수는 모든 기록의 문서 해시·문서 수가 같고, 같은 case_id의 실제 프롬프트 해시가 같으며, 설정별 문항 목록과 문항별 시도 수가 일치할 때만 요약한다. 서로 다른 문항은 서로 다른 프롬프트를 가질 수 있다. 실패 기록도 식별 정보가 있으면 분모에 포함하며, 식별 정보가 없는 구형 기록이나 프롬프트 구성 실패는 조용히 제외하지 않고 비교를 거부한다. 해당 기록의 오류 분석에는 기존 summarize_runs를 사용한다.

CLI의 case_id=manual은 서로 다른 질문을 하나의 비교 세트에 넣기에 적합하지 않다. 평가에서는 run_case에 문항별 고정 ID를 전달해야 한다. 프롬프트가 달라진 동일 문항은 별도 실험으로 취급한다. 이 검사는 공통조건 비교용이며 모델별 프롬프트 튜닝 비교에는 그대로 적용하지 않는다.

검사는 관측된 기록 사이의 일치만 확인한다. 모든 설정에서 똑같이 빠진 문항, 복제된 시도, 실행 회차·환경·모델 digest·평가 루브릭의 동일성은 검증하지 않는다. 예정 문항 manifest와 attempt ID가 아직 없으므로 평가 완결성이나 정답 품질을 보증하지 않는다. 빈 입력은 빈 목록을 반환한다.

## 기존 질문 CSV 배치 실행

`python -m generation_evaluation`은 저장소의 data/dataset.csv를 UTF-8 BOM 대응으로 읽고 기준 라벨 SEARCH_KNOWLEDGE만 선택한다. question_id 순으로 정렬하고 해당 ID를 case_id로 유지한다. 질문 원문만 모델에 전달하며 라벨·검수 기록은 프롬프트에 넣지 않는다. 선택 문항의 빈 ID·빈 질문·중복 ID 및 선택 결과가 없는 입력은 호출 전에 거부한다. 기준 라벨 선택이지 분류기 예측 통과 결과가 아니다.

```bash
uv run --locked python -m generation_evaluation \
  --limit 1 \
  --output tmp/generation-baseline-first.jsonl
```

기본값은 company-final-v1 / gpt-6-luna이며 최종 scope 프롬프트를 사용한다. [생성 실행 안내](../generation/README.md#독립-실행)에 따라 snapshot과 OPENAI_API_KEY를 준비한다. .env 사용 시 uv run에 --env-file .env를 추가한다. 전체 실행은 --limit을 생략하고 새 출력 경로를 지정하며, 선택 문항 수만큼 유료 호출이 발생한다. 문서 증가 시 입력 한도와 지연을 다시 확인해야 한다.

문서 로드와 클라이언트 생성은 한 번씩 수행한다. 출력은 x 모드로 열어 기존 파일을 덮어쓰지 않고 각 실행 결과를 JSONL 한 줄로 쓰고 flush한다. 모델 실행 오류도 기록하고 다음 문항으로 진행하며 KeyboardInterrupt는 전파한다. 중단 전에 저장된 줄은 남지만 재개 기능·fsync·디스크 장애의 원자적 복구는 없다. 초기 클라이언트 생성 실패는 빈 출력 파일을 남길 수 있다. 출력 상대 경로는 현재 작업 디렉터리 기준이다.

각 행에는 GenerationRun 필드와 experiment·model_alias·question·dataset_sha256·selection_label·available_cases·planned_cases·attempt_index를 저장한다. dataset_sha256은 이번에 읽은 CSV 원본 바이트의 해시다. 추가 필드는 run_from_dict 객체 복원 시 유지되지 않으므로 원본 JSONL도 보존한다. planned_cases와 attempt_index는 중단 점검용이며 완전한 실행 manifest나 고유 attempt ID를 대체하지 않는다.

진행 상황과 실행 오류 종류는 stderr, 최종 실행 개수 요약은 stdout에 출력한다. Provider 예외 원문은 인증 정보 노출을 피하기 위해 출력하지 않는다. 모든 결과가 COMPLETED이면 종료 코드 0, 실행은 끝났지만 실패 결과가 있으면 1이다. 설정·파일 오류와 중단은 예외로 종료한다. COMPLETED 개수는 정답 개수가 아니다. 이 명령은 구성된 provider를 실제 호출하므로 OpenAI 설정을 선택하면 외부 전송·유료 호출이 발생할 수 있다.

## 전체 문서 속도와 품질 진단

[속도·품질 일지](../docs/worklogs/2026-10-15-generation-tps-quality.md)에 71문서 첫5건의 주장별 검토와 KV cache/GPU 배치 실험을 기록한다. 상세 원자료·환경·공식 참조·2×2 비교는 로컬 `tmp/generation-tps-quality-20261015/`에 있다.

별도 Ollama는 [생성 실행 안내](../generation/README.md#로컬-gpu-실험-실행)에 따라 시작하고, 평가 호출 프로세스에도 `OLLAMA_HOST=http://127.0.0.1:11435`를 설정한다. 기존 모델 별칭과 전체문서 프리셋을 유지한다.

일반 GenerationRun의 elapsed_seconds는 요청 경로 전체시간이다. 이번 진단 스크립트는 동일 문서 로더·프롬프트 빌더·LangChain 메시지 변환을 사용하되 provider metadata를 별도로 저장해 순수 생성 TPS를 계산했다. 이 timing metadata가 일반 JSONL 계약에 자동 추가된 것은 아니다. 문서 수동 subset이나 강화 prompt는 진단용 비교 조건이며 현재 공통 생성 프롬프트나 검색기로 자동 적용되지 않는다.

GPT-6 Luna 비교 프로필은 [생성 실행 설정](../docs/generation-runtime.md)을 따른다. 실행 기록의 config에는 reasoning_effort·temperature도 보존하며, 과거 기록에 없으면 None으로 복원한다. 최신 교차 비교는 [GPT 비교 일지](../docs/worklogs/2026-10-15-generation-openai-comparison.md)에 기록한다.

프롬프트의 적용 범위·조회 권한·조건 보존 강화 A/B는 [후속 일지](../docs/worklogs/2026-10-15-generation-prompt-ab.md)에 기록했다. 프롬프트 후보 간에는 prompt hash가 달라지는 것이 정상이다. `summarize_comparable_runs`의 동일 문항 prompt 검사에 서로 다른 후보를 섞지 말고 후보별 동일 입력의 모델 비교로 구분한다. 호출 구조 성공, 필수 안내 충족, 추가 주장 오류, 과잉 유보를 분리하여 평가한다.

## 예산 제한이 있는 독립 비교

`python -m generation_evaluation.selection`은 기존 평가 CLI와 별도의 실험 진입점이다. [고정 평가 세트](benchmarks/selection-20261015/README.md)와 [차원별 판정 기준](../docs/generation-evaluation.md)을 먼저 읽는다.

```bash
uv run --locked --env-file /path/to/local/.env python -m generation_evaluation.selection \
  --candidates generation_evaluation/experiments/selection-20261015.json \
  --candidate gpt-baseline \
  --cases generation_evaluation/benchmarks/selection-20261015/dev.json \
  --documents tmp/evaluation-documents.jsonl --phase dev \
  --ledger tmp/selection/budget.json --output tmp/selection/dev-gpt-baseline
```

모든 후보는 같은 ledger를 사용한다. `--total-dollars`, `--dev-dollars`, `--total-seconds`, `--dev-seconds`로 실행 한도를 지정하며 기본값은 각각5달러·3달러·7200초·4200초다. 한도는 manifest와 공용 원장에 고정되므로 새 output에서도 다른 한도로 재개할 수 없다. 이미 시작한 원장의 시간·예약 이력을 지우지 않는다. 프로필은 baseline/concise/examples와 GPT 강화 실험용 examples_coverage/examples_conditions/examples_json, 전략은 single/evidence_first이다. `--start-repeat 2`와 새 output 경로로 선택 후보의 두 번째 회차를 실행한다. 같은 실행 명령의 재개는 이미 저장한 항목을 건너뛰며 입력·설정·코드 hash가 달라지면 거부한다. 시작 이벤트만 남은 호출은 비용/완료 여부를 수동 확인하기 전 자동 재호출하지 않는다. 재개는 원장의 고정 식별자와 기존 호출의 예약 이력도 확인하므로 새 원장으로 예산을 초기화할 수 없다. 원장을 옮길 때는 기존 실행을 멈추고 식별자·전체 이력을 함께 보존한다. 코드 hash가 다른 과거 실행은 당시 코드에서 재개한다.

API 키와 실제 환경 파일, 원문 응답 전체는 `tmp/` 또는 별도 비공개 경로에 보관한다. 결과 보고서에는 필요한 응답 비교·판정·설정·hash·집계만 남긴다. 실험 결과를 기본 설정에 자동 적용하지 않는다.

실제 후보 비교와 두 차례의 별도20문항 선정 결과는 [모델 선정 보고서](reports/2026-10-15-model-selection/README.md)에 모은다. 원응답·문항별 판정·근거·비용·반복 변동을 함께 보고, 기본값 승격 여부를 일반적인 서비스 정확도와 구분한다.

현재 선택 모델은 **GPT-6 Luna**다. 두 후보의 상대 비교로 선정했으며 기본 설정 승격·서비스 품질 승인과는 구분한다. 후속 기준 구성과 실험 준비는 [GPT-6 Luna 프롬프트 강화 계획](../docs/generation-luna-prompt-improvement.md)을 따른다.

## 연구 기반 후속 실행

[후속 후보 설정](experiments/luna-reference-followup-v1/README.md)은 `selection` 실행기에 `--rubric`, `--unlimited-budget`, `--max-calls 166`을 전달한다. 금액·전체 시간 상한을 생략해도 호출별 timeout과 비용 추적은 유지한다. 기존 CLI의 기본 예산은 유한한 값으로 유지한다.

루브릭은 입력 문항을 모두 포함해야 하며 모델 메시지에는 전달하지 않는다. manifest는 루브릭과 코드·스키마·lock 해시를 기록한다. 바뀐 입력/코드로 같은 run을 이어 실행하지 않으며, 저장된 실패도 자동 재호출하지 않는다. 시작 기록만 있는 요청은 확인 없이 재호출하지 않는다. 모든 후보가 동일 원장을 공유해 실패·불확실 예약을 포함한 166회 상한을 원자적으로 적용한다.

기록에는 `output_mode`와 거절 정보가 추가된다. 과거 설정은 prompt_json, 과거 거절 필드는 None으로 복원하며 과거 판정은 재작성하지 않는다. 추가 키 응답은 신규 파싱에서 parse_error이므로 과거 실행 완료 수치와 형식 기준의 차이를 구분한다.

GPT-6 Luna 답변 범위·strict 출력 후속 비교는 [결과와 채택 판단](reports/2026-10-15-luna-reference-followup/README.md)을 참조하세요. 당시 두 후보는 필수 안내 회귀로 탈락했습니다. 이후 사용자 최종 선택은 [보강 프롬프트 확정](../docs/generation-final-prompt.md)을 따릅니다. 후속 최종20문항과 반복 안정성은 미실행입니다.

## 최종 프로필 기록 호환성

run_case는 기본 examples_answer_scope_v3을 사용하며 keyword-only prompt_profile로 과거 프로필을 지정할 수 있다. 새 기록은 프로필과 실제 프롬프트 해시를 함께 남긴다. 과거 누락 profile은 None이며 새 기본값으로 소급하지 않는다. summarize_runs는 모델 설정과 프로필을 함께 묶고 group_by_config는 기존 모델 설정별 인터페이스를 유지한다. 비교 집계는 각 설정·프로필 그룹의 문항과 시도 수도 검사한다. [실행 반영 기록](../docs/worklogs/2026-10-15-generation-final-runtime.md)을 참조한다.
