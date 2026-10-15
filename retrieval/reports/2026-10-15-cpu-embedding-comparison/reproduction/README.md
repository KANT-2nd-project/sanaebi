# 실험 당시 스크립트 보존본

이 폴더는 실행한 스크립트를 원래 파일 그대로 보존한 자료다. 서비스 실행 코드·새 공통 평가 CLI가 아니다. 원본 스크립트는 `tmp/<단계 이름>/` 배치를 가정하므로 이 폴더에서 바로 실행하지 않는다.

- `e5-small-ko-v2-pilot-2026-10-15/`: 최초 질문·청크 구성과 E5 CPU 측정.
- `embedding-comparison-2026-10-15/`: 같은 청크로 BGE-M3·KURE-v1 비교와 검증.
- `embedding-broad-pilot-2026-10-15/`: 후보 공개 설정 조사·고정 catalog·순차 모델 실행·Potion 별도 실행·순위 검증·표 생성.

원래 실험 머신에서는 저장소 루트에서 다음 명령으로 신규 13종의 로컬 벡터·순위·지표를 모델 재호출 없이 검증할 수 있다.

```bash
uv run --locked python tmp/embedding-broad-pilot-2026-10-15/verify.py
```

다른 머신에는 로컬 벡터가 없으므로 이 명령을 바로 실행할 수 없다. Git만으로 가능한 검토는 `../cases.json`, `../chunks.json`, `../evidence/`, 비교 CSV를 대조하는 것이다. 전체 재실행을 원하면 별도 작업 사본에서 스크립트를 원래 tmp 경로에 배치하고, 질문·청크·최초 results와 단계별 결과·catalog를 해당 경로에 준비해야 한다. 원래 tmp 원자료를 덮어쓰지 않는다.

최초 E5·3종 비교 스크립트는 실행 당시 공개 revision을 조회했고, 확장 실험은 catalog에 기록한 revision을 사용했다. 같은 모델을 재현하려면 결과 JSON의 revision을 명시적으로 고정해야 한다. probe를 다시 실행하면 현재 공개 revision으로 catalog가 바뀔 수 있다. 그 재실행을 과거 실험의 동일 실행으로 표현하지 않는다.

Potion은 Python 3.12와 이 폴더의 `static-env/pyproject.toml`·`uv.lock`으로 별도 구성했다. 프로젝트 기본 의존성을 바꾸지 않았다. 가중치·벡터·콘솔 전체 로그는 Git에 포함하지 않았다. 이 보존본의 구조를 옮기거나 포맷을 바꾸면 과거 실행 스크립트와 같다고 주장할 수 없다.
