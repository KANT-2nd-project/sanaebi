# 분류 직접 구현·7종 비교 실험 게시

## 범위와 기여

기존 분류 구현·과거 결과를 `archive/classification_v1/`에 보존하고, `classification/`에 데이터 준비·TF-IDF·Transformer 학습·저장·명시적 평가를 구성했다. 사용자는 직접 구현 학습의 범위와 방향을 정하고 CSV·검증·그룹 분할 등을 AI 안내를 받아 작성했다. 후보 선택·저장·평가·Transformer 완성과 실제 실험·검증·게시는 사용자 요청으로 AI가 수행했다. 이를 사용자 독립 구현·숙달이나 사람 검수로 기록하지 않는다.

생성 모델·생성 평가 등 다른 작업의 변경은 이번 커밋에 포함하지 않는다. `docs/documentation-guide.md`의 생성 모델 실행 안내 행도 작업 트리에 보존하고 분류 관련 변경만 게시한다. `.env`, 모델 가중치, MLflow DB, 실행 원자료와 tmp 자료는 Git에 추가하지 않는다.

## 구현과 호환

- 기존 `sanaebi`와 `sanaebi-train`은 아카이브 구현으로 연결한다. 기존 회귀 테스트의 import·저장소 기준 경로를 조정했다.
- 새 TF-IDF는 train 어휘 학습과 validation C 선택, 새 Transformer는 train 배치·epoch 학습과 validation 최고 checkpoint 복사·복원을 수행한다. 동점은 먼저 선택한 상태를 유지한다.
- 새 학습 함수는 train/validation만 받는다. 저장 모델 평가는 기본 validation, 명시적 `--split test`만 test를 예측한다. 새 폴더 저장·임시 저장·재로딩 예측 확인과 기존 결과 보존을 유지한다.
- 새 로컬 구현에는 MLflow가 아직 없다. Jev는 보존된 기존 실행 코드를 사용하므로 MLflow에 기록했다. 새 저장 형식과 기존 아카이브 형식은 구분한다.
- 과거 결과 JSON·CSV·HTML 38개를 게시 전 HEAD와 대조해 바이트 동일성을 확인했다. 데이터와 기존 가중치·과거 실험 원자료를 이동·재생성하지 않았다.

## 실험과 판단

[7종 통합 보고서](../../classification/reports/2026-10-15-seven-model-comparison/README.md), [로컬 6종 상세](../../classification/reports/2026-10-15-learning-model-comparison/README.md), [Jev 상세](../../classification/reports/2026-10-15-jev-evaluation/README.md)가 수치와 해석의 기준이다.

같은 문항 집합 train 632 / validation 133 / test 135를 사용했다. Transformer는 학습률 2개·후보당 3 epoch·길이256·batch4이며 최적 성능 전체 탐색이 아니다. 중단 전에 완료한 모델은 재사용하고 KoELECTRA base만 재시작했다. Jev는 268회 실제 요청 후 응답을 재사용했다.

이번 validation 최고는 RoBERTa base이며 개발 test에서는 BERT base·KoELECTRA base가 각각 133/135 정답이다. 모든 자료는 합성이고 test는 이미 열람한 개발 자료다. 최종 서비스 모델 선정·서버 교체·실서비스 검증은 하지 않았다.

14개 평가의 1,876개 예측에서 문항 ID·정답·정확도·Macro-F1·혼동행렬을 대조했다. 저장 모델과 선택 validation 점수·model_id·분할을 확인했다. Jev의 268개 성공 응답·input_tokens·MLflow FINISHED를 확인했다. 로컬 CPU 추론은 같은 4스레드·batch1·validation 조건으로 측정했다.

## 게시와 외부 반영

기능별 커밋은 아카이브/데이터 학습 공간 → TF-IDF·저장·평가 → Transformer → 보고서·문서 순서로 구분한다. 원격 게시 후 Notion 문서 안내·서비스 처리 기준·데이터 절차·운영 규칙의 분류 구역을 갱신하고, 개인 작업 일지에 사용자 결정·AI 수행·한계·다음 작업을 구분한다. 기존 과거 일지와 다른 업무의 담당자·기한·상태는 변경하지 않는다.

### 최종 확인

- 현재 작업 트리: 전체 Python 테스트 451개 성공(1개 skip), Ruff check·format check 성공(198개 파일).
- 커밋된 코드만 분리한 체크아웃: 427개 중 1개 실패(1개 skip). `test_unparsable_reply_is_format_failure_not_call_error`가 로컬 문서 저장소 부재로 `DocumentStorageError`를 반환했다. 변경 전 `608f86d`의 별도 체크아웃에서도 같은 실패를 재현했다. 이번 분류 변경의 회귀로 판단하지 않으며, 깨끗한 체크아웃 전체 테스트 통과로 보고하지 않는다.
- `git diff --check` 및 분류 전용 커밋 범위를 확인했다. 코드·보고서는 `76a9723`(아카이브·데이터), `19e6471`(TF-IDF·저장·평가), `5525264`(Transformer), `fdbde0c`(보고서·문서)로 main에 푸시했다. GitHub API에서 게시된 통합 보고서 링크를 확인했다.
- Notion [문서 안내](https://www.notion.so/3f805a3cdadc81e1a70bfe82c89cebe7), [서비스 처리 기준](https://www.notion.so/3f805a3cdadc81d7b909fc71ed78381b), [데이터 절차](https://www.notion.so/3f805a3cdadc81d59dc9fec6e4fcca1d), [운영 규칙](https://www.notion.so/3f805a3cdadc81aa9f48d8445d372b80)에 현재 구현·결과·한계·게시된 Git 링크를 반영한 뒤 재조회했다. 이전 실험 수치는 과거 기록으로 보존했다.
- [새 개인 일지](https://www.notion.so/3f905a3cdadc81a19d1bfa4ea41c9e98)를 최재선·분류/데이터·2026-10-15로 생성했다. 사용자 기여와 AI 수행을 구분했고, 원격 게시와 4개 기술 문서 반영을 확인한 뒤 이 일지만 완료로 표시하고 재조회했다.
- 기존 모델·데이터·과거 결과와 다른 생성 작업 변경은 보존했다. 생성 작업 및 문서 관리 가이드의 생성 실행 안내 행은 미커밋 상태로 남겼다.
