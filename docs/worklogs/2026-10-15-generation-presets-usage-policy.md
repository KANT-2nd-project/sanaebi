# 생성 설정·사용량·실행 한계 학습 기록

- 날짜: 2026-10-15
- 범위: 독립 generation / generation_evaluation. 서버 연결과 기존 실행기 아카이브는 후속이다.
- 설계 기준: 로컬 `tmp/langchain-generation-review-2026-10-14/03-architecture-decision.md`, `04-evaluation-plan.md`. 공개된 현재 계약은 [생성 모듈](../../generation/README.md)과 [평가 모듈](../../generation_evaluation/README.md)을 따른다.

## 바꾸게 된 계기와 구현

사용자는 CLI에서 매번 긴 모델 이름·provider·문맥 한도·출력 한도·문서 경로를 입력하기보다 모델별 설정을 고정하고 별칭으로 실행하기를 원했다. models.json과 experiments.json으로 설정을 분리하고 qwen3-4b-q4km 별칭과 company-smoke-v1 실험을 구성했다. 설정 파일은 입력 파일을 배포하거나 실제 모델 가용성을 보장하지 않는다.

문서 한 건의 실제 실행을 시작하면서 문자열 답변만으로는 출력이 잘렸는지, 어느 정도의 토큰이 사용됐는지 알 수 없었다. ModelResponse로 원문·사용량·종료 사유를 전달하고 GenerationResult 및 저장 기록에 보존하도록 확장했다. length 종료는 JSON 파싱 전에 TRUNCATED로 판정한다. CLI도 평가와 같은 run_case를 사용해 시간·오류·설정을 함께 출력한다. 사용량 누락은 None이며 0으로 꾸미지 않는다.

업무 처리 요청 사례에서는 이미 신청을 대신할 수 없다고 답했다. 다만 “개인적인 업무를 대신해 수행할 수 없다”는 모델의 자발적 표현에 의존했다. 현재 사내비가 제공 문서 기반 안내만 수행한다는 경계를 고정하기 위해 신청·변경·취소·승인·개인별 상태 조회를 수행하지 않는다는 시스템 규칙과 허위 완료·허위 조회 금지를 추가했다. 이는 실제 허위 완료 실패를 재현해 고친 사례가 아니다.

사용자가 단계별 구현과 실제 Ollama 실행을 진행했고, AI는 코드·저장 결과 검토, 회귀 테스트와 문서 정리를 담당했다. 마지막 프롬프트 편집에서 기존 자료 부족 안내가 빠진 것을 발견해, 먼저 실패하는 테스트로 확인한 뒤 해당 문장을 복원했다. 새 실행 한계 규칙은 유지했다.

## 저장 결과에서 확인한 사실

아래는 변경 전 프롬프트로 사용자가 실행한 로컬 기록이다. 문서 한 건(ieum-001, 연차 사용 신청)을 사용했다. 원문·전체 문서 파일은 tmp에 보존하고 커밋하지 않는다.

| 로컬 파일 | 관측 | 입력/출력 토큰 | 시간 |
|---|---|---|---|
| tmp/generation-smoke-result.json | 예정 연차를 3영업일 전 이음 포털 인사 > 휴가에서 신청한다고 안내 | 기록 없음 | 기록 없음 |
| tmp/generation-smoke-usage-result.json | 같은 명시 사실 안내, completed / stop | 1081 / 44 | 기록 없음 |
| tmp/generation-smoke-insufficient-run.json | 개인 잔여 연차 일수를 만들어내지 않고 확인 경로 안내, completed / stop | 1081 / 58 | 2.701966311초 |
| tmp/generation-smoke-action-run.json | 실제 신청·신청 완료를 주장하지 않고 포털 경로 안내, completed / stop | 1084 / 122 | 5.204884105초 |

파일 SHA-256은 다음과 같다. 공개 저장소에서 원문을 재현할 수 있다는 의미는 아니다.

```text
generation-smoke-result.json 1774a7d04cdf0371a4de669a675f7cedb2c8d8ae8f8d13cb8337a577fac7e826
generation-smoke-usage-result.json bed305a39c6da81f59e2bc5cadeecb0d8b36fd190419cde64933afe9c649ec0e
generation-smoke-insufficient-run.json ed3c8999bbc5eaccfc0e6e24c765ef468ed66966f6d7ec05c2c16b9a96210fea
generation-smoke-action-run.json da036e2ee5125d1278271c803af9a767e02c3deb4db269dd396e1008b331824f
```

이 결과는 소수 사례의 AI 검토다. COMPLETED는 JSON 구조 성공이며 정답률·사람 승인·전체 문서 품질을 뜻하지 않는다. 변경 후 프롬프트의 실제 재실행은 아직 확인하지 않았다. 과거 전체 71건 입력은 한도를 초과했으며, 문맥 설정과 호출 후 사용량만으로 입력 누락이나 사전 예산 문제가 해결되지는 않는다.

## 검증

- 생성 관련 unittest 125개 통과.
- 전체 unittest 417개 실행, 1개 skip, 나머지 통과.
- 생성/평가 코드 및 생성 테스트 범위 Ruff check 통과.
- 전체 Ruff format --check: 183개 파일 통과.
- 전체 Ruff check: 별도 학습 작업 classification/tfidf.py의 RUF059·F841 2건 남음. 이번 범위에서 수정하지 않았다.
- 프롬프트 단위 테스트는 규칙이 전달되는지만 확인하며 실제 모델 준수를 증명하지 않는다.

## 다음 구현·검증

우선 동일한 업무 처리 요청을 새 프롬프트로 실행해 별도 파일에 저장하고 이전 기록과 비교한다. 이후 실행 기록에 문서·프롬프트 식별 정보를 남기고 입력 예산, 구조화 출력·인용 및 품질 평가로 진행한다. CLI의 experiment/model_alias/question은 현재 GenerationRun 복원 시 유지되지 않는다. 문서 로드·클라이언트 생성 실패는 run_case 이전이라 실행 기록으로 포착되지 않는다. 서버 연결·패키지 배포·기존 코드 아카이브는 아직 진행하지 않았다.
## 게시와 문서 동기화 확인

기존 미게시 생성 커밋 5개와 아래 기능별 커밋을 main에 푸시했다. 82a8c5140d9c09d26d498a810cb8e854df0198a5에서 로컬 HEAD와 실제 원격 main 일치를 확인했다.

- ac2f68b: 모델 별칭·실험 프리셋과 설정 검증.
- a9e3208: 사용량·종료 사유·길이 제한과 CLI 평가 기록.
- 802a1f6: 자료 부족·실행 한계 프롬프트와 회귀 검사.
- 82a8c51: 현재 계약·실행 근거·변경 계기 문서.

[Notion 문서](https://app.notion.com/p/3f805a3cdadc81e1a70bfe82c89cebe7), [서비스 설계](https://app.notion.com/p/3f805a3cdadc81d7b909fc71ed78381b), [개인 작업 일지](https://app.notion.com/p/3f905a3cdadc8146a9bbedb690ab5ecf)의 새 내용과 게시 링크를 재조회했다. 이전 CLI 기록은 과거 기록으로 표시했고, 개인일지에는 변경 계기·역할·검증·다음 단계와 10월 14~15일 기간을 반영했다. 날짜 종료만 보낸 첫 속성 갱신은 거부되어 미반영을 재조회한 뒤 시작·종료를 함께 보내 복구했고 저장을 확인했다. 전체 학습 상태는 진행 중이다.

변경 문서의 상대 링크 48개를 확인했다. 별도 분류 모듈·데이터·루트 README·의존성 변경은 스테이징하지 않았고 tmp의 원본 실행 기록도 게시하지 않았다.
