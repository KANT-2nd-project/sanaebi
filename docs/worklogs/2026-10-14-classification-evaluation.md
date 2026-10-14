# 분류 학습·평가 구조 개선 작업 기록

작성일: 2026-10-14. 시작 커밋: `55b3519`. 사용자가 구조 개선 A~D와 validation 기본 평가를 승인하고 구현·검증·문서화 및 기능별 커밋·푸시를 요청했다. 코드 수정, 검사 실행과 이 기록 작성은 AI가 수행했다. 사용자 독립 구현·사람의 데이터 승인으로 기록하지 않는다.

## 변경과 목적

| 기능 | 커밋 | 결과 |
|---|---|---|
| 학습·평가 경계와 결과 관리 | `52d4105` | 학습 입력을 train/validation으로 한정하고 SelectionResult를 반환. 기본 eval은 validation만, 명시적 test는 test만 예측·측정. 분할별 결과와 model_id 연결, 과거 형식 읽기, 실패 복구를 유지 |
| small 길이 후보 | `e53e968` | KoELECTRA small만 길이 후보를 256 하나로 축소. 현재 900건의 해당 tokenizer 최대 길이 65 관측이 근거 |
| 실행 안내·문서·피드백 | 이 기록을 포함하는 문서 커밋 | 분류 README, 데이터의 과거 분할 설명, 서버 규약과 루트 안내를 정합화. 작성자 피드백을 별도 제공 |

현행 로컬 평가, 구형 형식, Jev 조립, 비교 수집과 HTML 렌더링을 구분했다. 기존 실험 진입점과 Jev 프롬프트·호출 계약을 유지했다. 보고서는 모델·데이터·분할·용도와 한계를 앞에, 상세 trial은 접힌 영역에 표시한다. preview는 모델 다운로드·학습·결과 저장 없이 실행 조건을 보여준다.

사용법과 읽는 순서는 [분류 코드 안내](../../archive/classification_v1/README.md), 개선 전후 비교와 전달용 요약은 [작성자 피드백](2026-10-14-classification-feedback.md)에서 관리한다.

## 실행한 검증

- 집중 실패 테스트로 기존 기본 평가가 test에 접근함을 먼저 확인한 뒤 구현했다.
- `uv run --locked python -m unittest discover -s tests -v`: 게시 전 재실행 266개, 27.735초, `OK (skipped=1, expected failures=2)`.
- 예상 실패는 기존 `test_final_answer_debug`의 `test_chain_errors_return_502`, `test_unusable_model_output_returns_502`다. 실 Ollama 호출 1개는 제외했다.
- `uv run --locked ruff check .`, `uv run --locked ruff format --check .`, `git diff --check` 성공.
- `uv run --locked python scripts/validate_dataset.py`: 900건, 라벨별 300건, 392그룹, 검수 연결 900건 검증 성공.
- 임시 저장소의 작은 TF-IDF로 학습 → 동일 조건 재사용 → validation → test를 실제 실행했다. 분할별 결과 공존과 생성 HTML 내부 링크를 확인했다.
- test 미접근, 명시적 test, 잘못된 split, 과거 결과 읽기, stale model_id 제외, checkpoint·동점·라벨 매핑, preview 무부작용, 저장 실패 복구를 검사했다. Transformer 계약은 작은 텐서·대체 모델로 확인했다.

상세 실행 로그와 진단 원본은 Git 제외 로컬 `tmp/classification-review-2026-10-14/`에 보존한다. `implementation/red.log`, `prepublish-tests.log`, `cli-html-check.json`, `preservation-and-links.json`은 해당 폴더 내 조사 자료이며 공개 링크로 연결하지 않는다.

## 보존 범위와 해석 한계

데이터·가중치·과거 결과·runs를 포함한 9,067개 파일의 전후 대조에서 누락은 없었고 변경은 허용한 `data/README.md`뿐이었다. 원본 CSV·기존 모델·과거 결과는 수정하지 않았다. 임시 조사 결과나 모델 바이너리를 이번 커밋에 추가하지 않는다.

현재 test는 이미 열람한 개발 평가다. 명시적 test 명령도 미열람 최종 평가를 뜻하지 않는다. 실제 Transformer 재학습, 정확도 향상 확인, 최종 모델 선정과 서버 연결은 수행하지 않았다. 기존 small의 짧은 질문 오분류와 합성 데이터 한계는 별도 품질 과제다. small 후보와 내부 학습 계약 변경으로 기존 train 재사용 조건이 달라질 수 있으나 자동 재학습하지 않는다.

## 문서·Notion 반영

`52d4105`, `e53e968`, `318fa18`을 origin/main에 푸시하고 원격 HEAD 일치를 확인했다. [문서 관리 가이드](../documentation-guide.md)의 프로젝트 문서 안내·서비스 처리 기준·데이터 작성·검수·실험 절차에서 분류 구역의 미게시 표시를 게시 커밋 링크로 갱신했다. 세 페이지 모두 저장 후 재조회하여 게시 상태·Git 링크·일지 연결을 확인했다. [Notion 작업 일지](https://www.notion.so/3f905a3cdadc81ffa919f141d5ec2dce)를 생성하고 사용자 결정과 AI 구현·검증, 이 범위의 완료 상태와 산출물 링크를 재확인했다. 기존 업무 담당자·기한·상태는 변경하지 않았다.

후속 순서는 경계 질문 사람 검수 → 데이터 보완 → 별도 실험 → 최종 모델 선정 → 서버 연결이다. 작성자 피드백은 별도 문서로 제공하며 직접 전송하지 않는다.
