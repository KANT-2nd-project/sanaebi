# 회사 문서 초기 더미 보관본

`ieum_works.jsonl`은 새 정책 데이터 제작 전의 52개 예시 문서다. 실제 회사 규정이나 외부 자료 기반 정책으로 취급하지 않는다. `eval_set_dev.jsonl`은 이 시점의 개발 평가 질문이며 내용과 행 순서를 보존했다.

기준 커밋은 `abdae72`다. 원본 바이트 해시는 다음과 같다.

```text
67f794812b53ca02300f2ece1e60b247202379d569a752ef8db38aa493b09949  data/archive/company-knowledge-v0/eval_set_dev.jsonl
9629a0075ae83d3b3d0c9443706a55c8adcf59166a166902349a47471a4d7b67  data/archive/company-knowledge-v0/ieum_works.jsonl
```

현재 자료는 [회사 정책 데이터 안내](../../company-knowledge/README.md)를 따른다. 과거 실험 결과는 이 문서로 재평가한 결과로 바꾸지 않는다.

보관 자료의 읽기·평가 정합성 확인:

```bash
uv run --locked python -m answer_pipeline.cli run --documents data/archive/company-knowledge-v0/ieum_works.jsonl --eval-set data/archive/company-knowledge-v0/eval_set_dev.jsonl --models answer_pipeline/examples/models.example.json --run-dir tmp/company-knowledge-legacy-dry-run --dry-run
```

이 명령은 현재 실행기에서 보관 입력을 대조하는 명령이다. 과거 소프트웨어 동작까지 재현하려면 당시 커밋과 실행 설정도 사용해야 한다.
