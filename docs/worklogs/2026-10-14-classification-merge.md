# 분류·API 연결 브랜치 merge 충돌 해결

시작 main: `1ccfc21`. 병합 대상: `add-fastapi+classific`의 `f0cf9e5`. 사용자가 충돌 해결·검증·커밋·푸시를 요청했고, `/ask` 실제 답변 연결 채택과 `/ask/langchain` 제거를 명시적으로 선택했다. AI가 충돌 통합과 회귀 검사를 수행했다.

## 해결 내용

- `app/services/question_service.py` 삭제 충돌: `dependencies.py`와 단위 테스트가 사용하는 `handle_question`·`QuestionResult`를 보존했다. 제거한 `/ask/langchain` 전용 `answer_question`과 예외는 삭제했다. 패키지 초기화 파일도 보존했다.
- `classification/test_jev.py` 삭제/수정 충돌: 이전 단일 파일을 복원하지 않고 상대의 예시 4개 교체를 현재 `models/jev_prompt.py`로 이식했다. 새 train의 대표 12개를 검증하며 과거 결과 JSON은 수정하지 않았다.
- 서비스·서버 규약 충돌: 현재 `/ask`→KoELECTRA Base→선택한 LangChain 모델 경로를 반영하고 기존 미연결 서비스 초안과 구분했다. 기존 문서 관리 API·저장 계약은 유지했다.
- API 테스트 충돌: 삭제된 `/ask/langchain`만 목록에서 제외하고 기존 `/documents` 경로와 격리된 임시 DB 설정을 보존했다.
- 자동 병합된 분할 변경은 StratifiedGroupKFold 20개 fold의 14/3/3 조합을 채택했다. 새 분할은 632/133/135건이며 과거 모델 평가는 저장된 ID로 복원한다. 학습/test 분리, 기본 validation 평가, 분할별 결과 저장은 유지했다.

## 충돌 표시 밖에서 확인한 문제

새 `/ask`가 전달하는 `provider`를 기존 `langchain_adapter`가 받지 않아 TypeError가 발생했다. 집중 테스트의 실패를 확인하고 선택 provider를 실행기까지 전달하도록 수정했다. provider 생략 시 기존 `/assistant`의 기본 호출 계약을 유지한다.

과거 `generate_answer`를 교체하던 진단 테스트는 새 연결 함수를 교체하도록 수정했다. 분류기·외부 모델은 테스트 대체 객체로 격리한다. 실패 결과를 `/ask`가 502로 바꾸면서 기존 expectedFailure 2개가 정상 통과하므로 해당 표시를 제거했다.

## 검증

- 전체 Python 테스트: 268개, 33.471초, `OK (skipped=1)`. 실 Ollama 호출 1개만 제외. 이후 진단 테스트의 예외 범위 축소는 해당 파일 전체 재검사로 확인한다.
- Ruff check·format check, diff 공백 검사 성공. 데이터 900건·라벨별 300건·392그룹·검수 연결 900건 검증 성공.
- 기존 small 결과의 저장된 ID 복원: 637/129/134건 유지 확인.
- 전체 검사에는 임시 TF-IDF 학습·재사용·분할별 평가, 새 분할 라벨 비율·그룹 비중복, Jev 예시 train 소속·268회 요청 계약이 포함된다.
- 원본 CSV·가중치·과거 실험 결과를 변경하지 않았다. 실제 Transformer 재학습, 외부 API 요청, 모델 품질 평가·최종 선정·브라우저 종단 검증은 수행하지 않았다.

## 문서와 남은 경계

README·서버/서비스·분류/데이터·문서 관리·프런트 안내에서 현재 API와 과거 echo 검증을 구분했다. 원격 게시 후 문서 안내·서비스 처리 기준·데이터 절차의 Notion 기술 요약을 동일 기준으로 갱신한다. 기존 업무 담당자·기한·상태는 변경하지 않는다.

현재 `/ask`는 기존 서버의 Base 모델 경로를 사용한다. 실험 저장소의 small을 자동 선정·배치하지 않는다. 문서 관리 SQLite 게시본은 LangChain 답변에 아직 연결되지 않았다. `/documents/capabilities`의 기존 `answer_integration="echo"` 필드는 유지되며 문서 공급 미연결 상태의 과거 표시로 문서에 명시했다. 목표 라벨 분기 정책과 실제 모델 답변 품질도 후속 과제다.

상세 로컬 로그: `tmp/merge-review-2026-10-14/`의 `before.patch`, `adapter-red.log`, `tests-final.log`, `debug-final.log`. 임시 로그는 공개 파일로 연결하지 않는다.
