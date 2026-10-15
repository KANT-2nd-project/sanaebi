# GPT-6 Luna 선택 이후 프롬프트 강화 준비

## 확정한 결정

이번 모델 선정의 목적은 Qwen3 4B Q4_K_M과 GPT-6 Luna 중 더 좋은 모델을 고르는 것이었다. 상대 비교 결과에 따라 **GPT-6 Luna를 선택했다.** 이후 작업은 선택을 미루는 단계가 아니라 선택한 모델의 답변 품질을 개선하는 단계다.

최신 20문항×2회에서 GPT는 통과25·부분15·실패0, 중대한 오류0문항, 두 반복 통과11/20이었다. Qwen은 통과0·부분26·실패14, 중대한 오류5문항, 두 반복 통과0/20이었다. [최종 비교 근거](../generation_evaluation/reports/2026-10-15-model-selection/reasoning-extension/README.md)를 보존한다. 18/20 기준은 기본 설정 승격·서비스 품질 판단의 별도 목표이며 상대적인 모델 선택을 취소하지 않는다. 기존 실행 기본값과 서버 연결은 이번 준비에서 바꾸지 않았다.

## 준비된 자료와 아직 하지 않은 일

- [기준 후보 설정](../generation_evaluation/experiments/luna-prompt-improvement-20261015/baseline.json): GPT-6 Luna, examples, single, reasoning xhigh, 출력4096, timeout180초. temperature 미전달.
- [입력 고정 목록](../generation_evaluation/experiments/luna-prompt-improvement-20261015/inputs.json): 개발8·이미 열람한 두20문항 세트의 경로와 해시. 이전 문서 snapshot 식별 포함.
- [누락 분석 목록](../generation_evaluation/experiments/luna-prompt-improvement-20261015/omission-backlog.json): GPT의 부분 충족15응답과 판정 근거. 평가자용 자료이며 모델 입력으로 전달하지 않는다.
- [프롬프트 후보 초안](../generation_evaluation/experiments/luna-prompt-improvement-20261015/candidate-drafts.md): 필수 안내 점검, 조건 연결, 출력 예시 정렬의 세 후보. 아직 런타임 프로필에 등록하지 않았다.

이번에는 설정·초안·검증 순서를 준비했으며 추가 API 호출, 성능 향상 확인, 새 미공개 세트 생성은 하지 않았다. 과거 2시간·5달러 실험 원장과 결과는 그대로 보존한다. 후속 실행 시작 시 적용할 예산·시간 범위를 먼저 확정하고 원장에 남긴다. 준비 작업이 과거 한도를 초기화하거나 새 유료 실행을 뜻하지 않는다.

## 다음 실험 순서

1. 입력과 판정 기준 확인: 같은 문서71건 snapshot과 기존 개발8문항을 사용한다. 문서가 추가·개정됐다면 별도 snapshot으로 분리하고 기준 응답부터 다시 실행한다. 모든 문항의 필수 주장에 질문 직접 요구인지, 결론을 바꾸는 조건인지, 부가 안내인지 표시하는 기준 개정안을 준비한다. 과거 점수는 바꾸지 않으며 새 기준은 호출 전에 버전으로 고정한다.
2. 기준 구성 재확인: 같은 실행 환경에서 baseline을 실행하여 기존 기록과 구분한다. 서버·문서 검색·모델·추론·출력 한도를 동시에 바꾸지 않는다.
3. C1부터 비교: 질문에 필요한 조건·담당 주체·기한·증빙 누락을 줄이는 짧은 점검 지시만 추가한다. 근거 없는 내용을 채우거나 무관한 절차를 늘리면 탈락시킨다. 효과가 없으면 C2를 독립 비교한다.
4. 형식 후보 C3: 합성 예시의 답변 형식을 계약과 맞추는 효과만 별도로 측정한다. 최신40응답은 이미 형식 성공이므로 형식 성공률만으로 개선을 주장하지 않는다. strict JSON Schema는 별도 코드 변경·검증 후보다.
5. 유망 후보 반복: 개발8문항 1회 비교 후 최선 후보만 두 번째 반복한다. 이미 열람한 두20문항은 회귀용으로 사용한다. 이를 새로운 독립 최종 성적으로 발표하지 않는다.
6. 새 최종 검증: 기존 개발·예시·두 선정 세트와 질문 그룹이 겹치지 않는 새20문항과 원문 판정 기준을 독립 검토하여 고정한다. 기준 구성과 최선 후보를 각각2회 비교하고 이름을 가린 판정·경계 재검토를 수행한다. 결과를 본 뒤 해당 평가를 유지한 채 후보를 수정하지 않는다.

## 성공·중단 판단

8개 차원과 실패 포함 분모는 유지한다. 우선 중대한 근거·권한 오류가 늘지 않아야 하며, 두 반복 모두 통과한 문항 수와 필수 안내 누락 응답 수를 함께 본다. 과잉 유보·무관한 절차·형식 실패·잘림도 별도 집계한다. 평균 점수 하나로 새 환각을 상쇄하지 않는다.

두 차례 연속 개선이 없거나 예산·시간이 부족하면 추가 후보를 멈춘다. 품질이 같으면 응답 시간·출력 길이·추론 토큰·비용이 적은 구성을 우선한다. 캐시 적중 차이를 비용 개선으로 단정하지 않는다. 프롬프트 개선 채택 여부와 모델 선택은 별개다. 후보가 모두 실패해도 선택 모델 GPT-6 Luna와 기존 기준 구성을 유지한다.

## 실행 진입점

기존 `python -m generation_evaluation.selection`을 사용한다. 먼저 `--help`로 인자를 확인할 수 있다. 아래는 **후속 실행 시 사용할 기준 후보 명령 템플릿**이며 이번에는 실행하지 않았다. `$LUNA_DOCUMENTS`는 검증한 snapshot, `$LUNA_LEDGER`는 후속 실행 범위를 명시한 원장, `$LUNA_OUTPUT`은 새 결과 경로, `$SANAEBI_ENV_FILE`은 로컬 인증 파일 경로다. 키를 명령이나 저장소에 적지 않는다.

```bash
uv run --locked --env-file "$SANAEBI_ENV_FILE" python -m generation_evaluation.selection \
  --candidates generation_evaluation/experiments/luna-prompt-improvement-20261015/baseline.json \
  --candidate gpt-luna-reference \
  --cases generation_evaluation/benchmarks/selection-20261015/dev.json \
  --documents "$LUNA_DOCUMENTS" --phase dev \
  --ledger "$LUNA_LEDGER" --output "$LUNA_OUTPUT"
```

실험 후보는 초안을 프로필에 등록하고 오프라인 검증한 뒤 별도 이름으로 추가한다. 같은 조건의 모든 후보는 같은 원장을 사용한다. 기존 완료 실행을 새 코드로 재개하지 않고 새 실험으로 기록하며, 과거 실행의 재개라면 당시 코드와 원장 식별자·예약 이력을 유지한다. 문서 해시·질문 그룹·프롬프트 해시·원응답·실패·시간·토큰·비용을 보존한다.
