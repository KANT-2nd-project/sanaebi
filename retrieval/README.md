# 문서 검색·임베딩 기록

RAG의 검색 모델 선정과 실험 근거를 관리한다. 서버 검색 코드는 `app/retrieval/`에서 관리한다. 분류 학습은 [classification](../classification/README.md), 답변 생성은 [generation](../generation/README.md)에서 관리한다.

- **선정:** KoEn-E5-Tiny. [16종 CPU 비교·채택 보고서](reports/2026-10-15-cpu-embedding-comparison/README.md)와 [모델 계약·후속 작업](reports/2026-10-15-cpu-embedding-comparison/selection.md).
- **연결 상태:** 서버 기본값은 rag+C다. 점수0.35 이상 근거를 개수·문자·별도 전달 토큰 제한 없이 전달한다. 운영 설정 변경·배포·사람 검수는 별도다.
- **기록 기준:** 결론·작은 비교표·검토 가능한 증거는 reports, 큰 벡터·가중치·가상환경은 로컬 원자료에 둔다. 실험 당시 관측과 이후 사용자 결정을 구분하며 기존 기록을 덮어쓰지 않는다.

전체 연결 정책은 [서비스 설계](../docs/service-architecture.md), 문서 게시·개정은 [문서 관리](../docs/document-management.md)를 따른다.

## 서버 검색 구현

[RAG 실행](../docs/rag-runtime.md)은 기본 rag와 명시적 full 복구를 제공하면서 로컬 Tiny·SQLite exact 검색과 자정 기본 벡터 복원을 연결한다. 모델 선정 결과와 실제 운영 품질은 구분한다. 런타임 코드는 app/retrieval, 과거 실험 기록은 이 폴더의 reports에 둔다.

[로컬 RAG 검증](reports/2026-10-15-rag-local-validation/README.md)은 검색 순위·최종 근거와 자정 복원을 구분해 기록한다.

[단계별 검색 개선 비교](reports/2026-10-15-rag-quality-improvement/README.md): 세 후보 구현·평가, 인접 확장 회귀 개선과 사전 채택 기준 미충족에 따른 기존 검색 유지.

[Full·RAG 실제 답변 비교](reports/2026-10-15-rag-answer-comparison/README.md): 5호출 후 JSON 계약 위반으로 중단, 미완료 항목·비용·두 AI 판정과 삭제/기본복원 연동 검증.

## 검색 인자·문맥 실험과 최종 결정

실험 당시 판단과 이후 사용자 채택을 구분한다. 검색 근거 포함률과 답변 품질을 합쳐 하나의 정확도로 표시하지 않는다.

| 기록 | 목적·결론 |
|---|---|
| [v3 평가 보완·검색 최적화](reports/2026-10-15-retrieval-v3/README.md) | 동등 근거 정정, 인접 확장·CPU 재정렬 비교, 신규 확인 손실에 따른 C 유지 |
| [최종 C 채택](reports/2026-10-15-c-adoption/README.md) | 사용자 선택, 현재 서버 설정·검증과 운영 미전환 |
| [근거 점수·개수](reports/2026-10-15-evidence-threshold/README.md) | 임계값과 최대 근거 수 비교 |
| [점수만 사용한 선택](reports/2026-10-15-evidence-score-only/README.md) | 최대 개수를 제외한 비교 |
| [정답 재검수·인자 보정](reports/2026-10-15-rag-calibration/README.md) | 정답v2·개발/확인·실제 답변 비교, 당시 판단 보존 |
| [A/B/C 문맥 비교](reports/2026-10-15-context-limits/README.md) | 검색48문항 및 실제 답변12문항, 제한 중단과 키 교체 후 완료 |

과거 비교 실행기는 `retrieval/experiments/`에 보관한다. 서버는 해당 실험 코드를 import하지 않는다.
