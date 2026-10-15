# GPT-6 Luna 프롬프트 강화

> 현재 최종 구성은 [프롬프트 확정·튜닝 종료](generation-final-prompt.md)를 따른다. 아래 비교와 유지/보류 결정은 해당 실험 시점의 기록이다.

두 모델 중 더 좋은 모델을 고른다는 기존 목적에 따라 **GPT-6 Luna를 선택했다.** 이후에는 같은 모델의 필수 안내 누락을 줄이는 프롬프트를 비교한다. 모델 선택과 기본 설정 승격·서비스 품질 승인은 별도 결정이다. 이전 Qwen/GPT 점수와 당시 판단은 [이전 선정 보고서](../generation_evaluation/reports/2026-10-15-model-selection/reasoning-extension/README.md)에 보존한다.

이번 구현·실행과 채택 판단의 기준 위치는 [프롬프트 강화 보고서](../generation_evaluation/reports/2026-10-15-luna-prompt-improvement/README.md)다. [작업 일지](worklogs/2026-10-15-generation-luna-prompt-experiment.md)는 변경 계기·검증·게시를 기록한다. 이번 실험·판정은 AI 위임 수행이며 사용자의 독립 숙련도나 사람의 품질 승인을 의미하지 않는다.

## 비교한 구성

기준은 GPT-6 Luna / examples / single / reasoning xhigh / 출력4096 / timeout180초이며 temperature는 전달하지 않는다. [후보 설정](../generation_evaluation/experiments/luna-prompt-improvement-20261015/candidates.json)의 모델·추론·문서·전략은 같고 다음 프롬프트 요소만 바꾼다.

| 후보 | 프로필 | 변경 |
|---|---|---|
| luna-reference | examples | 기존 기준 |
| luna-coverage | examples_coverage | 답변 전 필수 안내 누락 점검 |
| luna-conditions | examples_conditions | 같은 업무의 조건·예외 연결 확인 |
| luna-json | examples_json | 합성 대조 예시의 답변을 JSON 계약으로 표현 |

공통 `generation/prompts.py`의 역할·말투·근거·출력 규칙에 `generation/profiles.py`의 선택형 규칙과 예시를 더한다. 따라서 실험의 실제 입력은 prompts.py만 읽어서는 모두 확인할 수 없다. [실제 system 프롬프트](../generation_evaluation/reports/2026-10-15-luna-prompt-improvement/system-prompts.json)와 각 실행의 프롬프트 hash를 함께 확인한다. 합성 예시의 정책을 회사 정책으로 사용하지 않도록 경계를 유지한다.

## 평가와 현재 결정

개발8문항에서 기준과 필수 안내 점검을 각각2회, 조건 연결·JSON 예시를각1회 실행했다. 통과는 기준11/16, 필수 안내 점검13/16, 조건 연결6/8, JSON 예시5/8이었다. 조건 연결과 JSON 예시가 연속으로 최선 후보보다 개선되지 않아 추가 튜닝을 중단했다. 새20문항각2회 비교에서 기준은29/40·안정14/20, 필수 안내 점검은27/40·안정13/20이었다. 개발 개선이 재현되지 않아 기준 examples를 유지하고 coverage는 채택하지 않는다. 사용자 요청으로 회귀 후속 실행·게시를 일시 중단하며 완료 범위는 보고서를 따른다.

[판정 기준](../generation_evaluation/benchmarks/luna-prompt-20261015/rubric.json)은 형식, 문서 근거, 적용 범위·조건, 필수 안내, 유보, 조회·실행 경계, 한국어 존댓말, 관련성의8차원이다. 문항별 필수 주장·금지 주장·정확한 원문 구간을 사전에 고정했다. 의미가 같은 표현은 인정하며 선택적 배경 누락은 감점하지 않는다. 형식 실패·잘림·불확실을 제외하거나 통과로 간주하지 않는다.

[새20문항](../generation_evaluation/benchmarks/luna-prompt-20261015/README.md)은 기존48개 질문 그룹과 구분하고 독립 작성·검토했다. 같은71문서를 사용하며 일부 인접 정책이 남아 새로운 정책 일반화 검증은 아니다. 최종 결과를 본 뒤 프롬프트를 고쳐 같은 최종 점수로 다시 제시하지 않는다. 이전 두20문항은 이미 열람한 회귀 자료로만 사용한다.

## 재현

기존 공통 CLI와 서버 기본값을 자동으로 바꾸지 않는다. 아래는 selection 실행기에서 기준을 명시하는 재현 명령이다. 문서는 보고서에 기록된 snapshot과 동일해야 한다. 환경 파일·API키는 저장소에 넣지 않는다.

```bash
uv run --locked --env-file "$SANAEBI_ENV_FILE" python -m generation_evaluation.selection \
  --candidates generation_evaluation/experiments/luna-prompt-improvement-20261015/candidates.json \
  --candidate luna-reference \
  --cases generation_evaluation/benchmarks/luna-prompt-20261015/final.json \
  --documents "$LUNA_DOCUMENTS" --phase final \
  --ledger "$LUNA_LEDGER" --output "$LUNA_OUTPUT" \
  --total-dollars 3 --dev-dollars 1.2 --total-seconds 7200 --dev-seconds 4200
```

필수 안내 점검은 `--candidate luna-coverage`로 실행한다. 두 번째 반복은 같은 원장과 새 output에 `--start-repeat 2`를 지정한다. 처음에는2시간·3달러를 승인받았고 이후 사용자가 비용 제한을 철회했다. 이번에는 충분한 운영 상한3달러를 유지했으며 이전 실험의 원장·시간을 초기화하지 않았다. 예산은 호출 전 입력·최대 출력을 예약하고 확인된 사용량으로 정산한다. 실제 청구 금액과는 구분한다.

같은 실행의 재개에서는 완료 항목을 건너뛰고 입력·설정·코드·원장 식별자·예약 이력을 확인한다. 다른 한도나 코드로 과거 출력 폴더를 재개하지 않는다. 문서가 추가·개정되면 새 snapshot/hash로 입력 예산·지연·답변 품질을 다시 평가하며 이번 성적을 그대로 승계하지 않는다.
