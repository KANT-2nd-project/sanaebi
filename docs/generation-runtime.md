# 생성 모델 실행 설정과 TPS 확인

독립 생성 CLI의 실행 설정 기준이다. 모델 선택과 답변 품질 승인은 [생성 평가 기준](generation-evaluation.md), 과거 실측은 [TPS·품질 일지](worklogs/2026-10-15-generation-tps-quality.md)에서 관리한다.

## 현재 기본 실행

최종 구성은 [최종 프롬프트 기준](generation-final-prompt.md)을 따른다. GPT-6 Luna 하나를 examples_answer_scope_v5 / single / xhigh / 16384 / 180초 / prompt_json으로 실행하며 temperature는 생략한다. 문서 snapshot 준비와 최소 명령은 [생성 모듈](../generation/README.md#독립-실행)을 따른다. --model과 --experiment를 생략해도 두 CLI에서 같은 기본값을 사용한다.

아래 Qwen·초기 GPT 비교는 역사 기록이다. 과거 별칭은 활성 models.json에서 제거했으며 당시 명령 재현에는 보관 설정과 당시 코드가 필요하다. 현재 Luna 명령에는 --experiment/--model을 생략한다.

## 로컬 Qwen 긴 문맥 프로필

검증 환경은 Ollama 0.33.3, RTX 5060 Laptop 8GB, Qwen3 4B Instruct 2507 Q4_K_M, 문맥 98,304, 동시 요청 1개다. 모델 파일 약2.5GB와 별개로 KV 캐시·계산 버퍼가 메모리를 사용한다.

`scripts/serve_generation_ollama.sh`는 loopback 11435에 별도 서버를 실행한다. Flash Attention, KV cache q4_0, 적재 모델 1개, backend fit 여유 256MiB를 지정한다. 기존 설치 모델을 재사용하고 자동 다운로드·prune을 하지 않는다. 설치 경로가 다르면 OLLAMA_MODELS로 지정한다.

```bash
bash scripts/serve_generation_ollama.sh
```

다른 터미널에서 호출한다. 서버와 호출 프로세스의 주소를 함께 지정해야 한다.

```bash
OLLAMA_HOST=http://127.0.0.1:11435 uv run --locked python -m generation \
  --experiment company-full-context-v1 --model qwen3-4b-q4km-96k \
  --question "영수증을 분실했을 때 어떻게 정산하나요?"
```

실험 종료 후 본인이 적재한 모델을 내리고 서버 터미널에서 Ctrl-C로 종료한다. 다른 모델 작업의 GPU 사용량은 건드리지 않는다.

```bash
OLLAMA_HOST=http://127.0.0.1:11435 ollama stop qwen3:4b-instruct-2507-q4_K_M
```

## 확인할 값과 적용 범위

- 실제 backend 로그의 `flash_attn`, K/V dtype, `offloaded 37/37 layers`를 확인한다. 설정값이 전달됐다는 사실만으로 적용됐다고 판단하지 않는다.
- `LLAMA_ARG_FIT_TARGET`은 설치 backend 옵션이다. 버전·하드웨어·동시 GPU 작업이 달라지면 다시 검증한다. 이번에 num_batch128 요청은 실제512로 실행되어 채택하지 않았다.
- 가중치 Q4_K_M과 KV cache q4_0는 별개의 양자화다. 캐시 압축도 답변 품질에 영향을 줄 수 있다. [Ollama 공식 설명](https://docs.ollama.com/faq#how-can-i-set-the-quantization-type-for-the-kv-cache)을 따른다.
- 모델을 내린 뒤 첫 호출과 동일 입력의 cache 재사용을 분리한다. 순수 생성TPS는 `eval_count / (eval_duration / 1e9)`, 전체 요청TPS는 출력토큰/전체시간이다. 서로 다른 지표로 개선 배수를 계산하지 않는다.

2026-10-15 고정 입력의 F16/Q4 비교에서 순수 생성TPS 약1.2~1.3→18.5, GPU14/37→37/37층을 관측했다. 첫 호출은 약254→87초, 동일 요청 반복은107→7.15초였다. 첫 입력 처리 약77초가 남으므로 모든 요청의7초 응답을 보장하지 않는다. 이 수치의 원자료·표본 한계는 일지에 보존한다.

## 문서 증가

문서 수를71건으로 제한하지 않는다. 새로운 문서는 새 snapshot/개정/hash로 보존하고 질문·system·출력 예약을 포함해 입력 예산을 다시 검사한다. 기존 최대입력67,692+출력예약1,024 기준96k 여유는29,588토큰이지만 미래 문서 수용량이나 지연을 보장하지 않는다. 자동 사전 토큰 검사는 아직 없다. 문서를 자동 절단하지 않는다.

## OpenAI GPT-6 Luna 비교 프로필

별칭 `gpt-6-luna`는 같은 실제 모델 ID를 사용한다. 비교 초기 설정은 Chat Completions, reasoning_effort=none, temperature=0, 출력 한도1,024, timeout180초다. Qwen 비추론 모델과 우선 비교하기 위한 조건이며 GPT의 모든 추론 설정을 대표하지 않는다. reasoning을 활성화하는 별도 실험에서는 temperature를 함께 보내지 않는다. [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-6-luna) · [매개변수 지침](https://developers.openai.com/api/docs/guides/latest-model).

OpenAI의 문맥 크기는 모델이 정하며 Ollama의 num_ctx처럼 요청하지 않는다. context_window는 비워두고 max_output_tokens를 max_completion_tokens로 전달한다. API 키는 로컬 `.env`의 OPENAI_API_KEY 또는 호출 프로세스 환경에 둔다. 실제 키를 저장소나 실행 보고서에 넣지 않는다.

```bash
uv run --locked --env-file .env python -m generation \
  --experiment company-openai-comparison-v1 --model gpt-6-luna \
  --question "은행 계좌가 바뀌었는데 다음 급여 전에 반영되려면 언제까지 어느 메뉴에서 수정해야 해요?"
```

비교 실험은 같은 문서·질문·system/user 해시를 확인한다. 출력 형식 강제 옵션은 추가하지 않고 기존 prompt의 JSON 계약으로 비교한다. API 인증 성공, 실제 응답 성공, 답변 품질 판정은 별도 상태다. 최신 진행과 결과는 [GPT 비교 일지](worklogs/2026-10-15-generation-openai-comparison.md)를 따른다.

## 서버의 선택적 RAG 입력

서버의 rag 모드는 선택한 발췌 근거를 기존 생성 서비스에 전달한다. Luna·실행 프롬프트·출력 검사·예산 예약은 같은 경로를 사용한다. [RAG 준비 안내](rag-runtime.md)를 참고한다. 이번 검색 연결은 프롬프트 튜닝이나 생성 품질 승인으로 기록하지 않는다.
