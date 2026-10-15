# v5 / v6 답변 가독성 소규모 비교

이 고정 개발 비교는 기존 `examples_answer_scope_v5`와 가독성 규칙을 덧붙인 `examples_answer_scope_v6`를 같은 모델 설정과 게시 문서 snapshot으로 확인한다. 질문 8개를 프로필별 한 번 실행하므로 실제 생성 시도 상한은 16회다. 이미 본 질문은 `cases.json`에 표시했으며, 이 결과를 미열람 holdout·일반 정확도·반복 안정성으로 해석하지 않는다.

## 고정 자료와 기준

- `cases.json`에는 질문, 필수 주장, 금지 주장, 유형별 기대 서식, 출처 문서의 정확한 인용을 호출 전에 고정했다. 루브릭은 모델 입력에 포함하지 않는다.
- 실행 snapshot은 읽기 전용 SQLite 게시 snapshot을 `tmp/readability-v6-20261015/snapshot.json`에 저장한 것이다. 72개 문서, fingerprint `9d02a7ba77a340bea017e89ab43e25db62a8cdeef83b2a40c5bbfb203a8eddf7`, 파일 SHA-256 `1cb0891c174267a2ae7b450a9654e40309eaaab7656e8c2ca0cec2e71bd26e72`다. DB와 WAL의 파일 해시를 읽기 전후 확인했고 바뀌지 않았다. 회사 문서 원문이 들어 있으므로 snapshot은 `tmp/` 밖으로 복사하거나 커밋하지 않는다.
- 후보 이름을 가린 독립 AI 판정을 별도 기록으로 수행한다. 사람 검수로 표현하지 않는다. `pass / partial / fail / uncertain`을 사용하고, 불확실한 응답은 통과로 간주하지 않는다.
- 평가 축은 JSON 계약, 한국어 사용자 응답, 문서 근거·완전성, 조건·예외 보존, 지시된 서식의 적합성, 불필요한 서식 사용, 가독성이다.
- 모델은 `gpt-6-luna`, `xhigh`, 출력 한도 16,384, timeout 180초, `prompt_json`, temperature 미전달을 사용한다.

## 실행

먼저 외부 호출 없는 사전 점검으로 snapshot, 프로필, 설정, 호출 수, 예상 비용과 해시를 확인한다.

```bash
PYTHONPATH=. uv run --locked --env-file .env python \
  generation_evaluation/experiments/readability-v6-20261015/run.py \
  --snapshot tmp/readability-v6-20261015/snapshot.json \
  --output tmp/readability-v6-20261015/run-001 \
  --preflight-only
```

사전 독립 검토가 끝난 뒤 같은 명령에서 `--preflight-only`를 빼면 실험을 실행한다. 호출 순서는 각 질문 안에서 v5/v6 순서를 번갈아 배치하고, 전체 요청은 순차 실행한다. 기존 출력 폴더가 있으면 시작 전에 실패한다. 자동 재시도·재개는 없다. 시작 기록만 남은 슬롯은 결과 불확실로 보고 재호출하지 않는다. 실패도 16회 시도 상한과 평가 분모에 남는다. 실제 실행 후 `manifest.json`, `events.jsonl`, `responses.jsonl`, 각 후보의 system prompt를 보존한다.

가격 상한 추정은 OpenAI 공식 [API pricing](https://developers.openai.com/api/docs/pricing)을 기준으로 한다. Standard 장문맥 Luna의 일반 input은 $0.20/M이지만, 더 높은 cache-write input $0.25/M을 입력 상한 추정에 사용하고 output은 $0.75/M으로 계산한다. 캐시 할인은 적용하지 않는다. 입력 토큰 예약은 직렬화된 UTF-8 바이트 수와 512 토큰 여유분을 기준으로 한 보수적 추정이며 API 청구액이나 tokenizer의 엄밀한 상한은 아니다. 실제 usage가 없거나 일부만 있으면 해당 슬롯의 전체 예약액을 비용 상한으로 기록하고 0으로 처리하지 않는다.

`run.py`의 `--preflight-only`는 API client를 만들거나 요청하지 않고 검증·해시·예약 추정만 출력한다. 일반 실행은 지정된 16 슬롯 외 요청을 발행하지 않는다.
