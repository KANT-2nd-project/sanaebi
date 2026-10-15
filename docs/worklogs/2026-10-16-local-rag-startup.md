# 로컬 RAG 준비 통합과 배포 확인

사용자는 README 준비부터 `npm run dev`, 문서 전체 삭제·기본 복원까지 일관되게 동작하고, 수정·푸시 후 CI/CD의 실제 원격 정상 확인까지 완료하도록 요청했다. 범위 결정은 사용자, 구현·자동 검증·독립 코드 검토는 AI가 수행했다.

## 문제와 변경

기존 README의 문서 이관은 검색 색인·기본 복원 묶음을 준비하지 않았고, dev는 worker를 실행하지 않았다. 묶음 환경변수가 없으면 기본 복원은 저장 전에503으로 종료했다. 빈 DB에서는 검색할 문서가 없어 health가200이어도 복원은 불가능했다.

- `setup:local`: 고정 모델·tokenizer·기본 벡터·현재 게시 색인을 명시적으로 준비한다. 기존 문서와 의도적 빈 DB를 보존한다. 새 DB는 임시 이관·검증 후 덮어쓰기 없는 게시로 실패 재실행을 지원한다.
- `check:local`: 읽기 전용 준비 진단. 명시적 환경변수를 우선하고 같은 `.env`를 준비·API·worker에서 사용한다.
- `dev`: 준비 확인 후 API·웹·worker를 실행하며 이번 실행의 프로세스 그룹을 종료한다. full에는 worker가 없다.
- 기본 묶음은 현재 원본 SHA/spec의 결정적 경로로 찾는다. rag readiness는 현재 색인과 복원 묶음을 함께 검증한다.

이 작업은 KURE revision·질문 게이트·상위20·생성 모델/프로필·공개 응답 형식을 변경하지 않았다. 첫 PR CI 도중 main에 별도 advisory 채택 작업(`9fb0d35`)이 게시되어 보존·통합했다. 분류 기본 정책은 해당 작업의 advisory 결정을 따르며, 로컬 준비 변경이 이를 shadow로 되돌리지 않는다. 과거 실험과 실제 사용자 DB를 보존했다.

## 로컬 검증

- 기본 묶음 미설정, 빈 DB에서 묶음 유실을 먼저 실패하는 테스트로 확인한 뒤 수정했다.
- 실제 KURE·격리 DB: 초기 준비·재실행 → 질문200 → 71개 삭제 → 자료 없음 안내200 → 기본 복원71개 → 질문200. 생성기는 모의 구현, 유료 호출0. 복원 문서 임베딩0, 실제 사용자 DB SHA 불변.
- 사용자 환경 `npm run setup:local` 성공, 기존 빈 DB0건 유지. 웹 프록시의 복원 preview200을 읽기 전용으로 확인했다.
- 독립 검토의 신규 DB 실패 재실행·baseline 원본 이중 읽기 지적을 수정하고 재검토에서 추가 중대 결함 없음. 실제 대체 자식·손자 프로세스로 종료와 무관한 프로세스 보존을 검사했다.
- 최신 advisory 통합본 전체 Python992개(76.647초), Ruff check·format573파일, 통합 변경 문서 상대 링크·앵커324개와 diff 검사를 통과했다.
- 실제 Chromium에서 격리 API로 연결한 문서 전체 삭제·복원 모달과 채팅 응답을 확인했다. 실제 사용자 DB를 시험하지 않았으며 웹 프록시는 읽기 전용 복원 preview로 별도 확인했다.
- 상세 실행 로그·격리 DB는 Git 제외 `tmp/rag-local-startup-review-2026-10-16/`에 보존한다. 팀원이 내려받을 수 있는 게시 산출물로 표현하지 않는다.

## 게시·원격 확인

[PR #16](https://github.com/KANT-2nd-project/sanaebi/pull/16)의 [통합 CI](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38807107029)가 Python·웹·ARM64 이미지에서 통과했다. main 병합 SHA는 `2e3866ebc4d6d85392a59ff5e098a581e92212a7`이며 배포를 건너뛰지 않았다. Delivery·원격 확인 결과는 실행 후 아래에 기록한다. 배포 전 원격은 full, indexer 없음, 구형 host helper·Compose였으며 host 기본 원본 SHA는 저장소 원본과 일치했다.

실제 자정 시각의 실행, 사람 검수, 답변 품질 일반화는 이번 자동 검증과 구분한다. 운영 삭제·복원 시험은 격리 DB에서만 수행한다.


### 첫 Delivery의 SSH 연결 중단과 보완

[첫 Delivery](https://github.com/KANT-2nd-project/sanaebi/actions/runs/38807952869)는 Python·웹·이미지를 통과했지만 배포 SSH가 `Broken pipe`(exit255)로 끊겼다. 당시 서버의 기본 복원 벡터 준비 프로세스는 계속 계산 중이었고 기존 full 릴리스가 서비스 중이었다. SSH의 유휴 연결 종료가 원인 후보이며 네트워크 원인 자체를 확정하지 않는다.

[PR #17](https://github.com/KANT-2nd-project/sanaebi/pull/17)은 runner SSH에 `ServerAliveInterval 30`, `ServerAliveCountMax 6`을 추가한다. 실제 workflow의 설정 블록을 임시 HOME에서 실행하고 `ssh -G`로 유효값을 확인하는 테스트는 수정 전 실패·수정 후 통과했다. 독립 검토에서도 설정 적용을 확인했다. 이는 실제 장시간 배포 성공을 대신하지 않는다. 기존 배포 작업 종료 전에 중복 실행하지 않는다.
