# 새 층화 분할 실험 결과 병합

병합 전 main은 `658a983`, 담당자 결과 커밋은 `8c12050`이다. 사용자는 새 train 632건으로 재학습한 결과라고 확인하고, 기존 결과를 별도 보관한 뒤 새 결과를 반영하는 방식을 선택했다. 이 확인은 사용자 진술이며 이번 작업에서 원본 가중치·학습 로그를 대조한 재현 검증은 아니다. Jev는 가중치 학습 없이 대표 예시를 사용하는 API 평가다.

## 해결

- `data/README.md`의 현재 분할 설명을 통합했다. 현재 코드 경로는 `classification/dataset.py`이며 새 수량 632/133/135건과 과거 모델의 ID 기반 복원, 기본 validation·명시적 test 평가 설명을 유지했다.
- 교체 전 `classification/result/` 추적 파일 18개를 [보관 폴더](../../archive/classification_v1/archive/results/before-stratified-2026-10-14/README.md)에 바이트 그대로 보존했다. 과거 비교 HTML과 개별 보고서의 내부 링크도 유지했다.
- 담당자가 제출한 새 개별 지표·보고서·Jev 예측은 유지했다. [결과 안내](../../archive/classification_v1/result/README.md)에 출처와 한계를 기록했다.
- 비교 화면은 현재 renderer로 validation 기준 재생성했다. 새 분할 6개 결과와 과거 분할의 roberta_base를 같은 표에서 비교하지 않고 과거 결과를 별도 링크로 제공한다.
- Jev 테스트는 새 보고서의 현재 프롬프트 일치와 보관된 과거 예시와의 차이를 각각 검사하도록 변경했다.

## 검증 범위

모든 결과의 기록된 ID로 분할을 복원하고 데이터 해시 일치를 확인했다. 보관 18개 파일의 바이트 일치와 새·과거 HTML의 로컬 링크를 확인했다. 모델 실행·재학습·최종 선정·서버 모델 교체는 수행하지 않았다. 새 구형 형식 보고서에는 model_id가 없어 기존 artifacts 모델과 자동 연결하지 않는다. test는 이미 열람한 개발 평가 자료다.

상세 로그는 Git 제외 `tmp/result-merge-2026-10-14/`에 보존한다. 원격에 추가된 `46117cd`는 별도 답변 평가 CSV 지원이며 이번 분류 수정과 파일이 겹치지 않아 함께 병합한다.

## 최종 통합 검사

분류 결과 merge `a0e05bd` 후 원격 변경을 `4f9417e`에서 충돌 없이 병합했다. 최종 전체 Python 테스트는 281개·33.307초, `OK (skipped=1)`이다. 실 Ollama 호출만 제외했다. Ruff check·format check(134파일), 데이터 검증, diff 공백 검사, 문서·HTML 링크 검사와 비교 표의 roberta_base 제외를 확인했다. 원본 데이터와 artifacts/runs 모델 파일은 수정하지 않았다.
