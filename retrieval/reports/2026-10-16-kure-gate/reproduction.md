# 재현 자료 접근과 실행

저장소 루트 기준이다. 저장소만 내려받으면 모델·벡터·준비 DB가 자동으로 생기지 않는다. 공개 다운로드 링크로 로컬 위치를 표현하지 않는다. 신규 확인40은 이미 사용했으므로 아래 명령은 재현 확인용이며 새 후보 튜닝용이 아니다.

## 실제 사용 자료

- 준비 artifact-root: `/home/jake/workspace/projects/.sanaebi-rag-answer-evaluation-20261015/tmp/answer-evaluation`
- Tiny 모델: `/home/jake/workspace/projects/.sanaebi-rag-answer-evaluation-20261015/tmp/tiny-model`
- KURE 모델: `/home/jake/.cache/huggingface/hub/models--nlpai-lab--KURE-v1/snapshots/8b418a58414668e75532ed045c22d9ca018ae2b2`
- pilot 벡터: `/home/jake/workspace/projects/sanaebi/tmp/kure-v3-pilot-2026-10-16`
- 이번 원본 출력: 격리 작업 공간의 `tmp/kure-gate/{development-tiny,development-kure,benchmark-kure,confirmation-tiny,confirmation-kure}`

각 출력의 source·vector_provenance가 DB·색인·벡터·pilot 질의 파일 SHA를 기록한다. DB는 임시 복사본만 읽었고 원본 전후 SHA를 대조했다. 파일럿 질의 벡터는 기존 문서 벡터 행의 청크 대응 검증에만 사용한다. 새 질문은 실제 모델로 인코딩한다.

## 명령 형식

아래 변수는 위 자료의 실제 위치로 지정한다. 결과 출력 폴더는 존재하면 거부한다. 모델 다운로드·LLM 호출은 실행기에 없다.

```bash
uv run --locked python -m retrieval.experiments.kure_evaluation \
  --phase development --model kure \
  --cases retrieval/reports/2026-10-16-kure-gate/development-cases.json \
  --output "$KURE_NEW_OUTPUT" \
  --artifact-root "$KURE_SOURCE_ARTIFACTS" \
  --model-path "$KURE_LOCAL_MODEL" \
  --pilot-root "$KURE_PILOT_ARTIFACTS"
```

Tiny 기준선은 `--model tiny`와 해당 모델·새 출력 경로를 지정한다. 개발 결과의 `rows`를 `retrieval.experiments.kure_gate.choose_threshold`에 전달한다. 개발 부적격이면 중지하며 확인을 열지 않는다. 적격이면 후보 하한·개발 결과 SHA·개발/확인 자료 SHA·revision·top_k20을 후보 파일로 동결한다.

확인은 위 명령의 `--phase confirmation`, `--cases .../confirmation-cases.json`, `--candidate-freeze .../candidate-freeze.json`을 지정한다. 이번 candidate 파일의 `development_results_path`는 당시 로컬 파일 위치이며 SHA와 함께 검사된다. 다른 환경에서 재현하려면 동일 개발 원자료를 배치하고 경로만 바꾼 **별도 재현용 후보 파일**을 만들어 변경 이유를 기록한다. 게시된 동결 파일은 수정하지 않는다.

CPU 측정은 개발 KURE 명령에 `--benchmark --candidate-freeze ...`를 추가한다. CPU2 affinity, 고정 기존48×3회, 동시1/2를 순차 실행한다. 입력 복사·모델 로딩·워밍업은 warm 지표에서 분리한다. 개별 지연 배열은 저장하지 않았으므로 이번 게시 자료에서 p95를 다시 계산할 수는 없고 계산 코드와 집계 출력을 확인할 수 있다.

## 원자료만 재집계

`*-{tiny,kure}.json.gz` 네 파일을 압축 해제해 위 이번 원본 출력별 `results.json`으로 배치하고, `benchmark.json`을 `tmp/kure-gate/benchmark-kure/results.json`에 둔다. `threshold-selection.json`은 보고서 위치를 읽는다. [집계 스크립트](summarize.py.txt)를 임시 `.py`로 복사한 뒤 `PYTHONPATH=. uv run --locked python <파일>`로 실행한다. 확인40의 누락·중복, 답변가능성 분모와 자원144회 완료를 검사한다. 출력은 보고서 위치를 사용하므로 검증용 checkout에서 실행한다.
