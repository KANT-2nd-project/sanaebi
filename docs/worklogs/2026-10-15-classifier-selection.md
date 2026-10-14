# KoELECTRA base 선정과 서버 연결 안내 — 2026-10-15

## 결정과 근거

사용자가 [7종 비교 결과](../../classification/reports/2026-10-15-seven-model-comparison/README.md)를 바탕으로 KoELECTRA base를 현 단계 서버 분류기로 채택했다. 개발 test는 BERT base와 공동 최고인 133/135 정답이며 동일 CPU 측정에서 17.91ms로 BERT base의 20.20ms보다 짧았다. validation 최고는 RoBERTa base다. 합성·이미 열람한 개발 test에 기반한 선택이며 미열람 최종 평가나 실서비스 성능을 입증하지 않는다.

사용자는 선정과 기록을 요청했고 AI는 근거·저장 메타데이터·서버 코드를 확인하고 문서를 정리했다. 이번 작업은 연결 방법 안내이며 서버 코드·가중치를 수정하거나 실제 API를 호출하지 않았다.

## 선정한 모델

- 로컬 경로: `artifacts/experiments/learning-comparison-2026-10-15/koelectra_base/model/`
- model_id: `9f51682d82d4455d8296077c339afd58`
- 기반 모델: `monologg/koelectra-base-v3-discriminator`
- 최대 길이: `metadata.json`의 `config.max_length` = 256
- 가중치·tokenizer·config·metadata가 함께 존재하는 것을 확인했다. 이 경로는 로컬 자료이며 Git 다운로드 경로가 아니다.

## 현재 코드와 연결 순서

1. [분류 어댑터](../../app/koelectra_classifier.py)의 `MODEL_PATH`를 위 저장본 경로로 연결한다. 현재 값인 `classification/model/koelectra_base`는 존재하지 않는다. 원본 실험 가중치를 이동·덮어쓰지 않는다.
2. `load_model()`은 지금 `training_summary.json`의 `max_length`를 읽는다. 새 저장본은 해당 파일이 없으므로 `metadata.json`의 `config.max_length`를 읽도록 바꾼다. model_id와 config의 라벨 매핑이 선정본과 일치하는지 검사한다. 세 라벨은 SEARCH_KNOWLEDGE·CLARIFY·UNSUPPORTED다.
3. `local_files_only=True`, `model.eval()`, `torch.inference_mode()`와 로딩 캐시는 유지한다. 학습 모듈을 서버로 가져올 필요는 없다. 모델 교체 후 서버를 재시작해 캐시된 예전 모델을 제거한다.
4. 저장 예측 JSON의 validation 133문항과 서버 어댑터의 예측을 대조한다. 서버 tokenizer 설정·최대 길이·라벨 매핑이 학습 평가와 같은지 확인한다. 이것은 새 성능 평가가 아니라 연결 회귀 검사다.
5. [분류 전용 라우터](../../app/routers/classification.py)의 `POST /classify/koelectra-base`로 세 라벨별 입력과 422·모델 부재 503을 확인한다. 실제 질문 결과는 실행 전 정답으로 단정하지 않는다.
6. [질문 라우터](../../app/routers/questions.py)의 `/ask`는 이미 같은 `classify_question`을 호출하므로 분류기 연결을 새로 만들 필요가 없다. 분류 결과 전달은 생성기를 모의 처리해 먼저 검증하고, 이후 문서 저장소와 생성 모델을 준비한 상태에서 종단 호출을 별도로 확인한다.

## 완료 기준

선정본 식별·저장 예측 일치·라벨별 API 응답·실패 처리 검증을 마친 뒤에만 분류기 연결 완료로 기록한다. 현재 상태는 **모델 채택 완료 / 선정 checkpoint 서버 연결 미완료**다. 기존 실험 일지의 당시 선정 보류 기록은 역사로 보존하고 후속 결정으로 연결한다.
