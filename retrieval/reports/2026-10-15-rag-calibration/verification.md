# 로컬 검증 기록

## 최종 검사

실제 실행 종료 뒤 누적 계획 수의 표시 반환값만 수정하고 다음 검사를 다시 실행했다. 원응답·비용·동결 정답·원장 값은 바꾸지 않았다.

| 검사 | 결과 | 로그 |
|---|---|---|
| `uv run --locked python -m unittest discover -s tests -t .` | 859개 통과 | [unittest](evidence/final-after-metadata-unittest.log) |
| `uv run --locked ruff check .` | 통과 | [Ruff](evidence/final-after-metadata-ruff-check.log) |
| `uv run --locked ruff format --check .` | 통과 | [format](evidence/final-after-metadata-ruff-format.log) |
| `git diff --check` | 통과 | [diff](evidence/final-after-metadata-diffcheck.log) |

신규 untracked 파일은 git diff만으로 검사되지 않으므로 JSON 구문, 로컬 Markdown 링크, 표 열 수·코드 펜스, 끝 공백·최종 개행을 별도로 확인했다. 브라우저 Markdown 렌더링은 수행하지 않았다. 기존 단계의 중간 로그는 삭제하지 않았다. 초기 `unittest discover -s tests`는 테스트 패키지 경로가 잘못 잡혀 import 오류가 났고, `-t .`를 명시한 위 정식 실행으로 검증했다.

집중 테스트에는 AND/OR span 판정, 미판정 null, 전달 전체 예산, confirmation qrel 선택, 재시도 상한·원장 실패·중복 실행 차단·실패 원응답 보존, 끝까지 JSON이 실패한 판정 packet, 실패 후 집계와 확정429 비용 처리가 포함된다. 독립 코드 검토에서 발견한 경계 오류를 수정한 뒤 재검토했다.

## 실제 Tiny와 격리 API

[실제 Tiny 검증](evidence/actual-tiny-readiness.json)과 [삭제·복원 API](evidence/api-clear-restore.json)에 수치와 명령을 남겼다. 생성기는 모의 구현이었다. 현재 개정만 전달, 삭제 후 문서·생성 예약0, 복원 후 색인 미준비503·예약0, 준비 후 HTTP200을 확인했다. 자정 복원과 mapping 복구는 존재하지 않는 모델 경로에서도71개 문서가 준비돼 모델 로딩·추론0회를 확인했다. 원본 DB 쓰기 syscall을 전부 계측한 것은 아니며 SHA·크기 보존과 회귀 테스트를 함께 사용했다.

## 개발 PC CPU2 측정

[CPU 측정](evidence/cpu2-benchmark.json): Intel Core Ultra9 275HX/WSL2, affinity2, torch intra-op1.

- 새 프로세스 모델 로딩2.759초, 첫 query2.473초.
- warm10회 p50/p95:43.648/45.633ms.
- 동시2 요청10개 p50/p95:80.040/97.136ms.
- peak RSS1,020,140KiB(약996MiB).

실제 운영2vCPU·Docker 성능이 아니다. OS page cache를 비우지 않았다. 이 CPU 측정은 기존 runtime 경로이며 실험 후보를 서버에 적용한 부하 시험이 아니다. 실험 후보의 예산 계산 비용은 [단계별 검색 지연](evidence/search-stage-latency.json)에 따로 있다. 4k 예산 계산의 선택 단계 p50은 약40.94ms, 기준선0.135ms였으므로 해당 실험 코드를 그대로 운영 기본 경로로 승격하지 않는다.

## 보존·평가 한계

[보존 검사](evidence/final-preservation-check.log), [독립 검토](review-and-limitations.md), [정오표](qrel-errata.md)를 함께 본다. 실제 답변 비교의 모드별 결과를 사람 검수나 서비스 품질 승인으로 표현하지 않는다. 운영 접속, 배포, 커밋·푸시·Notion은 수행하지 않았다.

새 보고서·코드·테스트의 JSON·압축 입력·로컬 링크·표·공백과 제한된 credential 패턴 검사 결과는 [산출물 검사](evidence/final-artifact-check.json)에 있다. 성공 시 출력이 없는 빈 diff 로그는 정상으로 처리했으며 내용을 임의로 추가하지 않았다.
