# v3 최소 변경·단계별 검증

2026-10-15 사용자 후속 요청으로 기존 v1에 출처 표시와 불필요한 추측 금지 규칙 두 개만 추가한다. v2의 새로운 예시·문서 진술 강제·타당성 검토 기능은 포함하지 않는다. [protocol.json](protocol.json)은 결과를 보기 전에 고정했다.

1. 이전 고정 자료의 G02(배포 실패), G11(출처), G04(롤백 정보 부족), DEV-FU-09(신고 필수 정보), DEV-FU-07(기존 JSON 실패), H02(표현 변경·기존 JSON 실패)를 v1/v3 각각2회 비교한다. 총24회다.
2. v3에서 JSON 실패가 생길 때만 동일 프롬프트의 strict 출력 후보로6개를 각각2회 실행한다. 형식과 내용은 별도로 판정한다.
3. 후보가 필수 정보를 모두 보존하고 ID 노출·근거 없는 단서·형식 오류가 없을 때만 기존 회귀12개를 각 프로필1회, 나머지 경계8개를 후보2회, 표현 변형4개를 후보2회로 확장한다.
4. 적격 후보만 실제 API2회·채팅 경로 확인 후 기본값 전환 대상으로 삼는다. 최대90회·추정5달러다. 의미 검토에서 부적격이면 후속 단계를 실행하지 않는다.

타당성 검토 기능의 G09는 이번 범위에서 제외한다고 호출 전에 정했다. 이미 본 문항을 재사용하는 회귀이며 독립 holdout이 아니다. 기존 필수·금지 주장과 근거는 [기존 신규 문항](../answer-grounding-20261015/cases.json), [표현 변형](../answer-grounding-20261015/holdout.json), [업무 회귀](../../benchmarks/luna-reference-followup-v1/dev.json)를 따른다. 평가 결과를 본 뒤 문구·자료·기준을 바꾸지 않는다.

저장소 루트에서 프로젝트 환경의 Python으로 실행한다. 키는 인자로 전달하지 않고 비공개 환경 파일 경로만 지정한다.

```bash
PYTHONPATH=. python generation_evaluation/experiments/answer-grounding-v3-20261015/run.py --stage focus --env-file /path/to/private.env --output tmp/answer-grounding-v3/runs
```

조건 충족 시에만 `--stage strict --mode strict_json_schema` 또는 `--stage broad --mode prompt_json`(선택된 형식이 strict면 해당 값)을 사용한다. 같은 출력 원장과 고정 manifest를 사용하고 코드·입력 변화나 예약된 요청의 중복 실행은 거절한다. 오류 응답을 자동 재시도하거나 보정하지 않는다. 원응답은 tmp, 공개 결과는 [보고서](../../reports/2026-10-15-answer-grounding-v3/README.md)에 둔다.
