# 최종 Luna 구성의 독립 생성·평가 반영

## 요청과 결정

사용자는 최종 선택한 examples_answer_scope_v1을 실제 generation/generation_evaluation에 연결하고, 실행 모델 목록은 GPT-6 Luna 하나로 정리하도록 요청했다. 설정 접미사로 별칭을 늘리지 않고 models.json의 단일 모델과 company-final-v1 프리셋으로 실행한다. 서버 연결·main 병합·추가 튜닝은 제외했다.

기준 커밋은 88d0f1a이며 생성 전용 feat/generation-evidence-20261015 작업 공간에서 수행했다. origin/main은 25d2904로 확인했고 main의 미커밋 변경을 수정하지 않았다.

## 구현

공통 프리셋 로더가 두 CLI의 설정을 검증한다. --model/--experiment는 생략 가능하며 최종 모델과 프로필을 사용한다. xhigh/4096/180초/prompt_json, temperature 생략이다. 기존 JSON 설정은 generation_evaluation/archive/pre-final-runtime-20261015에 원문 보관했다.

generate_from_documents와 run_case는 keyword-only prompt_profile을 받으며 기본값은 scope다. 기존 build_prompt와 모든 실험용 프로필 본문은 보존했다. config_from_dict를 generation.config로 옮기고 이전 reporting 가져오기 경로를 유지했다.

새 실행은 prompt_profile과 문서/프롬프트 해시를 기록한다. 구형 누락 profile은 None이며 현재값으로 소급하지 않는다. 요약은 모델 설정·프로필별로 분리하고 기존 group_by_config 인터페이스는 유지했다. 거절·잘림·오류·출력 파일 배타적 생성과 자동 재시도 없음은 유지했다.

문서는 명시적 snapshot 입력이다. 검증에서는 이미 내보낸 고정71문서를 로컬 기본 경로에 복사했고 DB를 조회하지 않았다. 문서 증가 시 재내보내기하며 문서 수를 코드에 고정하지 않았다.

## 검증과 실제 호출

설정 중심 변경에 비례 검증을 적용했으며 엄격한 TDD로 표현하지 않는다. 기존 기본값을 기대한 테스트 6건의 실패를 확인한 뒤 기대값을 갱신했다. 최종 프롬프트 원문 동일성, 두 CLI의 실제 메시지·설정 일치, temperature 생략, 과거 프로필 지정, 기록 복원·분리 집계와 잘못된 별칭 거부 테스트를 추가했다.

생성 unittest 249개, 저장소 전체 Ruff 검사와 형식 검사(263파일), git diff --check가 통과했다. 기존 실패를 제외하여 통과로 처리한 항목은 없다.

실제 호출은 승인한 총2회만 실행했다. 단일 생성 completed(14.04초), 배치1건 parse_error(7.02초)였다. 배치에서 JSON 대신 일반 문장이 반환됐고 원문·사용량을 보존하고 answer=None/종료1로 기록했다. 프롬프트와 모델 설정·문서 해시는 동일했다. 재시도·strict 대체·프롬프트 재수정은 하지 않았다.

추정 비용 합계 $0.02970825이며 기존 보수적 비용 함수 기준으로 실제 청구액이 아니다. [응답과 검증 자료](../../generation_evaluation/reports/2026-10-15-final-runtime/README.md)를 따른다. 실행 연결 확인과 응답 성공은 구분하며, 2회 모두 정상 응답이었다고 보고하지 않는다.

## 기여와 한계

사용자는 최종 구성과 반영 범위·실호출2회를 결정했다. AI가 이번 구현·테스트·실행·검토·문서화·게시를 수행했다. 사용자의 독립 구현 숙련도나 사람 품질 승인으로 기록하지 않는다.

프롬프트 튜닝은 종료 상태다. 과거 회귀 게이트와 알려진 필수 안내 누락을 보존한다. 이번 기본값 적용은 사용자 요청에 따른 독립 런타임 채택이며, 게이트 통과나 서비스 연결·품질 승인이 아니다.

Notion 반영 대상은 문서 안내 3f805a3cdadc81e1a70bfe82c89cebe7과 개인 일지 3f905a3cdadc8146a9bbedb690ab5ecf다. 게시 후 저장·재조회를 확인해 아래에 기록한다.
